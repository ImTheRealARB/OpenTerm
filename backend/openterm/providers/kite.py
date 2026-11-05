"""Zerodha Kite Connect bars (Phase 15, READ-ONLY; the package is openterm/kite/). First `history` and `quotes` provider for `.NS` / `.BO` /
`^NSEI` / `^NSEBANK` / `^BSESN` and NFO / BFO / MCX / CDS symbols. Symbols Kite does not serve (US, global) are skipped for free.
`supports()` is true while the key is set and a login exists (valid OR expired): an EXPIRED login raises `login_expired`, which costs no
network call and no circuit-breaker strike, so Yahoo answers, `fallback_from` names `kite` and `why_down()` gives the screen its reason
("KITE LOGIN EXPIRED: run KITE LOGIN"). No key, or never logged in: skipped silently (zero keys still works).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

import httpx

from ..kite.client import INTERVALS, KiteClient
from ..kite.instruments import Instruments
from ..kite.session import IST, KiteSession
from ..kite.symbols import FUTURES_EXCHANGES, to_kite
from ..models import Bars, Quote
from ..ranges import range_days
from .base import HISTORY, QUOTES, Provider, ProviderError

#: Measured live on 2026-11-05 with RELIANCE.NS: 5 / 15 / 60 minute bars start on 2015-02-02 (about 11.7 years back, so 4200 days is safe);
#: 1 minute was verified back 10 years (3650). Longer asks are chunked into Kite's per-call windows (kite/client.py HISTORY_WINDOW_DAYS).
INTRADAY_DAYS: dict[str, int] = {"1m": 3650, "5m": 4200, "15m": 4200, "30m": 4200, "60m": 4200}
SESSION_LOOKBACK_DAYS = 7  # how far back a `1D` request looks for the last session (covers long weekends and holidays)
MAX_DAYS = 7305  # about 20 years; `max` is left to Yahoo
OPEN_INTEREST_TYPES = ("FUT", "CE", "PE")  # Kite sends an `oi` column for every bar, but it is 0 throughout for shares and indices
DERIVATIVE_EXCHANGES = (*FUTURES_EXCHANGES, "BFO", "CDS")
#: the underlying's name at the front of a contract's trading symbol: `NIFTY26OCTFUT` -> NIFTY, `BAJAJ-AUTO26NOVFUT` -> BAJAJ-AUTO, `USDINR26N06FUT` -> USDINR
ROOT_RE = re.compile(r"^([A-Z&-]+?)(?:\d{2}[A-Z0-9]|$)")


def _num(v) -> float | None:
    """Kite sends 0 for a price the exchange has not produced yet (an untraded contract's open, high and low): that is no number."""
    return float(v) if v else None


def _stamp(text: str | None) -> int | None:
    """`YYYY-MM-DD HH:MM:SS` (IST) -> epoch seconds. An untraded contract's last_trade_time is the epoch itself (`1970-01-01 05:30:00`): no time."""
    try:
        t = int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST).timestamp()) if text else None
    except ValueError:
        return None
    return t if t and t > 86400 * 365 else None


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
            if any(k.startswith("BSE:") and k[4:].isdigit() for k in keys.values()) and self.instruments is not None:
                # `/quote` only knows the trading symbol (the name); a BSE scrip code (500325.BO) is looked up in the dump first
                dump = await self.instruments.get()
                keys = {s: (f"{r['exchange']}:{r['tradingsymbol']}" if (r := dump.find(k)) else k) for s, k in keys.items()}
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
            market_time = _stamp(d.get("last_trade_time")) or _stamp(d.get("timestamp"))
            out.append(Quote(
                symbol=sym, currency="INR", exchange=key.partition(":")[0], tz="Asia/Kolkata", price=price, prev_close=prev,
                change=price - prev if prev else None, change_pct=(price - prev) / prev * 100 if prev else None,
                open=_num(ohlc.get("open")), high=_num(ohlc.get("high")), low=_num(ohlc.get("low")), volume=int(d["volume"]) if d.get("volume") else None,
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
                raise ProviderError("not_found", await self._missing(key))
            end = datetime.now(IST)
            # 1D means "the last session", as on Yahoo. Ask for a week so a weekend or a holiday before it still finds one, then keep
            # only the newest IST date that came back (below). Longer ranges ask for exactly their length.
            start = end - timedelta(days=SESSION_LOOKBACK_DAYS if range_ == "1d" else max(days, 2))
            candles = await self.client.candles(inst["instrument_token"], kite_interval, start, end)
        except DataError as e:
            raise ProviderError(_kind(e), str(e)) from e
        if not candles:
            raise ProviderError("not_found", "no bars")
        if range_ == "1d":
            last_day = candles[-1][0][:10]  # Kite stamps are local exchange time: "2026-11-05T09:15:00+0530"
            candles = [c for c in candles if c[0][:10] == last_day]
        stamp = lambda c: int(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z").timestamp())
        has_oi = inst["instrument_type"] in OPEN_INTEREST_TYPES and all(len(c) >= 7 for c in candles)
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency="INR", exchange=inst["exchange"], tz="Asia/Kolkata",
            t=[stamp(c) for c in candles], o=[float(c[1]) for c in candles], h=[float(c[2]) for c in candles],
            l=[float(c[3]) for c in candles], c=[float(c[4]) for c in candles], v=[int(c[5]) for c in candles],
            source=self.source, as_of=time.time(), adj=None, fund=None, oi=[float(c[6]) for c in candles] if has_oi else None,
        )

    async def _missing(self, key: str) -> str:
        """Why a key is not in the dump. For a derivative the answer names the contracts that do exist: Kite drops expired contracts, and
        a bare underlying (`NIFTY.NFO`) is not a contract, so the next thing the user needs is the live contract names."""
        text = f"{key} is not in the Kite instrument dump"
        exchange, _, trading = key.partition(":")
        m = ROOT_RE.match(trading)
        if exchange in DERIVATIVE_EXCHANGES and m and self.instruments is not None:
            futures = sorted((r for r in (await self.instruments.get()).chain_rows(exchange, m.group(1), ("FUT",))),
                             key=lambda r: r["expiry"] or "")
            if futures:
                return f"{text} (expired contracts are removed). {m.group(1)} CONTRACTS: {', '.join(r['tradingsymbol'] for r in futures[:4])}"
        return text

    async def probe(self) -> None:
        if self.session is None or not self.session.logged_in:
            raise ProviderError("key_required", self.session.message() if self.session else "KITE NOT ATTACHED")
