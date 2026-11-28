"""Turn the chart's bars into longer bars (spec 1.5, `request` on the same symbol with a longer timeframe).

Rules, all in UTC:
  * intraday buckets and 1D are aligned to epoch seconds (a 4h bucket starts at 00:00, 04:00, ...);
  * 1W weeks start on Monday 00:00;
  * 1M is the calendar month.
A bucket's open is its first bar's open, high / low the extremes, close the last bar's close, volume the sum, and `t` the
bucket's start time.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .names import TIMEFRAMES

SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1D": 86400, "1W": 604800}
MONTH_NOMINAL = 30 * 86400  # only used to order timeframes ("longer than"), never to bucket


def normalize(tf: str | None) -> str | None:
    """"60" -> "1h", "D" -> "1D". "" and None stay empty; an unknown spelling gives None."""
    if not tf:
        return ""
    return TIMEFRAMES.get(tf)


def seconds(tf: str) -> int:
    """Nominal length of a normal-form timeframe (a month counts as 30 days)."""
    return MONTH_NOMINAL if tf == "1M" else SECONDS[tf]


def _month_start(t: float, add: int = 0) -> float:
    d = datetime.fromtimestamp(t, tz=UTC)
    month = d.month - 1 + add
    return datetime(d.year + month // 12, month % 12 + 1, 1, tzinfo=UTC).timestamp()


def bucket_start(t: float, tf: str) -> float:
    """Start time of the bucket that holds time `t`."""
    if tf == "1M":
        return _month_start(t)
    if tf == "1W":
        day = int(t // 86400)
        return float((day - (day + 3) % 7) * 86400)  # 1970-01-01 was a Thursday, so Monday = (day + 3) % 7 == 0
    s = SECONDS[tf]
    return float(int(t // s) * s)


def bar_end(t: float, tf: str) -> float:
    """When a bar of timeframe `tf` that starts at `t` closes."""
    if tf == "1M":
        return _month_start(t, 1)
    return t + SECONDS[tf]


def resample(cols: dict, tf: str) -> dict:
    """Group the bars in `cols` (keys o h l c v t, oldest first) into buckets of timeframe `tf`."""
    out = {k: [] for k in "ohlcvt"}
    t = cols["t"]
    cur = None
    for i in range(len(t)):
        b = bucket_start(t[i], tf)
        if b != cur:
            cur = b
            out["t"].append(b)
            out["o"].append(cols["o"][i])
            out["h"].append(cols["h"][i])
            out["l"].append(cols["l"][i])
            out["c"].append(cols["c"][i])
            out["v"].append(cols["v"][i])
        else:
            out["h"][-1] = max(out["h"][-1], cols["h"][i])
            out["l"][-1] = min(out["l"][-1], cols["l"][i])
            out["c"][-1] = cols["c"][i]
            out["v"][-1] += cols["v"][i]
    return out
