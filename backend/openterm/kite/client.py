"""HTTP calls to the Kite Connect API (market data and the login exchange only). Headers: `X-Kite-Version: 3` and
`Authorization: token api_key:access_token`. Rate limits (3 requests/s historical, 10 requests/s otherwise) go through `ratelimit`.
A 403 TokenException on any call marks the login expired and raises a DataError that starts `KITE LOGIN EXPIRED`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..ratelimit import RateLimited, TokenBucket
from ..redact import redact
from . import KITE_API
from .session import EXPIRED_MESSAGE, IST, KiteSession

#: Kite's per-call window for historical bars, in days, by interval
HISTORY_WINDOW_DAYS = {"minute": 60, "3minute": 100, "5minute": 100, "10minute": 100, "15minute": 200, "30minute": 200,
                       "60minute": 400, "day": 2000}
INTERVALS = {"1m": "minute", "5m": "5minute", "15m": "15minute", "30m": "30minute", "60m": "60minute", "1d": "day"}
MAX_QUOTE_BATCH = 500


class KiteLoginFailed(Exception):
    pass


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()


def _error(kind: str, message: str):
    from ..service import DataError

    return DataError(kind, message)


class KiteClient:
    def __init__(self, session: KiteSession, http: httpx.AsyncClient):
        self.session = session
        self.http = http
        self.hist_bucket = TokenBucket(3.0, 3)
        self.api_bucket = TokenBucket(10.0, 10)

    async def _send(self, method: str, path: str, params: dict[str, Any] | None, historical: bool, data: dict | None = None) -> httpx.Response:
        key, token = self.session.auth()
        bucket = self.hist_bucket if historical else self.api_bucket
        try:
            await bucket.acquire(max_wait=5.0)
        except RateLimited as e:
            raise _error("unavailable", "KITE RATE LIMITED: TOO MANY REQUESTS, TRY AGAIN") from e
        headers = {"X-Kite-Version": "3", "Authorization": f"token {key}:{token}", "User-Agent": "OpenTerm/0.1"}
        try:
            r = await self.http.request(method, f"{KITE_API}{path}", params=params, data=data, headers=headers, timeout=20.0)
        except httpx.TimeoutException as e:
            raise _error("unavailable", "KITE TIMEOUT") from e
        except httpx.HTTPError as e:
            raise _error("unavailable", f"KITE UNREACHABLE ({type(e).__name__})") from e
        if r.status_code == 403 and "TokenException" in r.text:
            self.session.mark_expired()
            raise _error("login_expired", EXPIRED_MESSAGE)
        if r.status_code == 429:
            raise _error("unavailable", "KITE RATE LIMITED (429)")
        return r

    @staticmethod
    def _json(r: httpx.Response) -> Any:
        try:
            body = r.json()
        except ValueError as e:
            raise _error("unavailable", f"KITE ANSWERED HTTP {r.status_code} WITHOUT JSON") from e
        if r.status_code >= 400 or body.get("status") != "success":
            msg = redact(str(body.get("message") or f"HTTP {r.status_code}"))
            kind = "not_found" if body.get("error_type") == "InputException" else "unavailable"
            raise _error(kind, f"KITE: {msg}")
        return body.get("data")

    async def get_json(self, path: str, params: dict[str, Any] | None = None, historical: bool = False) -> Any:
        return self._json(await self._send("GET", path, params, historical))

    async def get_text(self, path: str) -> str:
        r = await self._send("GET", path, None, False)
        if r.status_code >= 400:
            raise _error("unavailable", f"KITE: HTTP {r.status_code}")
        return r.text

    async def quote(self, keys: list[str]) -> dict[str, dict]:
        """`GET /quote`, up to 500 instruments per call. Keys Kite does not know are simply absent from the answer."""
        out: dict[str, dict] = {}
        for i in range(0, len(keys), MAX_QUOTE_BATCH):
            out.update(await self.get_json("/quote", {"i": keys[i : i + MAX_QUOTE_BATCH]}) or {})
        return out

    async def candles(self, token: int, interval: str, start: datetime, end: datetime) -> list[list]:
        """Bars between two instants, chunked to Kite's per-call window, oldest first, with open interest (`oi=1`)."""
        step = timedelta(days=HISTORY_WINDOW_DAYS[interval])
        out: list[list] = []
        seen: set[str] = set()
        cur = start.astimezone(IST)
        stop = end.astimezone(IST)
        while cur <= stop:
            chunk_end = min(cur + step, stop)
            params = {"from": cur.strftime("%Y-%m-%d %H:%M:%S"), "to": chunk_end.strftime("%Y-%m-%d %H:%M:%S"), "oi": 1}
            data = await self.get_json(f"/instruments/historical/{token}/{interval}", params, historical=True)
            for c in (data or {}).get("candles") or []:
                if c[0] not in seen:
                    seen.add(c[0])
                    out.append(c)
            cur = chunk_end + timedelta(seconds=1)
        return out

    async def exchange_token(self, request_token: str) -> dict:
        """The login exchange: `POST /session/token` with checksum = sha256(api_key + request_token + api_secret). Returns the answer's data."""
        creds = self.session.credentials()
        if creds is None:
            raise KiteLoginFailed("KEY REQUIRED: set KITE_API_KEY in APIKEYS")
        key, secret = creds
        try:
            r = await self.http.post(f"{KITE_API}/session/token", headers={"X-Kite-Version": "3", "User-Agent": "OpenTerm/0.1"},
                                     data={"api_key": key, "request_token": request_token, "checksum": checksum(key, request_token, secret)},
                                     timeout=20.0)
        except httpx.HTTPError as e:
            raise KiteLoginFailed(f"KITE UNREACHABLE ({type(e).__name__})") from e
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code != 200 or body.get("status") != "success" or not (body.get("data") or {}).get("access_token"):
            raise KiteLoginFailed(redact(str(body.get("message") or f"HTTP {r.status_code}"), [key, secret, request_token]))
        return body["data"]
