"""The base class for adapters that need an API key (Finnhub, Tradier, Alpaca, FRED, Companies House, Etherscan, Marketaux, api.data.gov ...).

Before this file existed, about ten adapters each copied the same three things: the key fields with `has_key` / `set_keys` / `supports`,
and an authenticated request that turns HTTP trouble into a `ProviderError`. Now they live here once, and an adapter only says what
really differs: which key fields it has, where the key travels (a header, the query string, basic auth) and a few message texts.

How a key reaches an adapter. There are two styles in the codebase, and this class is the first one:

  1. PUSH (this class): the adapter keeps the key in memory. `main.on_key_change` calls `set_keys(store.get(name))` whenever APIKEYS
     saves a key, and once for every provider 2 s after startup (keyring keys). Use it when the key is needed on every call and the
     adapter is built once per app. The adapter reads its key from `app.state.keys`'s values only through `set_keys`, so a key set in
     APIKEYS works at once, with no restart.
  2. PULL (`tradeus.py`, EIA, OpenFIGI): the adapter holds NO key. The service reads `app.state.keys` on each request and passes the
     key into the method. Use it when the key must be checked before the adapter is reached. The two styles are kept apart on
     purpose: unifying them would change when a key is read.

What a keyed request does, in order (the same as every adapter did by hand):
  1. no key: raise `key_required` BEFORE any network call (the panel then says `KEY REQUIRED: set X in APIKEYS`);
  2. `_before_send()` (Marketaux counts its daily budget here);
  3. wait for a rate-limit slot (`rate_limited` if none comes in time);
  4. send the request with the key added by `auth_headers()` / `auth_params()`;
  5. timeout or network error: `unavailable` with a SHORT text (never `str(e)`, which can carry the URL and so the key);
  6. `_check_status(r)`: 429 `rate_limited`, 401/403 `key_required` (the source refused the key; unlike the keyless
     `Provider._request`, which calls that "unavailable"), 404 `not_found` only when the adapter sets `msg_not_found`, else >= 400 `unavailable`.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from .. import errkinds as K
from ..ratelimit import RateLimited
from ..redact import redact
from .base import Provider, ProviderError


class KeyedProvider(Provider):
    key_name: str = ""
    """The label shown on the SOURCES screen and in `KEY REQUIRED` hints. Usually the key's own name in the key store, but not always
    (FRED says "FRED"): it is user-visible text, so it is kept as each adapter had it."""
    key_fields: ClassVar[tuple[str, ...]] = ()
    """Names of the key-store values this adapter needs, e.g. ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY"). Empty = just `key_name`."""
    hide_without_key: ClassVar[bool] = True
    """True: `supports()` is false without a key, so the router skips the source silently (a key unlocks more, never gates the basics).
    False: `supports()` stays true and a call raises `key_required` before any network call, so the panel says KEY REQUIRED."""

    # Message texts. `{code}` becomes the HTTP status. Adapters override what differs.
    msg_rate_limited: str = "429 from upstream"
    msg_refused: str = "Upstream refused the key ({code})"
    msg_not_found: str | None = None
    """None = a 404 is just "HTTP 404" (unavailable), as it was for the adapters that never mapped it."""

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        self._values: dict[str, str] = dict.fromkeys(self._fields(), "")

    # --- key state ------------------------------------------------------------------------------------------------------------
    @classmethod
    def _fields(cls) -> tuple[str, ...]:
        return cls.key_fields or (cls.key_name,)

    @property
    def _key(self) -> str:
        """The key of a single-key adapter (the first field)."""
        return self._values[self._fields()[0]]

    @_key.setter
    def _key(self, value: str) -> None:
        self._values[self._fields()[0]] = value

    @property
    def has_key(self) -> bool:
        """True when EVERY key field is set (Alpaca needs both its id and its secret)."""
        return all(self._values.values())

    def set_keys(self, values: dict[str, str] | None) -> None:
        v = values or {}
        self._values = {f: v.get(f, "") for f in self._fields()}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return (self.has_key or not self.hide_without_key) and capability in self.capabilities

    # --- where the key travels (override ONE of these per adapter) -------------------------------------------------------------
    def auth_headers(self) -> dict[str, str]:
        return {}

    def auth_params(self) -> dict[str, str]:
        """Query parameters added to every call: the key, for sources that only accept it there (and fixed ones such as FRED's file_type)."""
        return {}

    def _before_send(self) -> None:
        """Runs after the key check and before the rate-limit wait (a hook; Marketaux counts its daily budget here)."""

    def _missing_text(self) -> str:
        names = self._fields()
        return f"{names[0]} is not set" if len(names) == 1 else f"{' and '.join(names)} are not set"

    # --- the request ------------------------------------------------------------------------------------------------------------
    async def _request(self, url: str, params: dict[str, Any] | None, timeout: float | None, body: Any = None) -> httpx.Response:
        if not self.has_key:
            raise ProviderError(K.KEY_REQUIRED, self._missing_text())
        self._before_send()
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError(K.RATE_LIMITED, str(e)) from e
        auth = self.auth_params()
        sent = {**(params or {}), **auth} if auth else params
        headers = {**self.headers, **self.auth_headers()}
        try:
            if body is None:
                r = await self.http.get(url, params=sent, headers=headers, timeout=timeout or self.timeout)
            else:
                r = await self.http.post(url, params=sent, json=body, headers=headers, timeout=timeout or self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError(K.UNAVAILABLE, "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError(K.UNAVAILABLE, type(e).__name__) from e  # never str(e): it can carry the URL with the key
        self._check_status(r)
        return r

    def _check_status(self, r: httpx.Response) -> None:
        """Maps an HTTP error to a ProviderError. Adapters whose errors arrive inside the body (FRED, Marketaux) override this with a no-op
        and map the body themselves."""
        code = r.status_code
        if code == 429:
            raise ProviderError(K.RATE_LIMITED, self.msg_rate_limited)
        if code in (401, 403):
            raise ProviderError(K.KEY_REQUIRED, redact(self.msg_refused.format(code=code), list(self._values.values())))
        if code == 404 and self.msg_not_found is not None:
            raise ProviderError(K.NOT_FOUND, self.msg_not_found)
        if code >= 400:
            raise ProviderError(K.UNAVAILABLE, f"HTTP {code}")

    async def get_json(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        r = await self._request(url, params, timeout)
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError(K.UNAVAILABLE, "non-JSON response") from e
