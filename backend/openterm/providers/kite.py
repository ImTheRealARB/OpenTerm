"""Zerodha Kite Connect bars (Phase 15, READ-ONLY; the package is openterm/kite/). First `history` provider for `.NS` / `.BO` / `^NSEI` /
`^NSEBANK` and NFO / MCX symbols, but only while a Kite login is valid: `supports()` is false without a key, logged out, or after the
login expired, so the router skips it and Yahoo answers. A 403 TokenException mid-call marks the login expired and the router falls back
to Yahoo with `fallback_from` naming `kite`.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import httpx

from ..kite.client import INTERVALS, KiteClient
from ..kite.instruments import Instruments
from ..kite.session import IST, KiteSession
from ..kite.symbols import to_kite
from ..models import Bars
from ..ranges import range_days
from .base import HISTORY, Provider, ProviderError

MAX_DAYS = 7305  # about 20 years; `max` is left to Yahoo


class KiteProvider(Provider):
    name = "kite"
    label = "Zerodha Kite Connect (read-only, paid app, daily login)"
    capabilities = frozenset({HISTORY})
    markets = "NSE, BSE, NFO and MCX bars with open interest; ticks and option chains with OI (needs a Kite Connect developer app)"
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
        return (capability in self.capabilities and symbol is not None and self.session is not None and self.session.logged_in
                and to_kite(symbol) is not None)

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        from ..service import DataError

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
            kind = {"key_required": "key_required", "not_found": "not_found"}.get(e.kind, "unavailable")
            raise ProviderError(kind, str(e)) from e
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
