"""OpenSky Network: live aircraft positions (ADS-B) for the FLT panel. Works with no key; a free account raises the daily credit limit.

Docs: https://openskynetwork.github.io/opensky-api/rest.html (read 2026-11-05).

  Anonymous      : 400 credits a day, positions to a 10 s resolution, no history. This is the default and needs nothing.
  Signed in      : 4000 credits a day (standard account), 5 s resolution. Uses OAuth2 "client credentials": the user makes an API client on the
                   OpenSky account page and gets a client id + client secret; we POST them to the token URL and receive a short-lived (30 min)
                   access token that is sent as `Authorization: Bearer <token>`. A 401 means the token expired: fetch a new one, retry ONCE.
  Credits        : one `states/all` call costs 1-4 credits by the AREA of the box (`world/flights.credits_for`). The answer's
                   `X-Rate-Limit-Remaining` header says what is left; a 429 carries `X-Rate-Limit-Retry-After-Seconds`.

Guard rails (this is a metered service, so every one of them protects the user's credits):
  - an identical box is answered from memory for CACHE_S seconds (30), so a repeat or a second panel costs nothing;
  - after a 429 the provider makes NO further network call until the retry time the server named has passed, and says so;
  - a bad login is an error, never a silent fall back to anonymous (that would hide a typo in the key and drain the small anonymous quota).

HONESTY: the live service refused every connection from the machine this was written on, so the request/response shapes and the whole OAuth
flow follow the documentation and are tested with a fake transport. Nothing here has run against a real OpenSky account.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, ClassVar

import httpx
import orjson

from .. import redact
from ..world import flights
from .base import Provider, ProviderError

FLIGHTS = flights.FLIGHTS
STATES_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
CACHE_S = 30.0  # identical box: answered from memory (the anonymous resolution is 10 s, so nothing newer exists inside this time anyway)
REFRESH_MARGIN_S = 60.0  # fetch a new token this long before the old one runs out, so a call never starts with a token about to die
DEFAULT_RETRY_S = 60.0  # a 429 without a retry header: back off this long (the message says the header was missing)
MAX_CACHE = 64


def _wait_text(seconds: float) -> str:
    """'45 S', '12 MIN' or '3 H 20 MIN' for the message that tells the user when to try again."""
    s = int(max(0, seconds))
    if s < 120:
        return f"{s} S"
    if s < 7200:
        return f"{s // 60} MIN"
    return f"{s // 3600} H {s % 3600 // 60} MIN"


async def check_key(values: dict[str, str], http: httpx.AsyncClient) -> tuple[str, str | None]:
    """APIKEYS test: ask the token endpoint for a token. `(state, detail)`: OK | INVALID | ERROR. Spends no flight credits.

    The token endpoint answers HTTP 200 with an access_token for a good client and 401 `invalid_client` for a bad one (OAuth2 standard; checked
    against the docs only)."""
    try:
        r = await http.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": values["OPENSKY_CLIENT_ID"],
                                             "client_secret": values["OPENSKY_CLIENT_SECRET"]}, timeout=10.0)
    except httpx.HTTPError as e:
        return "ERROR", type(e).__name__
    if r.status_code == 200 and b"access_token" in r.content:
        return "OK", None
    if r.status_code in (400, 401):
        return "INVALID", f"HTTP {r.status_code}: OPENSKY REJECTED THE CLIENT ID OR SECRET"
    return "ERROR", f"HTTP {r.status_code}"


class OpenSkyProvider(Provider):
    name = "opensky"
    label = "OpenSky Network (ADS-B aircraft, free; optional account)"
    capabilities = frozenset({FLIGHTS})
    markets = "Live aircraft positions from volunteer ADS-B receivers, worldwide but patchy (strong in Europe and North America, thin over oceans and some regions)"
    terms = ("Free. Anonymous: 400 credits a day. With a free OpenSky account (OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET in APIKEYS): 4000 a day. "
             "Positions are as reported by aircraft transponders; coverage is partial.")
    rate = (0.5, 2)  # at most one call every 2 s: a metered service, and a human reads the table
    max_wait = 1.0
    timeout = 20.0  # a global (CALLSIGN) answer is a few MB and OpenSky can be slow
    key_name = "OPENSKY_CLIENT_ID"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        self.source = "opensky (doc-shaped fixture, NOT A RECORDING)" if self.fixture else "opensky"
        self._id = ""
        self._secret = ""
        self._token = ""
        self._token_exp = 0.0  # clock() value after which the token is dead
        self._token_lock = asyncio.Lock()  # two panels asking at once must not fetch two tokens
        self._blocked_until = 0.0  # clock() value before which we do not call (set by a 429)
        self._cache: dict[Any, tuple[float, dict[str, Any]]] = {}
        self.clock: Callable[[], float] = time.time  # tests replace this to age tokens and caches without sleeping
        self.token_fetches = 0  # how many times we asked the token endpoint (tests assert on it)

    # --- keys ------------------------------------------------------------------------------------------------------------------
    @property
    def has_key(self) -> bool:
        """True when BOTH halves of the login are set. The provider works without it, so supports() never looks at this."""
        return bool(self._id and self._secret)

    def set_keys(self, values: dict[str, str] | None) -> None:
        v = values or {}
        self._id, self._secret = v.get("OPENSKY_CLIENT_ID", ""), v.get("OPENSKY_CLIENT_SECRET", "")
        self._token, self._token_exp = "", 0.0  # a new login drops the old token
        self._cache.clear()  # cached answers belong to the other access level
        if self._secret:
            redact.register([self._secret])

    # --- OAuth2 client credentials (docs-shaped, see the module note) --------------------------------------------------------------
    async def _bearer(self) -> str | None:
        """A valid access token, fetching or refreshing it when needed. None when no login is set (anonymous)."""
        if not self.has_key:
            return None
        if self._token and self.clock() < self._token_exp - REFRESH_MARGIN_S:
            return self._token
        async with self._token_lock:
            if self._token and self.clock() < self._token_exp - REFRESH_MARGIN_S:  # another caller refreshed while we waited
                return self._token
            return await self._fetch_token()

    async def _fetch_token(self) -> str:
        self.token_fetches += 1
        try:
            r = await self.http.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": self._id, "client_secret": self._secret},
                                     headers={"User-Agent": "OpenTerm"}, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "OPENSKY LOGIN TIMED OUT") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", f"OPENSKY LOGIN FAILED: {type(e).__name__}") from e  # never str(e): it can echo the URL
        if r.status_code in (400, 401):
            raise ProviderError("unavailable", f"OPENSKY LOGIN REJECTED (HTTP {r.status_code}): CHECK OPENSKY_CLIENT_ID AND OPENSKY_CLIENT_SECRET IN APIKEYS")
        if r.status_code != 200:
            raise ProviderError("unavailable", f"OPENSKY LOGIN FAILED (HTTP {r.status_code})")
        try:
            body = orjson.loads(r.content)
            token, ttl = body["access_token"], float(body["expires_in"])
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise ProviderError("unavailable", "OPENSKY LOGIN ANSWER HAS NO access_token/expires_in") from e
        if not isinstance(token, str) or not token or ttl <= 0:
            raise ProviderError("unavailable", "OPENSKY LOGIN ANSWER HAS AN EMPTY TOKEN")
        redact.register([token])  # the token is a credential too: keep it out of logs and error text
        self._token, self._token_exp = token, self.clock() + ttl
        return token

    # --- the one capability ---------------------------------------------------------------------------------------------------------
    async def flights(self, box: tuple[float, float, float, float] | None) -> dict[str, Any]:
        """Aircraft with a position inside `box` (south, west, north, east), or everywhere when `box` is None (the CALLSIGN search; 4 credits).

        Returns `{"time", "rows", "received", "no_position", "credits_remaining", "authenticated", "fixture"}`; rows are `world/flights.parse_states` rows.
        Raises ProviderError("rate_limited") with the wait when credits are gone, and never calls again until that time has passed."""
        # The box was already validated by the service (`flights.parse_args`), before any provider is asked.
        now = self.clock()
        key = box
        hit = self._cache.get(key)
        if hit and now - hit[0] < CACHE_S:
            return hit[1]
        if now < self._blocked_until:
            raise ProviderError("rate_limited", f"OPENSKY CREDITS EXHAUSTED OR RATE LIMITED: NO NEW CALL FOR {_wait_text(self._blocked_until - now)}")
        meta = await self._call(box, retry_on_401=True)
        if len(self._cache) >= MAX_CACHE:
            self._cache.pop(next(iter(self._cache)))  # oldest first: a dict keeps insertion order
        self._cache[key] = (self.clock(), meta)
        return meta

    async def _call(self, box: tuple[float, float, float, float] | None, retry_on_401: bool) -> dict[str, Any]:
        token = await self._bearer()
        headers = dict(self.headers)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        params = {} if box is None else dict(zip(("lamin", "lomin", "lamax", "lomax"), (f"{v:g}" for v in box), strict=True))
        try:
            await self.bucket.acquire(self.max_wait)
        except Exception as e:  # RateLimited from our own bucket
            raise ProviderError("rate_limited", "OPENSKY: TOO MANY CALLS FROM OPENTERM, WAIT A MOMENT") from e
        try:
            r = await self.http.get(STATES_URL, params=params, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "OPENSKY TIMED OUT") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", f"OPENSKY UNREACHABLE: {type(e).__name__}") from e
        if r.status_code == 429:
            raw = r.headers.get("X-Rate-Limit-Retry-After-Seconds")
            try:
                wait = float(raw) if raw is not None else DEFAULT_RETRY_S
            except ValueError:
                wait = DEFAULT_RETRY_S
            self._blocked_until = self.clock() + wait  # no more calls until then: a refused call must not be repeated
            who = "ACCOUNT" if token else "ANONYMOUS"
            missing = "" if raw is not None else " (NO RETRY TIME SENT, ASSUMING 60 S)"
            raise ProviderError("rate_limited", f"OPENSKY {who} CREDITS EXHAUSTED OR RATE LIMITED: RETRY IN {_wait_text(wait)}{missing}")
        if r.status_code == 401 and token:
            self._token, self._token_exp = "", 0.0  # the docs say 401 = expired token: drop it
            if retry_on_401:
                return await self._call(box, retry_on_401=False)  # exactly one retry with a fresh token
            raise ProviderError("unavailable", "OPENSKY REJECTED THE ACCESS TOKEN TWICE: CHECK THE CLIENT ID AND SECRET IN APIKEYS")
        if r.status_code in (401, 403):
            raise ProviderError("unavailable", f"OPENSKY REFUSED THE REQUEST (HTTP {r.status_code})")
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"OPENSKY HTTP {r.status_code}")
        try:
            t, rows, no_position = flights.parse_states(orjson.loads(r.content))
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", "OPENSKY SENT NON-JSON") from e
        except flights.FlightsError as e:
            raise ProviderError("unavailable", str(e)) from e
        left = r.headers.get("X-Rate-Limit-Remaining")
        return {"time": t, "rows": rows, "received": len(rows) + no_position, "no_position": no_position,
                "credits_remaining": int(left) if left is not None and left.lstrip("-").isdigit() else None,
                "authenticated": bool(token), "fixture": self.fixture}

    # No probe(): the scheduler would call it every 30 s while the provider is tripped, and every call spends a metered credit.
