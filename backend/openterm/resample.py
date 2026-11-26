"""Candle resampler: builds the longer candle lengths (2h .. 12h, 2d, 3d, 2wk, quarterly, yearly) from a smaller candle a source has.

Why here and not at the sources: no source (Yahoo, Kite, Binance ...) sells a 4 hour or a quarterly candle, but every one of them
sells the candle it is built from (60 minute, daily, weekly, monthly). So `DataService.history` asks the normal path for the base
candle (cache, source hierarchy, fallbacks all unchanged), then calls `resample()` here.

PURE PYTHON on purpose: the server process must never import pandas or numpy (a test enforces it), and a plain loop over a few
thousand bars is fast enough.

The rule for every bucket (one output candle = a run of consecutive base candles):
  t   = the first base candle's time      o = the first open       h = the highest high      l = the lowest low
  c   = the last close                    v = the sum of volumes   (a missing value, None, is skipped; all missing stays None)
Optional per-candle columns:
  adj  (adjusted close)      the LAST one in the bucket, same as the close
  oi   (open interest)       the LAST one in the bucket (it is a level at the end of the candle, not a flow)
  fund (funding rate)        the MEAN of the base candles' values (each is already a mean of that candle's settlements, and
                             Binance settles on a fixed cadence, so the mean of the means is the mean of the settlements)
Everything else on `Bars` (symbol, currency, exchange, tz, source, as_of, range) is carried over unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Bars

# target interval -> (base interval it is built from, rule)
#   ("hours", n)   n-hour buckets inside ONE local trading day, anchored at that day's first candle
#   ("bars", n)    every n consecutive base candles, counted from the start of the series
#   ("months", n)  calendar buckets of n months: n = 3 gives the quarters Jan/Apr/Jul/Oct, n = 12 gives calendar years
RESAMPLED: dict[str, tuple[str, tuple[str, int]]] = {
    "2h": ("60m", ("hours", 2)), "3h": ("60m", ("hours", 3)), "4h": ("60m", ("hours", 4)),
    "6h": ("60m", ("hours", 6)), "8h": ("60m", ("hours", 8)), "12h": ("60m", ("hours", 12)),
    "2d": ("1d", ("bars", 2)), "3d": ("1d", ("bars", 3)),
    "2wk": ("1wk", ("bars", 2)),
    "3mo": ("1mo", ("months", 3)), "12mo": ("1mo", ("months", 12)),
}

# A source labels the candles it answers with. Yahoo says "1h" for the 60 minute size it was asked for as "60m", so both count.
_BASE_LABELS = {"60m": {"60m", "1h"}}


class ResampleError(ValueError):
    """The base candles cannot be turned into the asked length (wrong size came back, unknown time zone)."""


def _zone(tz: str | None) -> ZoneInfo:
    """The exchange time zone of the bars. Crypto sources say "UTC"; a source that names none is read as UTC too."""
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ResampleError(f"UNKNOWN TIME ZONE {tz} ON THE SOURCE'S BARS") from e


def _hour_starts(t: Sequence[int], tz: ZoneInfo, hours: int) -> list[int]:
    """Index of the first base candle of every bucket.

    Each LOCAL trading day (the date in the exchange's own time zone) is cut on its own, from its FIRST candle: a US day starts at
    09:30, an Indian day at 09:15, a crypto day at 00:00 UTC. Cutting from midnight UTC instead would split a New York session in two
    and a bucket must never run across a day change, so the next day always opens a fresh bucket. Candles are placed by the time
    elapsed since that day's first candle, so a gap (a halt, a missing candle) leaves a bucket empty instead of shifting the others.
    """
    span = hours * 3600
    starts: list[int] = []
    day = anchor = bucket = -1
    for i, ts in enumerate(t):
        d = datetime.fromtimestamp(ts, tz).toordinal()  # the local calendar day of this candle
        if d != day:
            day, anchor, bucket = d, ts, 0
            starts.append(i)
        else:
            b = (ts - anchor) // span
            if b != bucket:
                bucket = b
                starts.append(i)
    return starts


def _month_starts(t: Sequence[int], tz: ZoneInfo, months: int) -> list[int]:
    """Index of the first monthly candle of every calendar bucket of `months` months (quarters for 3, years for 12).

    The month of a candle is read in the exchange time zone: a monthly candle stamped midnight of the 1st in Tokyo is already
    the previous month in UTC. The first bucket holds only the months the series starts with: asking a quarterly chart for
    "1Y" can open on a half quarter, and that bucket honestly holds just the months we have."""
    starts: list[int] = []
    last = None
    for i, ts in enumerate(t):
        d = datetime.fromtimestamp(ts, tz)
        key = (d.year * 12 + d.month - 1) // months  # the same number for every month of one quarter (or year)
        if key != last:
            last = key
            starts.append(i)
    return starts


def _fold(col: Sequence | None, starts: list[int], n: int, pick: Callable[[list], float | None]) -> list | None:
    """Apply `pick` to the non-missing values of every bucket (`starts[k]` .. `starts[k+1]`). A column the source did not send stays None."""
    if col is None:
        return None
    ends = [*starts[1:], n]
    return [pick([x for x in col[s:e] if x is not None]) for s, e in zip(starts, ends, strict=True)]


def _head(xs: list) -> float | None:
    return xs[0] if xs else None


def _tail(xs: list) -> float | None:
    return xs[-1] if xs else None


def _max(xs: list) -> float | None:
    return max(xs) if xs else None


def _min(xs: list) -> float | None:
    return min(xs) if xs else None


def _sum(xs: list) -> float | None:
    return sum(xs) if xs else None


def _mean(xs: list) -> float | None:
    return sum(xs) / len(xs) if xs else None


def resample(bars: Bars, target: str) -> Bars:
    """`bars` (the base candle) -> the same data as `target` candles. Raises `ResampleError` if the bars are not the base size."""
    base, (kind, n) = RESAMPLED[target]
    if bars.interval not in _BASE_LABELS.get(base, {base}):
        # A source may answer a coarser size than asked (Yahoo gives monthly bars for range=max with 1d; the synthetic source always
        # sends daily). Folding those would draw a wrong chart under the right label, so say so instead.
        raise ResampleError(f"SOURCE ANSWERED {bars.interval} BARS, NOT THE {base} BARS NEEDED FOR {target}")
    count = len(bars.t)
    if count == 0:
        starts: list[int] = []
    elif kind == "hours":
        starts = _hour_starts(bars.t, _zone(bars.tz), n)
    elif kind == "months":
        starts = _month_starts(bars.t, _zone(bars.tz), n)
    else:  # "bars": consecutive chunks of n, counted from the first candle (the last chunk may hold fewer)
        starts = list(range(0, count, n))
    return Bars.model_construct(
        symbol=bars.symbol, range=bars.range, interval=target, currency=bars.currency, exchange=bars.exchange, tz=bars.tz,
        t=[bars.t[s] for s in starts],
        o=_fold(bars.o, starts, count, _head), h=_fold(bars.h, starts, count, _max),
        l=_fold(bars.l, starts, count, _min), c=_fold(bars.c, starts, count, _tail),
        v=_fold(bars.v, starts, count, _sum),
        source=bars.source, as_of=bars.as_of,
        adj=_fold(bars.adj, starts, count, _tail), fund=_fold(bars.fund, starts, count, _mean), oi=_fold(bars.oi, starts, count, _tail),
    )
