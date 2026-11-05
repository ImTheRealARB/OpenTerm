"""Upstox market data (READ-ONLY) with the free Analytics Token: Indian shares and indices, candles and quotes.

A key unlocks more, never gates the basics: `supports()` is false without UPSTOX_ANALYTICS_TOKEN, and for any symbol that is
not an NSE / BSE share or one of the three indices, so the router skips it and Yahoo answers. It sits above Yahoo in
providers/hierarchy.py because it is real time and its intraday history reaches back to January 2022 (Yahoo: 60 days).

The Analytics Token is the one Upstox offers for read-only data: valid one year, GET endpoints only, no static IP, and it
cannot place orders. There is no order surface here. The token travels in an Authorization header, never in a URL.

Built from the official docs, NOT from recordings (no token was available): fixtures and tests are doc-shaped. Expect the
first live call to be the real test; a shape change shows as an ERR line and Yahoo answers, never as wrong numbers.
"""

from __future__ import annotations

import asyncio
import time
import zlib
from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx

from ..models import Bars, Quote
from ..ranges import range_days
from ..ratelimit import RateLimited
from ..redact import redact
from . import upstox_parse as up
from .base import HISTORY, QUOTES, Provider, ProviderError

IST = ZoneInfo("Asia/Kolkata")
TABLE_TTL_S = 86400.0  # the instruments files refresh about 6 AM daily
KV_KEY = "upstox:instruments"
MAX_WINDOWS = 70  # one request per window; 5-minute candles over 5 years is about 66
QUOTE_BATCH = 100  # the docs do not state the per-call limit (they only name error UDAPI100043); stay well under typical limits
PARALLEL = 4
MINUTE_INTERVALS = ("1m", "2m", "5m", "15m", "30m", "60m", "90m")


class UpstoxProvider(Provider):
    name = "upstox"
    label = "Upstox (free Analytics Token, read-only)"
    capabilities = frozenset({HISTORY, QUOTES})
    markets = "NSE and BSE shares, Nifty 50, Nifty Bank, Sensex: real-time quotes; minute candles from 2022, daily from 2000"
    terms = "Free read-only Analytics Token (UPSTOX_ANALYTICS_TOKEN in APIKEYS), valid 1 year, 500 requests/minute. No orders."
    rate = (8.0, 20)  # docs: 50/s and 500/minute for standard APIs; 500/minute is 8.3/s sustained
    max_wait = 3.0
    timeout = 10.0
    key_name = "UPSTOX_ANALYTICS_TOKEN"
    headers: ClassVar[dict[str, str]] = {"Accept": "application/json"}

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.source = "upstox (doc-shaped fixture, NOT A RECORDING)" if self.fixtures else "upstox"
        self._token = ""
        self.db = None
        self._table: dict[str, dict] | None = None
        self._table_at = 0.0
        self._lock = asyncio.Lock()

    # --- switching on -------------------------------------------------------------------------------------------
    @property
    def has_key(self) -> bool:
        return bool(self._token)

    def set_keys(self, values: dict[str, str] | None) -> None:
        self._token = (values or {}).get("UPSTOX_ANALYTICS_TOKEN", "")

    def attach(self, db) -> None:
        """The instruments table is kept in the kv table for 24 h so a restart does not download it again."""
        self.db = db

    @property
    def intraday_days(self) -> dict[str, int]:  # type: ignore[override]
        days = up.depth_days(datetime.now(IST).date())
        return {i: days for i in MINUTE_INTERVALS}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        if not self.has_key or capability not in self.capabilities:
            return False
        # The router asks about the capability first (symbol None) and then per symbol.
        return symbol is None or up.classify(symbol) is not None

    # --- HTTP ---------------------------------------------------------------------------------------------------
    async def _api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._token:
            raise ProviderError("key_required", "UPSTOX_ANALYTICS_TOKEN is not set")
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        try:
            r = await self.http.get(f"{up.BASE}{path}", params=params, timeout=self.timeout,
                                    headers={**self.headers, "Authorization": f"Bearer {self._token}"})
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        if r.status_code == 429:
            raise ProviderError("rate_limited", "429 from Upstox")
        if r.status_code == 401:
            raise ProviderError("key_required", redact("Upstox refused the Analytics Token (expired or revoked: generate a new one)", [self._token]))
        try:
            body = r.json()
        except ValueError as e:
            raise ProviderError("unavailable", f"HTTP {r.status_code}, non-JSON answer") from e
        if r.status_code >= 400 or (isinstance(body, dict) and body.get("status") == "error"):
            errs = (body.get("errors") if isinstance(body, dict) else None) or [{}]
            code = str((errs[0] or {}).get("error_code") or "")
            msg = redact(str((errs[0] or {}).get("message") or f"HTTP {r.status_code}"), [self._token])
            if code in ("UDAPI100011", "UDAPI1021", "UDAPI1087"):  # documented: invalid instrument key
                raise ProviderError("not_found", f"{code} {msg}")
            if code == "UDAPI1148":  # documented: invalid date range
                raise ProviderError("depth", f"{code} {msg}")
            if code in ("UDAPI100050", "UDAPI100016"):  # documented: invalid token / credentials
                raise ProviderError("key_required", f"{code} {msg}")
            raise ProviderError("unavailable", f"{code} {msg}".strip())
        return body.get("data") if isinstance(body, dict) else None

    # --- instruments --------------------------------------------------------------------------------------------
    async def _load_table(self) -> dict[str, dict]:
        async with self._lock:
            if self._table is not None and time.time() - self._table_at < TABLE_TTL_S:
                return self._table
            if self.db is not None:
                async with self.db.execute("SELECT value FROM kv WHERE key=?", (KV_KEY,)) as cur:
                    row = await cur.fetchone()
                if row:
                    try:
                        import orjson

                        blob = orjson.loads(await asyncio.to_thread(zlib.decompress, row[0]))
                        if time.time() - blob["at"] < TABLE_TTL_S:
                            self._table, self._table_at = blob["table"], blob["at"]
                            return self._table
                    except (zlib.error, ValueError, KeyError, TypeError):
                        pass  # damaged or old cache entry: download again
            table: dict[str, dict] = {}
            for url in up.INSTRUMENT_FILES:
                try:
                    r = await self.http.get(url, timeout=60.0)
                except httpx.HTTPError as e:
                    raise ProviderError("unavailable", f"instruments file: {type(e).__name__}") from e
                if r.status_code >= 400:
                    raise ProviderError("unavailable", f"instruments file: HTTP {r.status_code}")
                table.update(await asyncio.to_thread(up.parse_instruments, r.content))
            self._table, self._table_at = table, time.time()
            if self.db is not None:
                import orjson

                blob = await asyncio.to_thread(zlib.compress, orjson.dumps({"at": self._table_at, "table": table}), 3)
                await self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                      (KV_KEY, blob))
                await self.db.commit()
            return table

    async def _resolve(self, symbol: str) -> tuple[str, str, str | None]:
        """(instrument key, exchange, name) for a Yahoo-style symbol, or not_found."""
        c = up.classify(symbol)
        if c is None:
            raise ProviderError("unsupported", "not an Upstox symbol")
        kind, segment_or_key, exchange, base = c
        if kind == "index":
            return segment_or_key, exchange, base
        rec = (await self._load_table()).get(f"{segment_or_key}:{base}")
        if rec is None:
            raise ProviderError("not_found", f"{symbol} is not in the Upstox instruments file")
        return rec["key"], exchange, rec.get("name")

    # --- capabilities -------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        plan = up.INTERVAL_PLAN.get(interval)
        if plan is None:
            raise ProviderError("unsupported", f"Upstox has no {interval} candles")
        unit, n = plan
        key, exchange, _ = await self._resolve(symbol)
        today = datetime.now(IST).date()
        wins = up.windows(today, range_days(range_), unit, n)
        if len(wins) > MAX_WINDOWS:
            raise ProviderError("depth", f"{interval} over {range_} needs {len(wins)} Upstox requests (limit {MAX_WINDOWS}): use a longer candle")
        sem = asyncio.Semaphore(PARALLEL)

        async def one(w: tuple) -> list:
            async with sem:
                data = await self._api(up.candle_path(key, unit, n, w[0], w[1]))
            return (data or {}).get("candles") or []

        rows: list = []
        for part in await asyncio.gather(*(one(w) for w in wins)):
            rows.extend(part)
        candles = up.parse_candles(rows)
        if not candles:
            raise ProviderError("not_found", "no bars")
        has_oi = any(c[6] for c in candles)
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency="INR", exchange=exchange, tz="Asia/Kolkata",
            t=[c[0] for c in candles], o=[c[1] for c in candles], h=[c[2] for c in candles], l=[c[3] for c in candles],
            c=[c[4] for c in candles], v=[c[5] for c in candles], source=self.source, as_of=time.time(), adj=None, fund=None,
            oi=[c[6] for c in candles] if has_oi else None,
        )

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        wanted: dict[str, str] = {}  # instrument key -> symbol
        meta: dict[str, tuple[str, str | None]] = {}
        for s in symbols:
            try:
                key, exchange, name = await self._resolve(s)
            except ProviderError as e:
                if e.kind in ("not_found", "unsupported"):
                    continue  # the router asks the next source for the ones this one lacks
                raise
            wanted[key] = s
            meta[s] = (exchange, name)
        if not wanted:
            return []
        out: list[Quote] = []
        keys = list(wanted)
        for i in range(0, len(keys), QUOTE_BATCH):
            batch = keys[i:i + QUOTE_BATCH]
            data = await self._api("/v3/market-quote/ohlc", {"instrument_key": ",".join(batch), "interval": "1d"})
            now = time.time()
            for q in up.parse_quotes(data, {k: wanted[k] for k in batch}):
                exchange, name = meta[q["symbol"]]
                prev = q["prev_close"]
                change = q["price"] - prev if prev is not None else None
                out.append(Quote(
                    symbol=q["symbol"], name=name, currency="INR", exchange=exchange, tz="Asia/Kolkata", price=q["price"],
                    prev_close=prev, change=change, change_pct=change / prev * 100 if change is not None and prev else None,
                    open=q["open"], high=q["high"], low=q["low"], volume=int(q["volume"]) if q["volume"] is not None else None,
                    source=self.source, as_of=now,
                ))
        return out

    async def probe(self) -> None:
        await self._api("/v3/market-quote/ltp", {"instrument_key": "NSE_INDEX|Nifty 50"})
