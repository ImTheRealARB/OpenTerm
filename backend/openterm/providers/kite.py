"""Zerodha Kite Connect bars (Phase 15, READ-ONLY; the package is openterm/kite/). First `history` and `quotes` provider for `.NS` / `.BO` /
`^NSEI` / `^NSEBANK` / `^BSESN` and NFO / BFO / MCX / CDS symbols. Symbols Kite does not serve (US, global) are skipped for free.
`supports()` is true while the key is set and a login exists (valid OR expired): an EXPIRED login raises `login_expired`, which costs no
network call and no circuit-breaker strike, so Yahoo answers, `fallback_from` names `kite` and `why_down()` gives the screen its reason
("KITE LOGIN EXPIRED: run KITE LOGIN"). No key, or never logged in: skipped silently (zero keys still works).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import httpx

from ..kite.client import INTERVALS, KiteClient
from ..kite.instruments import Instruments
from ..kite.session import IST, KiteSession
from ..kite.symbols import to_kite
from ..models import Bars, Quote
from ..ranges import range_days
from .base import HISTORY, QUOTES, Provider, ProviderError

#: Measured live on 2026-11-05 with RELIANCE.NS: 5 / 15 / 60 minute bars start on 2015-02-02 (about 11.7 years back, so 4200 days is safe);
#: 1 minute was verified back 10 years (3650). Longer asks are chunked into Kite's per-call windows (kite/client.py HISTORY_WINDOW_DAYS).
INTRADAY_DAYS: dict[str, int] = {"1m": 3650, "5m": 4200, "15m": 4200, "30m": 4200, "60m": 4200}
MAX_DAYS = 7305  # about 20 years; `max` is left to Yahoo


def _kind(e) -> str:
    """DataError kind -> ProviderError kind."""
    return {"key_required": "key_required", "not_found": "not_found", "login_expired": "login_expired"}.get(e.kind, "unavailable")


class KiteProvider(Provider):
    name = "kite"
    label = "Zerodha Kite Connect (read-only, paid app, daily login)"
    capabilities = frozenset({HISTORY, QUOTES})
    markets = "NSE, BSE, NFO, BFO, MCX and CDS quotes and bars with open interest; ticks and option chains with OI (needs a Kite Connect developer app)"
    #: Days of history per candle length (verified live, see docs/DATA_SOURCES.md). Longer asks are chunked into Kite's per-call windows.
    intraday_days = INTRADAY_DAYS
    terms = "Your own Kite Connect subscription (KITE_API_KEY, KITE_API_SECRET in APIKEYS) and a login each trading day. Read-only: no orders."
    rate = (3.0, 3)
    key_name = "KITE_API_KEY"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.session: KiteSession | None = None
        self.client: KiteClient | None = None
        self.instruments: Instruments | None = None
        self.source = "kite (doc-shaped fixture, NOT A RECORDING)" if self.fixtures else "kite"

    def attach(self, session: KiteSession, db=None) -> None:
        """Called by the lifespan once the key store exists: nothing works before this."""
        self.session = session
        self.client = KiteClient(session, self.http)
        self.instruments = Instruments(self.client, db)

    @property
    def has_key(self) -> bool:
        return self.session is not None and self.session.has_key

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        # A valid OR expired login counts: an expired one must be tried and fail visibly (fallback_from), not vanish.
        if capability not in self.capabilities or self.session is None or self.session.state not in ("OK", "KITE LOGIN EXPIRED"):
            return False
        # symbol=None is the router asking "is this capability on at all" (Router.quotes does).
        return symbol is None or to_kite(symbol) is not None

    def why_down(self) -> str | None:
        """The reason shown next to a fallback; None when Kite is fine."""
        return self.session.message() if self.session is not None else None

    def _check_login(self) -> None:
        if self.session is None or self.session.state != "OK":
            raise ProviderError("login_expired", (self.session.message() if self.session else None) or "KITE NOT ATTACHED")

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        """One `GET /quote` call for the whole batch (up to 500). Kite's `ohlc.close` is the previous close."""
        from ..service import DataError

        self._check_login()
        keys = {s: to_kite(s) for s in symbols}
        keys = {s: k for s, k in keys.items() if k}
        if not keys or self.client is None:
            return []
        try:
            data = await self.client.quote(list(keys.values()))
        except DataError as e:
            raise ProviderError(_kind(e), str(e)) from e
        out: list[Quote] = []
        now = time.time()
        for sym, key in keys.items():
            d = data.get(key)
            if not d or d.get("last_price") is None:
                continue  # unknown to Kite: the router records not_found and Yahoo gets a go
            ohlc = d.get("ohlc") or {}
            price, prev = float(d["last_price"]), ohlc.get("close")
            prev = float(prev) if prev else None
            when = d.get("last_trade_time") or d.get("timestamp")
            try:
                market_time = int(datetime.strptime(when, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST).timestamp()) if when else None
            except ValueError:
                market_time = None
            out.append(Quote(
                symbol=sym, currency="INR", exchange=key.partition(":")[0], tz="Asia/Kolkata", price=price, prev_close=prev,
                change=price - prev if prev else None, change_pct=(price - prev) / prev * 100 if prev else None,
                open=ohlc.get("open"), high=ohlc.get("high"), low=ohlc.get("low"), volume=int(d["volume"]) if d.get("volume") else None,
                market_time=market_time, source=self.source, as_of=now,
            ))
        return out

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        from ..service import DataError

        self._check_login()
        key = to_kite(symbol)
        kite_interval = INTERVALS.get(interval)
        days = range_days(range_)
        if key is None or self.client is None or self.instruments is None:
            raise ProviderError("unsupported", "not a Kite symbol")
        if kite_interval is None or days > MAX_DAYS:
            raise ProviderError("unsupported", f"Kite has no {interval} bars for range {range_}")
        try:
            inst = await self.instruments.resolve(key)
            if inst is None:
                raise ProviderError("not_found", f"{key} is not in the Kite instrument dump")
            end = datetime.now(IST)
            start = end - timedelta(days=max(days, 2))
            candles = await self.client.candles(inst["instrument_token"], kite_interval, start, end)
        except DataError as e:
            raise ProviderError(_kind(e), str(e)) from e
        if not candles:
            raise ProviderError("not_found", "no bars")
        stamp = lambda c: int(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z").timestamp())
        has_oi = all(len(c) >= 7 for c in candles)
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency="INR", exchange=inst["exchange"], tz="Asia/Kolkata",
            t=[stamp(c) for c in candles], o=[float(c[1]) for c in candles], h=[float(c[2]) for c in candles],
            l=[float(c[3]) for c in candles], c=[float(c[4]) for c in candles], v=[int(c[5]) for c in candles],
            source=self.source, as_of=time.time(), adj=None, fund=None, oi=[float(c[6]) for c in candles] if has_oi else None,
        )

    async def probe(self) -> None:
        if self.session is None or not self.session.logged_in:
            raise ProviderError("key_required", self.session.message() if self.session else "KITE NOT ATTACHED")
