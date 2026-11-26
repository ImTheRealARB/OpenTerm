"""Helpers shared by the Phase 15 job bodies. numpy is allowed here (job workers only)."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import msgpack
import numpy as np

from ..research.table import head, payload

YEAR_DAYS = 365.2425
_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()  # day number 0


def load(params: dict) -> dict:
    """The content-addressed data file the server wrote (checked against its hash; the job never touches the network)."""
    blob = Path(params["data_path"]).read_bytes()
    if hashlib.sha256(blob).hexdigest() != params["data_sha"]:
        raise RuntimeError("DATA FILE DOES NOT MATCH ITS HASH")
    return msgpack.unpackb(blob, raw=False)


def fin(x: Any) -> float | None:
    """A finite float, else None (JSON has no NaN)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parametric_var(returns: Any, confidence: float, horizon: int) -> float:
    """Normal VaR over `horizon` periods, with the mean grown by the horizon and only the spread by its square root:
    -(mu * h + z * sigma * sqrt(h)). The ported `quantlib.risk.parametric_var` scales the WHOLE sum by sqrt(h) (Vibe's
    documented convention, pinned by the cross-check tests), which misreads the drift of a 60-day VaR by mu * (60 - sqrt(60))
    (audit H-25). The panels use this one; the ported function stays as Vibe has it."""
    from ..quantlib import risk as qr

    one_period = qr.parametric_var(returns, confidence, 1)  # validates the inputs and the confidence like the ported one
    r = np.asarray(returns, dtype=float)
    mu = float(r[np.isfinite(r)].mean())
    # one_period = -(mu + z sigma): the spread term is -(one_period + mu) = z * sigma (negative for a loss tail)
    spread = -(one_period + mu)
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    return float(-(mu * horizon + spread * math.sqrt(horizon)))


def series(bars: dict | None) -> tuple[np.ndarray, np.ndarray]:
    """(day numbers, closes) ascending, one close per day (the last), without missing closes.

    A day is the EXCHANGE's calendar date when the bars name their time zone (`tz`, Yahoo's exchangeTimezoneName), else the
    UTC date. ASX and NZX daily bars are stamped at the local open, which is 23:00 UTC the day before in summer: bucketing
    them by UTC date paired every ASX return with the previous US day (audit H-25)."""
    if not bars or not bars.get("t"):
        return np.array([], dtype=np.int64), np.array([], dtype=float)
    stamps = np.asarray(bars["t"], dtype=np.int64)
    if bars.get("tz"):
        zone = ZoneInfo(bars["tz"])  # an unknown zone name raises: better a failed job than a silently shifted calendar
        t = np.array([datetime.fromtimestamp(int(x), zone).toordinal() - _EPOCH_ORDINAL for x in stamps], dtype=np.int64)
    else:
        t = stamps // 86400
    c = np.array([np.nan if v is None else v for v in bars["c"]], dtype=float)
    ok = np.isfinite(c) & (c > 0)
    t, c = t[ok], c[ok]
    if t.size == 0:
        return t, c
    order = np.argsort(t, kind="stable")
    t, c = t[order], c[order]
    last = np.append(t[1:] != t[:-1], True)  # keep the last bar of a day
    return t[last], c[last]


def align(cols: dict[str, tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """Inner join on day: (days, closes[days x symbols] in the dict's order)."""
    keys = list(cols)
    days = cols[keys[0]][0]
    for k in keys[1:]:
        days = np.intersect1d(days, cols[k][0], assume_unique=True)
    mat = np.column_stack([cols[k][1][np.searchsorted(cols[k][0], days)] for k in keys]) if days.size else np.empty((0, len(keys)))
    return days, mat


def asof(days: np.ndarray, close: np.ndarray, day: int) -> float | None:
    """Close of the last bar on or before `day` (None before the first bar)."""
    i = int(np.searchsorted(days, day, side="right")) - 1
    return float(close[i]) if i >= 0 else None


def year(day: np.ndarray | int) -> np.ndarray | float:
    """Day number as a decimal year (1970 + days / 365.2425), the numeric x axis of a chart."""
    return 1970.0 + np.asarray(day, dtype=float) / YEAR_DAYS


def iso(day: int) -> str:
    from datetime import date, timedelta

    return (date(1970, 1, 1) + timedelta(days=int(day))).isoformat()


def day_of(iso_date: str) -> int:
    from datetime import date

    return (date.fromisoformat(iso_date) - date(1970, 1, 1)).days


def envelope(data: dict, labels: dict) -> dict:
    """The standard job result: {data, source, stale, age_s, fallback_from} built from the server's per-symbol source labels."""
    src = labels.get("sources") or []
    names = sorted({str(s.get("name")) for s in src if s.get("name")})
    ages = [s["age_s"] for s in src if isinstance(s.get("age_s"), int | float)]
    return {"data": data, "source": ", ".join(names) or None, "stale": any(s.get("stale") for s in src),
            "age_s": max(ages) if ages else None, "fallback_from": list(labels.get("fallback_from") or [])}


def data_notes(labels: dict) -> list[str]:
    """Notes every payload carries: where the bars came from and whether they are test data."""
    src = labels.get("sources") or []
    notes = []
    if any(str(s.get("name")) == "synthetic" for s in src):
        notes.append("SYNTHETIC DATA, NOT A MARKET")
    if labels.get("fixtures"):
        notes.append("RECORDED FIXTURE DATA, NOT LIVE")
    if any(s.get("stale") for s in src):
        notes.append("STALE: SOME BARS ARE OLDER THAN THEIR CACHE LIFETIME")
    if src:
        names = sorted({str(s.get("name")) for s in src if s.get("name")})
        age = max((s["age_s"] for s in src if isinstance(s.get("age_s"), int | float)), default=None)
        notes.append(f"BARS FROM {', '.join(n.upper() for n in names)}" + (f", AGE {age:.0f}s" if age is not None else ""))
    return notes


def not_runnable(title: str, message: str, labels: dict | None = None) -> dict:
    """A normal answer that says why nothing ran (status starts with NOT RUNNABLE)."""
    msg = message if message.startswith("NOT RUNNABLE") else f"NOT RUNNABLE: {message}"
    labels = labels or {}
    return envelope(payload(None, title, [head("STATUS", msg)], [], [msg, *data_notes(labels)], status=msg), labels)


def eq_vol(port: np.ndarray) -> float:
    return float(port.std(ddof=1) * math.sqrt(252))


def cum(port: np.ndarray) -> np.ndarray:
    return np.cumprod(1.0 + port)


def drawdown(eq: np.ndarray) -> np.ndarray:
    return eq / np.maximum.accumulate(eq) - 1.0
