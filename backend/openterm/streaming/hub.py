"""Subscription hub: many clients x many panels -> one upstream subscription per symbol.

Ticks are coalesced per symbol (latest wins) and flushed to each client as one compact frame
every FLUSH_S. A slow client never blocks others: its pending ticks keep coalescing until its
sender catches up, so it always converges on the latest prices.
"""

import asyncio
import contextlib
import logging
import time
from collections import deque

import orjson
from fastapi import WebSocket

from ..symbols import SYNTHETIC_RE
from .tick import Tick

log = logging.getLogger("openterm.hub")
FLUSH_S = 0.025


class Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.symbols: set[str] = set()
        self.pending: dict[str, Tick] = {}
        self.ready = asyncio.Event()
        self.sent_frames = 0
        self.outbox: deque[list] = deque(maxlen=1000)  # Phase 11: non-tick frames (jobs), sent before ticks

    def offer(self, ticks: dict[str, Tick]) -> None:
        hit = False
        for s in self.symbols & ticks.keys():
            self.pending[s] = ticks[s]
            hit = True
        if hit:
            self.ready.set()

    async def send_json(self, obj) -> None:
        await self.ws.send_text(orjson.dumps(obj).decode())

    def push(self, frame: list) -> None:
        self.outbox.append(frame)
        self.ready.set()

    async def sender(self) -> None:
        while True:
            await self.ready.wait()
            self.ready.clear()
            while self.outbox:
                await self.send_json(self.outbox.popleft())
            batch, self.pending = self.pending, {}
            if batch:
                await self.send_json(["T", [t.wire() for t in batch.values()]])
                self.sent_frames += 1


class Hub:
    def __init__(self, yahoo, poller, synthetic=None, on_tick=None, iex=None):
        self.yahoo = yahoo
        self.poller = poller
        self.synthetic = synthetic
        self.iex = iex  # Phase 13: real-time IEX trades (Alpaca keys); None or keyless = Yahoo only
        self.on_tick = on_tick
        self.clients: set[Client] = set()
        self.refs: dict[str, int] = {}
        self._pending: dict[str, Tick] = {}
        self._task: asyncio.Task | None = None
        self.ticks_in = 0
        self._rate: deque[tuple[float, int]] = deque(maxlen=50)

    def broadcast(self, frame: list) -> None:
        """Phase 11: one frame to every connected client (job progress)."""
        for c in self.clients:
            c.push(frame)

    def start(self) -> None:
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # --- upstream -----------------------------------------------------------------------------
    def emit(self, tick: Tick) -> None:
        if self.iex is not None and tick.source in ("y", "p") and self.iex.covers(tick.symbol):
            return  # real-time IEX owns this symbol while it answers; Yahoo resumes if it stops
        self.ticks_in += 1
        self._pending[tick.symbol] = tick
        if self.on_tick:
            self.on_tick(tick)

    async def _sync_upstream(self) -> None:
        symbols = set(self.refs)
        synth = {s for s in symbols if SYNTHETIC_RE.match(s)} if self.synthetic else set()
        real = symbols - synth
        await self.yahoo.set_symbols(real)
        await self.poller.set_symbols(real)
        if self.iex is not None:
            await self.iex.set_symbols(real)
        if self.synthetic:
            await self.synthetic.set_symbols(synth)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_S)
            if not self._pending:
                continue
            batch, self._pending = self._pending, {}
            for c in self.clients:
                c.offer(batch)

    # --- clients ------------------------------------------------------------------------------
    async def subscribe(self, client: Client, symbols: list[str]) -> None:
        new = [s for s in symbols if s not in client.symbols]
        client.symbols.update(new)
        changed = False
        for s in new:
            self.refs[s] = self.refs.get(s, 0) + 1
            changed |= self.refs[s] == 1
        if changed:
            await self._sync_upstream()

    async def unsubscribe(self, client: Client, symbols: list[str]) -> None:
        gone = [s for s in symbols if s in client.symbols]
        client.symbols.difference_update(gone)
        changed = False
        for s in gone:
            self.refs[s] -= 1
            if self.refs[s] <= 0:
                del self.refs[s]
                changed = True
        if changed:
            await self._sync_upstream()

    async def disconnect(self, client: Client) -> None:
        self.clients.discard(client)
        await self.unsubscribe(client, list(client.symbols))

    def stats(self) -> dict:
        now = time.time()
        self._rate.append((now, self.ticks_in))
        t0, n0 = self._rate[0]
        return {
            "clients": len(self.clients),
            "symbols": len(self.refs),
            "ticks_in": self.ticks_in,
            "ticks_per_s": (self.ticks_in - n0) / (now - t0) if now > t0 else None,
            "yahoo_stream": self.yahoo.status,
            "yahoo_messages": self.yahoo.messages,
            "synthetic": self.synthetic is not None,
            "iex": self.iex.status if self.iex is not None else "OFF",
        }
