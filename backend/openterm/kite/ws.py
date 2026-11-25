"""Kite ticker: binary packet decoder (pure) and the WebSocket client that feeds the streaming hub (source tag `k`, `RT KITE` on screen).

Message = 2 bytes packet count, then per packet 2 bytes length + the packet; a lone byte is a heartbeat. Packet lengths: 8 (LTP), 28 (index
quote), 32 (index full), 44 (quote), 184 (full: the quote, then last trade time, open interest, its day high and low, exchange timestamp and
five buy and five sell depth entries of quantity, price, orders). Every field is big-endian int32 (orders: int16). Prices are paise: divide
by 100, by 10^7 for currency derivatives (CDS) and by 10^4 for BCD. A short or damaged message is dropped, never raised.
The client connects while a Kite-served symbol is subscribed and the login is valid, and is never started in fixture mode.

Depth and the tape (read-only, Phase 23 gap): the socket normally runs in `quote` mode (44-byte packets, no depth). A panel that asks for
a symbol's book (`pin(sym, depth=True)`, called by the DOM route) puts that ONE instrument into `full` mode (184 bytes: the best five
bids and asks) for `PIN_TTL_S` seconds after its last request; a recording (`hold`) keeps it in full mode until released. Every tick of a
watched symbol also feeds `tape`: Kite sends the latest price and the day's cumulative volume, not each trade, so a print is
(time, last price, volume gained since the previous packet), one per packet that gained volume. Whether it was a buy or a sell is NOT
in the feed: `world/kiteflow.py` guesses it with the tick rule and always says ESTIMATED. Nothing here sends anything to Kite except
subscribe / unsubscribe / mode, and no order surface exists.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from collections import deque
from collections.abc import Callable

from ..streaming.tick import Tick
from . import KITE_WS
from .symbols import to_kite

log = logging.getLogger("openterm.kite")

SEGMENT_DIVISOR = {"cds": 1e7, "bcd": 1e4}
TOKEN_SEGMENTS = {3: "cds", 6: "bcd"}  # instrument_token & 0xff
MAX_TOKENS = 3000  # Kite's limit per connection
TAPE_MAX = 5000  # prints kept per symbol in memory
PIN_TTL_S = 90.0  # a panel's request keeps a symbol subscribed (and in full mode for depth) this long


def default_segment(token: int) -> str | None:
    return TOKEN_SEGMENTS.get(token & 0xFF)


def decode(data: bytes, segment_of: Callable[[int], str | None] | None = None) -> list[dict]:
    """Decodes one binary message into tick dicts. Keys: token, ltp, and per length last_qty, avg, volume, buy_qty, sell_qty, open, high,
    low, close, change, ts_last_trade, oi, oi_day_high, oi_day_low, ts_exchange, depth_buy / depth_sell as 5 (qty, price, orders)."""
    if len(data) < 4:
        return []  # a heartbeat (1 byte) or noise
    seg_of = segment_of or default_segment
    try:
        (count,) = struct.unpack_from(">H", data, 0)
    except struct.error:
        return []
    out: list[dict] = []
    pos = 2
    for _ in range(count):
        if pos + 2 > len(data):
            return []
        (length,) = struct.unpack_from(">H", data, pos)
        pos += 2
        if pos + length > len(data):
            return []  # damaged: the message claims more bytes than it has
        packet = data[pos : pos + length]
        pos += length
        tick = _packet(packet, seg_of)
        if tick is not None:
            out.append(tick)
    return out


def _packet(p: bytes, seg_of: Callable[[int], str | None]) -> dict | None:
    n = len(p)
    if n not in (8, 28, 32, 44, 184):
        return None
    token = struct.unpack_from(">i", p, 0)[0]
    div = SEGMENT_DIVISOR.get(seg_of(token) or "", 100.0)
    f = lambda off: struct.unpack_from(">i", p, off)[0]
    price = lambda off: f(off) / div
    out: dict = {"token": token, "ltp": price(4)}
    if n == 8:
        return out
    if n in (28, 32):  # index: no quantities, no depth
        out |= {"high": price(8), "low": price(12), "open": price(16), "close": price(20), "change": price(24)}
        if n == 32:
            out["ts_exchange"] = f(28)
        return out
    out |= {"last_qty": f(8), "avg": price(12), "volume": f(16), "buy_qty": f(20), "sell_qty": f(24), "open": price(28),
            "high": price(32), "low": price(36), "close": price(40)}
    if n == 184:
        out |= {"ts_last_trade": f(44), "oi": f(48), "oi_day_high": f(52), "oi_day_low": f(56), "ts_exchange": f(60)}
        for name, base in (("depth_buy", 64), ("depth_sell", 124)):
            out[name] = [(f(base + 12 * i), f(base + 12 * i + 4) / div, struct.unpack_from(">h", p, base + 12 * i + 8)[0]) for i in range(5)]
    return out


class KiteTicker:
    """The ticker connection. Mirrors `streaming/iex.py`: the hub calls `set_symbols`, `covers` says whether Yahoo's ticks for a symbol
    should be dropped, `status` shows on SOURCES."""

    def __init__(self, emit: Callable[[Tick], None], session, instruments, prev_close: Callable[[str], float | None]):
        self.emit = emit
        self.session = session  # kite.session.KiteSession
        self.instruments = instruments  # kite.instruments.Instruments
        self.prev_close = prev_close
        self.symbols: set[str] = set()
        self.status = "OFF"
        self.ticks = 0
        self._wanted = {}  # token -> Yahoo-style symbol (the setter below also refreshes the set `covers` reads on every tick)
        self._ws = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._segments: dict[int, str | None] = {}
        self._sleep = asyncio.sleep  # the backoff wait; a test swaps it for a recording stand-in
        # --- depth, tape and recording hooks (read-only) ---
        self.tape: dict[str, deque[tuple[int, int, float, int]]] = {}  # symbol -> (seq, ms, price, qty gained), oldest first
        self.books: dict[str, dict] = {}  # symbol -> newest depth {t, buy, sell} (5 levels of (qty, price, orders))
        self.listeners: list[Callable[[str, str, dict], None]] = []  # (symbol, "t" | "d", data): the recorder's hook
        self._vol: dict[str, int] = {}  # symbol -> the day's cumulative volume at the previous packet
        self._seq = 0
        self._pins: dict[str, tuple[float, bool]] = {}  # symbol -> (expires at, wants depth)
        self._held: dict[str, int] = {}  # symbol -> holds (recordings); always subscribed in full mode
        self._full: set[int] = set()  # tokens in full mode on the live socket

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def set_symbols(self, symbols: set[str]) -> None:
        self.symbols = {s for s in symbols if to_kite(s) is not None}
        self._wake.set()

    def pin(self, symbol: str, depth: bool = False) -> None:
        """A panel asked for `symbol`'s tape or book: subscribe it (even when no chart shows it) for PIN_TTL_S more seconds, in `full`
        mode when `depth`. Calling again renews the time. Raises ValueError for a symbol Kite does not serve."""
        sym = symbol.strip().upper()
        if to_kite(sym) is None:
            raise ValueError(f"KITE DOES NOT SERVE {sym}")
        old = self._pins.get(sym)
        now = time.monotonic()
        self._pins[sym] = (now + PIN_TTL_S, depth or bool(old and old[1] and old[0] > now))
        self._wake.set()

    def hold(self, symbol: str) -> None:
        """A recording needs `symbol` (with its book) until `release`."""
        sym = symbol.strip().upper()
        if to_kite(sym) is None:
            raise ValueError(f"KITE DOES NOT SERVE {sym}")
        self._held[sym] = self._held.get(sym, 0) + 1
        self._wake.set()

    def release(self, symbol: str) -> None:
        sym = symbol.strip().upper()
        n = self._held.get(sym, 0) - 1
        if n > 0:
            self._held[sym] = n
        else:
            self._held.pop(sym, None)
        self._wake.set()

    def _pinned(self) -> dict[str, bool]:
        """symbol -> wants depth, for every live pin and hold (expired pins are dropped here)."""
        now = time.monotonic()
        for s in [s for s, (exp, _) in self._pins.items() if exp <= now]:
            del self._pins[s]
        out = {s: d for s, (_, d) in self._pins.items()}
        out.update({s: True for s in self._held})
        return out

    def _all_symbols(self) -> set[str]:
        """The symbols the hub wants plus those panels and recordings pinned."""
        return {s for s in self.symbols | set(self._pinned()) if to_kite(s) is not None}

    def _full_tokens(self) -> set[int]:
        depth = {s for s, want in self._pinned().items() if want}
        return {tok for tok, sym in self._wanted.items() if sym in depth}

    def covers(self, symbol: str) -> bool:
        """True while the Kite socket is up and `symbol` is subscribed on it (Yahoo's delayed ticks are dropped meanwhile).

        Not "a tick arrived in the last few seconds": an illiquid option can stay silent for minutes, and a Yahoo tick (15 minutes late)
        sneaking in then would drag the price back in time. The moment the socket drops (`status` leaves OK) or the login ends, Yahoo and the
        poller serve the symbol again, and their ticks carry the labels STREAM / POLL instead of RT KITE."""
        return self.status == "OK" and symbol in self._subscribed and self.session.logged_in

    @property
    def _wanted(self) -> dict[int, str]:
        return self._by_token

    @_wanted.setter
    def _wanted(self, tokens: dict[int, str]) -> None:
        self._by_token = tokens
        self._subscribed = frozenset(tokens.values())

    async def _tokens(self) -> dict[int, str]:
        dump = await self.instruments.get()
        out: dict[int, str] = {}
        for s in sorted(self._all_symbols())[:MAX_TOKENS]:
            row = dump.find(to_kite(s) or "")
            if row is not None:
                out[row["instrument_token"]] = s
                self._segments[row["instrument_token"]] = {"CDS": "cds", "BCD": "bcd"}.get(row["exchange"])
        return out

    async def _run(self) -> None:
        import orjson
        import websockets

        backoff = 1.0
        while True:
            if not self._all_symbols() or not self.session.logged_in:
                self.status = "OFF" if not self.session.has_key else ("IDLE" if self.session.logged_in else self.session.state)
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), 30.0)
                continue
            try:
                key, token = self.session.auth()
                self._wanted = await self._tokens()
                if not self._wanted:
                    self.status = "IDLE"
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                self.status = "CONNECTING"
                async with websockets.connect(f"{KITE_WS}?api_key={key}&access_token={token}", open_timeout=8, ping_interval=20,
                                              max_queue=4096) as ws:
                    self._ws = ws
                    subscribed = set(self._wanted)
                    full = self._full = self._full_tokens()
                    await ws.send(orjson.dumps({"a": "subscribe", "v": sorted(subscribed)}).decode())
                    await self._send_modes(ws, subscribed & full, subscribed - full)
                    self.status = "OK"
                    backoff = 1.0
                    log.info("kite ticker connected (%d instruments)", len(subscribed))
                    reader = asyncio.create_task(self._read(ws))
                    # a dropped socket must wake the loop below at once: otherwise `status` stays OK (and `covers` true, Yahoo's ticks
                    # dropped) for up to the 5 s poll while nothing arrives
                    reader.add_done_callback(lambda _t: self._wake.set())
                    try:
                        while not reader.done():
                            self._wake.clear()
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(self._wake.wait(), 5.0)
                            if reader.done() or not self._all_symbols() or not self.session.logged_in:
                                break
                            self._wanted = await self._tokens()
                            add, drop = set(self._wanted) - subscribed, subscribed - set(self._wanted)
                            if add:
                                await ws.send(orjson.dumps({"a": "subscribe", "v": sorted(add)}).decode())
                            if drop:
                                await ws.send(orjson.dumps({"a": "unsubscribe", "v": sorted(drop)}).decode())
                            subscribed = set(self._wanted)
                            # modes: a new token gets its mode; a token whose depth need changed switches (full <-> quote)
                            full_now = self._full_tokens()
                            await self._send_modes(ws, (full_now - full) | (full_now & add), ((full - full_now) & subscribed) | (add - full_now))
                            full = self._full = full_now
                    finally:
                        reader.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await reader
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - any failure: mark down, back off, reconnect while logged in
                log.warning("kite ticker down: %s", type(e).__name__)
            finally:
                self._ws = None
            self.status = "DOWN"
            await self._sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    @staticmethod
    async def _send_modes(ws, full: set[int], quote: set[int]) -> None:
        import orjson

        if full:
            await ws.send(orjson.dumps({"a": "mode", "v": ["full", sorted(full)]}).decode())
        if quote:
            await ws.send(orjson.dumps({"a": "mode", "v": ["quote", sorted(quote)]}).decode())

    async def _read(self, ws) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                self.on_message(raw)

    def on_message(self, raw: bytes) -> None:
        for d in decode(raw, lambda t: self._segments.get(t) or default_segment(t)):
            sym = self._wanted.get(d["token"])
            if sym is None or d.get("ltp") is None:
                continue
            price = d["ltp"]
            self._observe(sym, d)
            if sym not in self.symbols and sym in self._pinned():
                continue  # pinned only for a panel's tape / book: no chart asked for this symbol, so the hub does not need its ticks
            close = d.get("close") or self.prev_close(sym)
            change = price - close if close else None
            self.ticks += 1
            self.emit(Tick(symbol=sym, price=price, change=change, change_pct=change / close * 100 if change is not None and close else None,
                           volume=d.get("volume"), high=d.get("high"), low=d.get("low"),
                           time_ms=int((d.get("ts_exchange") or time.time()) * 1000), source="k"))

    def _observe(self, sym: str, d: dict) -> None:
        """Feeds the tape and the book from one decoded packet (see the module note). Cheap: it runs on every packet."""
        t_ms = int((d.get("ts_exchange") or time.time()) * 1000)
        vol = d.get("volume")
        if vol is not None:
            prev = self._vol.get(sym)
            self._vol[sym] = vol
            # The first packet (or a volume that went DOWN: a new day) is not a trade, only a starting point: it is kept as a REFERENCE print of
            # quantity 0 so the tick rule can compare the next price with it; the panels never draw a quantity-0 row.
            if prev is None or vol < prev or vol > prev:
                self._seq += 1
                row = (self._seq, t_ms, d["ltp"], vol - prev if prev is not None and vol > prev else 0)
                self.tape.setdefault(sym, deque(maxlen=TAPE_MAX)).append(row)
                for cb in self.listeners:
                    cb(sym, "t", {"seq": row[0], "t": t_ms, "p": row[2], "q": row[3]})
        if "depth_buy" in d:
            book = {"t": t_ms, "buy": d["depth_buy"], "sell": d["depth_sell"]}
            self.books[sym] = book
            for cb in self.listeners:
                cb(sym, "d", book)
