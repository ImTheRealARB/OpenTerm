"""Upstream tick sources. Each exposes set_symbols(); the hub feeds it the union of all subscriptions.

- YahooStream: one websocket to Yahoo's public streamer for every subscribed symbol.
- Poller: REST quotes on an interval, used while the stream is down (and for markets it doesn't cover).
- SyntheticStream: random-walk ticks for SYNxxxx symbols, enabled only by OPENTERM_SYNTHETIC=1
  for load testing. Its ticks are tagged "s" and the UI labels them SYNTHETIC.
"""

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Callable

import orjson
import websockets

from ..providers.yahoo import UA, day_range
from ..symbols import SYNTHETIC_RE
from .pricing import decode_b64
from .tick import Tick

log = logging.getLogger("openterm.stream")
Emit = Callable[[Tick], None]



class YahooStream:
    URL = "wss://streamer.finance.yahoo.com/?version=2"

    def __init__(self, emit: Emit):
        self.emit = emit
        self.symbols: set[str] = set()
        self.status = "IDLE"
        self.messages = 0
        self._ws = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def set_symbols(self, symbols: set[str]) -> None:
        added, removed = symbols - self.symbols, self.symbols - symbols
        self.symbols = set(symbols)
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                if added:
                    await ws.send(orjson.dumps({"subscribe": sorted(added)}).decode())
                if removed:
                    await ws.send(orjson.dumps({"unsubscribe": sorted(removed)}).decode())
        self._wake.set()

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            if not self.symbols:
                self.status = "IDLE"
                self._wake.clear()
                await self._wake.wait()
                continue
            try:
                self.status = "CONNECTING"
                async with websockets.connect(
                    self.URL,
                    additional_headers={"User-Agent": UA, "Origin": "https://finance.yahoo.com"},
                    open_timeout=8,
                    ping_interval=20,
                    max_queue=4096,
                ) as ws:
                    self._ws = ws
                    await ws.send(orjson.dumps({"subscribe": sorted(self.symbols)}).decode())
                    self.status = "OK"
                    backoff = 1.0
                    log.info("yahoo stream connected (%d symbols)", len(self.symbols))
                    async for raw in ws:
                        self._on_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - any failure: mark down, back off, reconnect
                log.warning("yahoo stream down: %s: %s", type(e).__name__, e)
            finally:
                self._ws = None
            self.status = "DOWN"
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _on_message(self, raw: str | bytes) -> None:
        try:
            msg = orjson.loads(raw)
            d = decode_b64(msg["message"])
        except Exception:  # noqa: BLE001 - one malformed frame must not kill the stream
            log.debug("bad stream frame")
            return
        if "id" not in d or "price" not in d:
            return
        self.messages += 1
        self.emit(Tick(
            symbol=d["id"], price=d["price"], change=d.get("change"), change_pct=d.get("change_pct"),
            volume=d.get("day_volume"), high=day_range(d.get("day_high")), low=day_range(d.get("day_low")),
            time_ms=int(d.get("time") or time.time() * 1000), source="y",
        ))


class Poller:
    """REST fallback: polls quotes for subscribed symbols while the stream is not OK."""

    def __init__(self, emit: Emit, fetch, active: Callable[[], bool], interval_s: float = 5.0):
        self.emit = emit
        self.fetch = fetch  # async (symbols) -> {symbol: envelope | error}
        self.active = active
        self.interval_s = interval_s
        self.symbols: set[str] = set()
        self._task: asyncio.Task | None = None
        self._last: dict[str, float] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def set_symbols(self, symbols: set[str]) -> None:
        self.symbols = set(symbols)
        self._last = {s: p for s, p in self._last.items() if s in self.symbols}  # no memory of symbols nobody watches

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            if not self.symbols or not self.active():
                continue
            try:
                results = await self.fetch(sorted(self.symbols))
            except Exception as e:  # noqa: BLE001 - keep polling; errors show up on SOURCES
                log.info("poll failed: %s", e)
                continue
            for env in results.values():
                q = env.get("data") if isinstance(env, dict) else None
                if not q or q.get("price") is None or env.get("stale"):
                    continue
                prev = self._last.get(q["symbol"])
                self._last[q["symbol"]] = q["price"]
                if prev is None or prev == q["price"]:
                    continue  # first sighting is the snapshot clients already have; unchanged is not a tick
                self.emit(Tick(
                    symbol=q["symbol"], price=q["price"], change=q.get("change"), change_pct=q.get("change_pct"),
                    volume=q.get("volume"), high=q.get("high"), low=q.get("low"),
                    time_ms=int((q.get("market_time") or q.get("as_of") or time.time()) * 1000), source="p",
                ))


class SyntheticStream:
    def __init__(self, emit: Emit, ticks_per_s: float = 20.0):
        self.emit = emit
        self.rate = ticks_per_s
        self.symbols: set[str] = set()
        self.status = "OK"
        self._task: asyncio.Task | None = None
        self._px: dict[str, tuple[float, float]] = {}
        self.ticks = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def set_symbols(self, symbols: set[str]) -> None:
        self.symbols = {s for s in symbols if SYNTHETIC_RE.match(s)}

    async def _run(self) -> None:
        # Rate is driven by elapsed time, not sleep length: Windows timers tick at ~15.6 ms,
        # so counting sleeps would silently under-deliver the advertised ticks/s.
        acc: dict[str, float] = {}
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            t = time.perf_counter()
            dt, last = t - last, t
            now = int(time.time() * 1000)
            for s in self.symbols:
                a = acc.get(s, random.random()) + self.rate * dt
                n = int(a)
                acc[s] = a - n
                if not n:
                    continue
                base, px = self._px.get(s, (100.0, 100.0))
                for _ in range(n):
                    px = round(max(0.01, px * (1 + random.gauss(0, 0.0005))), 2)
                    self.ticks += 1
                self._px[s] = (base, px)
                ch = round(px - base, 2)
                self.emit(Tick(s, px, ch, round(ch / base * 100, 4), None, None, None, now, "s"))


class NullStream:
    """Stands in for YahooStream in fixture mode so tests and the bench never touch the network."""

    status = "OFF"
    messages = 0

    def __init__(self, emit: Emit | None = None):
        self.symbols: set[str] = set()

    def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def set_symbols(self, symbols: set[str]) -> None:
        self.symbols = set(symbols)
