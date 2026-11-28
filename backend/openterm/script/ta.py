"""The `ta.*` functions, computed one bar at a time (spec 1.6).

Each call SITE in a script gets its own small state object from `TA_FACTORIES`. `step(...)` is called with the values of the
arguments on the current bar and returns the result for that bar. The state only advances when the call actually runs, so a
`ta.sma` inside an `if` sees only the values from bars where the `if` was true (spec 1.5).

Rules shared by all of them:
  * "window" functions look at the LAST n values this call site has seen; fewer than n values, or any na in the window, gives na;
  * `n` must be a whole number from 1 to 5,000 (else a runtime error) and may change from bar to bar;
  * na never crashes: it just flows through.
"""

# `x != x` is the standard test for NaN (na) in Python and JavaScript; ruff's PLR0124 would reject it.
# ruff: noqa: PLR0124

from __future__ import annotations

import math

from .builtins import NA, fail, num, truthy
from .names import LIMITS

LOOKBACK = LIMITS["lookback"]


def length(n) -> int:
    """Check a window length: a whole number from 1 to 5,000."""
    n = num(n)
    if not (n >= 1.0) or n != math.floor(n) or n > LOOKBACK:
        fail(f"LENGTH MUST BE A WHOLE NUMBER FROM 1 TO {LOOKBACK}")
    return int(n)


def _push(buf: list, x) -> None:
    """Append, and now and then cut the list back to what a window can still need (the last 5,001 values)."""
    buf.append(x)
    if len(buf) > 2 * LOOKBACK + 2:
        del buf[: -(LOOKBACK + 1)]


# ------------------------------------------------------------------------------------------------ window functions


class WindowOp:
    """Base for functions of the last n values. Subclasses define `calc(window, n, window_sum)`."""

    __slots__ = ("b",)

    def __init__(self) -> None:
        self.b: list[float] = []

    def calc(self, w: list[float], n: int, s: float) -> float:
        raise NotImplementedError

    def step(self, x, n) -> float:
        x = num(x)
        n = length(n)
        b = self.b
        _push(b, x)
        if len(b) < n:
            return NA
        w = b[-n:]
        s = sum(w)
        if s != s:  # an na in the window makes the sum NaN
            return NA
        return self.calc(w, n, s)


class Sma(WindowOp):
    __slots__ = ()

    def calc(self, w, n, s):
        return s / n


class Variance(WindowOp):
    """Population variance: the mean of squared deviations from the window mean."""

    __slots__ = ()

    def calc(self, w, n, s):
        m = s / n
        return sum((x - m) * (x - m) for x in w) / n


class Stdev(Variance):
    __slots__ = ()

    def calc(self, w, n, s):
        return math.sqrt(Variance.calc(self, w, n, s))


class Wma(WindowOp):
    """Weights 1..n, the newest value weighs n."""

    __slots__ = ()

    def calc(self, w, n, s):
        return sum(x * (i + 1) for i, x in enumerate(w)) / (n * (n + 1) / 2)


class Highest(WindowOp):
    __slots__ = ()

    def calc(self, w, n, s):
        return max(w)


class Lowest(WindowOp):
    __slots__ = ()

    def calc(self, w, n, s):
        return min(w)


class Linreg:
    """Least-squares line over the window (x = 0..n-1, oldest = 0), read at x = n-1-offset."""

    __slots__ = ("b",)

    def __init__(self) -> None:
        self.b: list[float] = []

    def step(self, x, n, offset=0.0) -> float:
        x = num(x)
        n = length(n)
        off = num(offset)
        _push(self.b, x)
        if len(self.b) < n:
            return NA
        w = self.b[-n:]
        sy = sum(w)
        if sy != sy or off != off:
            return NA
        sx = n * (n - 1) / 2
        sxx = (n - 1) * n * (2 * n - 1) / 6
        sxy = sum(i * y for i, y in enumerate(w))
        denom = n * sxx - sx * sx
        slope = 0.0 if denom == 0 else (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        return intercept + slope * (n - 1 - off)


class Vwma:
    """sma(src * volume) / sma(volume) over the same window."""

    __slots__ = ("ds", "pv", "v")

    def __init__(self, ds) -> None:
        self.pv: list[float] = []
        self.v: list[float] = []
        self.ds = ds

    def step(self, x, n) -> float:
        x = num(x)
        n = length(n)
        vol = self.ds.v[self.ds.i]
        _push(self.pv, x * vol)
        _push(self.v, vol)
        if len(self.v) < n:
            return NA
        sp = sum(self.pv[-n:])
        sv = sum(self.v[-n:])
        if sp != sp or sv != sv or sv == 0:
            return NA
        return sp / sv


# ------------------------------------------------------------------------------------------------ smoothing


class Ema:
    """EMA (alpha = 2/(n+1)) or RMA (alpha = 1/n). Seeded with the mean of the first n values that are not na."""

    __slots__ = ("prev", "rma", "seed")

    def __init__(self, rma: bool = False) -> None:
        self.rma = rma
        self.prev: float | None = None
        self.seed: list[float] | None = []

    def step(self, x, n) -> float:
        x = num(x)
        n = length(n)
        if x != x:
            return NA  # an na input gives na and leaves the state alone
        if self.prev is None:
            assert self.seed is not None
            self.seed.append(x)
            if len(self.seed) < n:
                return NA
            self.prev = sum(self.seed[:n]) / n
            self.seed = None
            return self.prev
        alpha = 1.0 / n if self.rma else 2.0 / (n + 1)
        self.prev = self.prev + alpha * (x - self.prev)
        return self.prev


class Rsi:
    """Relative strength: up and down moves smoothed with an RMA, the first change is on bar 1."""

    __slots__ = ("down", "prev", "up")

    def __init__(self) -> None:
        self.prev: float | None = None
        self.up = Ema(True)
        self.down = Ema(True)

    def step(self, x, n) -> float:
        x = num(x)
        p = self.prev
        self.prev = x
        d = NA if (p is None or p != p or x != x) else x - p
        up = self.up.step(d if d != d else (d if d > 0 else 0.0), n)
        down = self.down.step(d if d != d else (-d if d < 0 else 0.0), n)
        if up != up or down != down:
            return NA
        if down == 0:
            return 100.0
        if up == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + up / down)


class Tr:
    """True range of the chart bar (bar 0 is high - low)."""

    __slots__ = ("ds",)

    def __init__(self, ds) -> None:
        self.ds = ds

    def step(self) -> float:
        ds = self.ds
        i = ds.i
        hi, lo = ds.h[i], ds.l[i]
        if i == 0:
            return hi - lo
        pc = ds.c[i - 1]
        v = (hi - lo, abs(hi - pc), abs(lo - pc))
        if v[0] != v[0] or v[1] != v[1] or v[2] != v[2]:
            return NA
        return max(v)


class Atr:
    __slots__ = ("e", "tr")

    def __init__(self, ds) -> None:
        self.tr = Tr(ds)
        self.e = Ema(True)

    def step(self, n) -> float:
        return self.e.step(self.tr.step(), n)


class Macd:
    """macd = ema(src, fast) - ema(src, slow); signal = ema(macd, signal_len); hist = macd - signal."""

    __slots__ = ("fast", "sig", "slow")

    def __init__(self) -> None:
        self.fast = Ema()
        self.slow = Ema()
        self.sig = Ema()

    def step(self, x, f, s, g):
        a = self.fast.step(x, f)
        b = self.slow.step(x, s)
        m = a - b if (a == a and b == b) else NA
        sig = self.sig.step(m, g)
        hist = m - sig if (m == m and sig == sig) else NA
        return (m, sig, hist)


class Bb:
    """Bollinger bands: middle = sma, upper / lower = middle +- mult * stdev."""

    __slots__ = ("b",)

    def __init__(self) -> None:
        self.b: list[float] = []

    def step(self, x, n, mult):
        x = num(x)
        n = length(n)
        k = num(mult)
        _push(self.b, x)
        if len(self.b) < n:
            return (NA, NA, NA)
        w = self.b[-n:]
        s = sum(w)
        if s != s or k != k:
            return (NA, NA, NA)
        mid = s / n
        sd = math.sqrt(sum((v - mid) * (v - mid) for v in w) / n)
        return (mid, mid + k * sd, mid - k * sd)


class Stoch:
    """100 * (src - lowest(low, n)) / (highest(high, n) - lowest(low, n)); a range of 0 gives na."""

    __slots__ = ("hi", "lo")

    def __init__(self) -> None:
        self.hi: list[float] = []
        self.lo: list[float] = []

    def step(self, x, high, low, n) -> float:
        x = num(x)
        n = length(n)
        _push(self.hi, num(high))
        _push(self.lo, num(low))
        if len(self.hi) < n:
            return NA
        wh = self.hi[-n:]
        wl = self.lo[-n:]
        if sum(wh) != sum(wh) or sum(wl) != sum(wl) or x != x:
            return NA
        top, bottom = max(wh), min(wl)
        if top == bottom:
            return NA
        return 100.0 * (x - bottom) / (top - bottom)


# ------------------------------------------------------------------------------------------------ change and friends


class Change:
    """src - src[n] as seen by this call site (also `ta.mom`). `roc=True` gives the rate of change in percent."""

    __slots__ = ("b", "roc")

    def __init__(self, roc: bool = False) -> None:
        self.b: list[float] = []
        self.roc = roc

    def step(self, x, n=1.0) -> float:
        x = num(x)
        n = length(n)
        _push(self.b, x)
        if len(self.b) <= n:
            return NA
        p = self.b[-1 - n]
        if self.roc:
            return NA if p == 0 else 100.0 * (x - p) / p
        return x - p


class Cum:
    """Running sum; na inputs are skipped."""

    __slots__ = ("total",)

    def __init__(self) -> None:
        self.total = 0.0

    def step(self, x) -> float:
        x = num(x)
        if x == x:
            self.total += x
        return self.total


class Cross:
    """mode "over", "under" or "either". Needs the previous bar's values, so the first call is false."""

    __slots__ = ("mode", "prev")

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.prev: tuple[float, float] | None = None

    def step(self, a, b) -> bool:
        a, b = num(a), num(b)
        p = self.prev
        self.prev = (a, b)
        if p is None:
            return False
        pa, pb = p
        # With any na every comparison below is false, so na gives false.
        over = a > b and pa <= pb
        under = a < b and pa >= pb
        if self.mode == "over":
            return over
        if self.mode == "under":
            return under
        return over or under


class Rising:
    """True when src is above (rising) or below (falling) each of its previous n values."""

    __slots__ = ("b", "up")

    def __init__(self, up: bool) -> None:
        self.b: list[float] = []
        self.up = up

    def step(self, x, n) -> bool:
        x = num(x)
        n = length(n)
        _push(self.b, x)
        if len(self.b) < n + 1:
            return False
        prev = self.b[-(n + 1) : -1]
        if self.up:
            return all(x > p for p in prev)
        return all(x < p for p in prev)


class BarsSince:
    __slots__ = ("since",)

    def __init__(self) -> None:
        self.since: int | None = None

    def step(self, cond) -> float:
        if truthy(cond):
            self.since = 0
        elif self.since is not None:
            self.since += 1
        return NA if self.since is None else float(self.since)


class ValueWhen:
    __slots__ = ("hits",)

    def __init__(self) -> None:
        self.hits: list = []

    def step(self, cond, src, k=0.0):
        kk = num(k)
        if not (kk >= 0) or kk != math.floor(kk) or kk > LOOKBACK:
            fail("OCCURRENCE MUST BE A WHOLE NUMBER FROM 0")
        kk = int(kk)
        if truthy(cond):
            _push(self.hits, src)
        if len(self.hits) > kk:
            return self.hits[-1 - kk]
        return NA


# name -> function making the state object for one call site (`ds` is the bar data it may need)
TA_FACTORIES = {
    "ta.sma": lambda ds: Sma(),
    "ta.ema": lambda ds: Ema(False),
    "ta.wma": lambda ds: Wma(),
    "ta.rma": lambda ds: Ema(True),
    "ta.vwma": lambda ds: Vwma(ds),
    "ta.rsi": lambda ds: Rsi(),
    "ta.stdev": lambda ds: Stdev(),
    "ta.variance": lambda ds: Variance(),
    "ta.highest": lambda ds: Highest(),
    "ta.lowest": lambda ds: Lowest(),
    "ta.change": lambda ds: Change(False),
    "ta.mom": lambda ds: Change(False),
    "ta.roc": lambda ds: Change(True),
    "ta.cum": lambda ds: Cum(),
    "ta.tr": lambda ds: Tr(ds),
    "ta.atr": lambda ds: Atr(ds),
    "ta.crossover": lambda ds: Cross("over"),
    "ta.crossunder": lambda ds: Cross("under"),
    "ta.cross": lambda ds: Cross("either"),
    "ta.rising": lambda ds: Rising(True),
    "ta.falling": lambda ds: Rising(False),
    "ta.barssince": lambda ds: BarsSince(),
    "ta.valuewhen": lambda ds: ValueWhen(),
    "ta.linreg": lambda ds: Linreg(),
    "ta.macd": lambda ds: Macd(),
    "ta.bb": lambda ds: Bb(),
    "ta.stoch": lambda ds: Stoch(),
}
