"""Real-time US last trades from Alpaca's IEX feed (Phase 13 step 7, spec decision J).

Needs the user's Alpaca keys (APIKEYS); without them this does nothing and Yahoo stays the only source. It polls the
latest-trade endpoint once a second for the subscribed US symbols and emits ticks with source code `a` (`RT IEX` on screen).
IEX is one exchange: its price is the last IEX trade, not the consolidated last sale, and its size is IEX volume only.
While a symbol is covered here the hub drops Yahoo's ticks for it, so the two never alternate.
"""

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable

from ..providers.base import ProviderError
from .tick import Tick

log = logging.getLogger("openterm.iex")

US_SYMBOL = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")  # AAPL, BRK-B; not RELIANCE.NS, ^GSPC, EURUSD=X, BTC-USD
COVER_S = 5.0
"""A symbol counts as covered while its last IEX tick is younger than this; after that Yahoo ticks pass again."""
MAX_SYMBOLS = 100


def alpaca_symbol(s: str) -> str:
    return s.replace("-", ".")


class IexPoller:
    def __init__(self, emit: Callable[[Tick], None], provider, prev_close: Callable[[str], float | None], interval_s: float = 1.0):
        self.emit = emit
        self.provider = provider  # providers.alpaca.AlpacaProvider (has_key, latest_trades)
        self.prev_close = prev_close
        self.interval_s = interval_s
        self.symbols: set[str] = set()
        self.status = "OFF"
        self.ticks = 0
        self._task: asyncio.Task | None = None
        self._last: dict[str, tuple[float, int]] = {}  # symbol -> (price, trade time ms) of the last emitted tick
        self._seen: dict[str, float] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def set_symbols(self, symbols: set[str]) -> None:
        self.symbols = {s for s in symbols if US_SYMBOL.match(s)}
        self._seen = {s: t for s, t in self._seen.items() if s in self.symbols}

    def covers(self, symbol: str) -> bool:
        """True while real-time IEX ticks are arriving for `symbol`."""
        t = self._seen.get(symbol)
        return t is not None and time.monotonic() - t < COVER_S and self.provider.has_key

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            if not self.symbols or not self.provider.has_key:
                self.status = "OFF" if not self.provider.has_key else "IDLE"
                continue
            batch = sorted(self.symbols)[:MAX_SYMBOLS]
            try:
                trades = await self.provider.latest_trades([alpaca_symbol(s) for s in batch])
            except ProviderError as e:
                self.status = "KEY REQUIRED" if e.kind == "key_required" else "DOWN"
                log.info("iex poll failed: %s %s", e.kind, e)
                continue
            except Exception as e:  # noqa: BLE001 - keep polling; the failure shows on SOURCES
                self.status = "DOWN"
                log.warning("iex poll crashed: %s", e)
                continue
            self.status = "OK"
            by_alpaca = {alpaca_symbol(s): s for s in batch}
            for asym, (price, size, when) in trades.items():
                sym = by_alpaca.get(asym)
                if sym is None:
                    continue
                self._seen[sym] = time.monotonic()
                if self._last.get(sym) == (price, when):
                    continue  # the same trade again is not a tick
                self._last[sym] = (price, when)
                prev = self.prev_close(sym)
                change = price - prev if prev else None
                self.ticks += 1
                self.emit(Tick(
                    symbol=sym, price=price, change=change, change_pct=change / prev * 100 if change is not None and prev else None,
                    volume=None, high=None, low=None, time_ms=when, source="a",
                ))
