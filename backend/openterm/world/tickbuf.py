"""Per-symbol tick ring buffers behind GIP (the intraday tick chart): what this server has seen since the session began.

Only ticks the hub actually emitted are kept (a symbol nobody subscribed to has no buffer, and GIP says so: nothing is invented). A buffer
holds the newest `CAP` ticks as three typed arrays (about 24 bytes a tick), for at most `MAX_SYMBOLS` symbols (the one whose last tick is
oldest is dropped first). A gap of more than four hours between ticks starts a new session and clears the buffer.
"""

import math
from array import array
from itertools import islice
from operator import le

from ..streaming.tick import Tick

CAP = 20_000
MAX_SYMBOLS = 100
SESSION_GAP_MS = 4 * 3600 * 1000
BARS = {"1s": 1, "5s": 5, "15s": 15, "1m": 60}
SOURCE_LABEL = {"y": "YAHOO STREAM", "p": "YAHOO POLL", "s": "SYNTHETIC", "a": "RT IEX", "k": "RT KITE"}


class TickRing:
    __slots__ = ("cap", "last_ms", "p", "sessions", "since_ms", "src", "start", "t", "total", "v")

    def __init__(self, cap: int = CAP):
        self.cap = cap
        self.t = array("q")  # epoch ms
        self.p = array("d")
        self.v = array("d")  # cumulative day volume, NaN when the tick carried none
        self.start = 0
        self.src = ""
        self.total = 0
        self.sessions = 0
        self.since_ms: int | None = None
        self.last_ms: int | None = None

    def __len__(self) -> int:
        return len(self.t) - self.start

    def _clear(self) -> None:
        del self.t[:], self.p[:], self.v[:]
        self.start = 0

    def add(self, ms: int, price: float, vol: float | None, src: str) -> None:
        if self.last_ms is None or ms - self.last_ms > SESSION_GAP_MS:
            if self.last_ms is not None:
                self._clear()
            self.sessions += 1
            self.since_ms = ms
        self.last_ms = ms if self.last_ms is None or ms > self.last_ms else self.last_ms
        self.t.append(ms)
        self.p.append(price)
        self.v.append(math.nan if vol is None else float(vol))
        self.src = src
        self.total += 1
        excess = len(self.t) - self.start - self.cap
        if excess > 0:
            self.start += excess
            if self.start > self.cap:  # compact once the dead prefix is as long as the live part
                del self.t[: self.start], self.p[: self.start], self.v[: self.start]
                self.start = 0

    def view(self) -> tuple[list[int], list[float], list[float]]:
        s = self.start
        return self.t[s:].tolist(), self.p[s:].tolist(), self.v[s:].tolist()


class TickBuffers:
    def __init__(self, cap: int = CAP, max_symbols: int = MAX_SYMBOLS):
        self.cap = cap
        self.max_symbols = max_symbols
        self.rings: dict[str, TickRing] = {}

    def add(self, tick: Tick) -> None:
        price = tick.price
        if not (0 < price < 1e15):  # also false for NaN
            return
        ring = self.rings.get(tick.symbol)
        if ring is None:
            if len(self.rings) >= self.max_symbols:
                quiet = min(self.rings, key=lambda s: self.rings[s].last_ms or 0)
                del self.rings[quiet]
            ring = self.rings[tick.symbol] = TickRing(self.cap)
        ring.add(tick.time_ms, price, tick.volume, tick.source)

    def get(self, symbol: str) -> TickRing | None:
        return self.rings.get(symbol)

    def symbols(self) -> list[str]:
        return list(self.rings)


def bucket(t_ms: list[int], price: list[float], cum_vol: list[float], bar_s: int) -> dict:
    """Time buckets of `bar_s` seconds with open / high / low / close by tick TIME (equal times keep arrival order).

    Volume per bucket is the increase of the cumulative day volume across its ticks (a tick without volume keeps the last known total;
    a fall means a new day and counts as zero). `v` is None when no tick carried volume. Buckets with no ticks are not created.

    One pass with scalar running values (a 20,000-tick ring took 25 ms with per-tick list indexing, 7 ms now: see docs/review/backend-api.md).
    """
    n = len(t_ms)
    if all(map(le, t_ms, islice(t_ms, 1, None))):
        ts, ps, vs = t_ms, price, cum_vol
    else:
        order = sorted(range(n), key=t_ms.__getitem__)
        ts, ps, vs = [t_ms[i] for i in order], [price[i] for i in order], [cum_vol[i] for i in order]
    span = bar_s * 1000
    ot: list[int] = []
    oo: list[float] = []
    oh: list[float] = []
    ol: list[float] = []
    oc: list[float] = []
    ov: list[float] = []
    have_vol = False
    base: float | None = None
    cur: int | None = None
    o = h = low = c = vsum = 0.0
    for t, px, vi in zip(ts, ps, vs, strict=True):
        b = t // span * bar_s
        delta = 0.0
        if vi == vi:  # noqa: PLR0124 - not NaN; math.isnan costs a call per tick
            have_vol = True
            if base is not None and vi >= base:
                delta = vi - base
            base = vi
        if b != cur:
            if cur is not None:
                ot.append(cur)
                oo.append(o)
                oh.append(h)
                ol.append(low)
                oc.append(c)
                ov.append(vsum)
            cur = b
            o = h = low = c = px
            vsum = delta
        else:
            if px > h:  # noqa: PLR1730 - builtin max/min cost a call per tick here
                h = px
            if px < low:  # noqa: PLR1730
                low = px
            c = px
            vsum += delta
    if cur is not None:
        ot.append(cur)
        oo.append(o)
        oh.append(h)
        ol.append(low)
        oc.append(c)
        ov.append(vsum)
    return {"t": ot, "o": oo, "h": oh, "l": ol, "c": oc, "v": ov if have_vol else None}
