"""IMPORT: bars from the user's own CSV (spec decision K). Pure Python, no pandas, so the server parses them.

Columns (any order, any case): date, open, high, low, close, volume (optional). Dates are `YYYY-MM-DD` (a time after
it is ignored: the data is daily). Rows are sorted by date; a duplicate date, a non-numeric or non-positive price, or a
high below the low rejects the whole file with the row number, never a silent fix. The browser parser
(`frontend/src/bt/csvImport.ts`) applies the same rules for the preview; this one is the authority.

INTRADAY (Phase 22): a file is intraday when some calendar date appears on more than one row AND the dates carry a time
(`2026-01-02T09:30:00-05:00`, or `2026-01-02 09:30` plus `tz="America/New_York"`). Every row then needs a time with its zone,
the bar spacing (1, 2, 5, 15, 30, 60 or 90 minutes) is read from the data, and a file that mixes spacings is refused. A file
whose dates are all different stays DAILY exactly as before (its times are ignored), so no existing daily import changes.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from functools import lru_cache
from itertools import pairwise

REQUIRED = ("date", "open", "high", "low", "close")
MAX_ROWS = 200_000
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T].*)?$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.^=_-]{0,15}$")
# A date followed by a time of day: the mark of an intraday row.
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")
# A full intraday timestamp: date, time (seconds optional, fractions ignored), then an optional zone: Z or +05:30 / -0500 / +05.
TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$", re.IGNORECASE)
# Seconds between bars -> the candle length id the rest of the app uses (`ranges.YAHOO_INTERVALS`).
STEPS = {60: "1m", 120: "2m", 300: "5m", 900: "15m", 1800: "30m", 3600: "60m", 5400: "90m"}


class CsvError(ValueError):
    pass


def symbol_name(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not SYMBOL_RE.match(s):
        raise CsvError("SYMBOL MUST BE 1-16 CHARACTERS: LETTERS, DIGITS AND . ^ = _ -")
    return s


def _num(raw: str, name: str, row: int) -> float:
    try:
        v = float(raw)
    except ValueError:
        raise CsvError(f"ROW {row}: BAD NUMBER IN {name} {raw!r}") from None
    if not math.isfinite(v):
        raise CsvError(f"ROW {row}: BAD NUMBER IN {name} {raw!r}")
    return v


@lru_cache(maxsize=16)
def zone_of(name: str):
    """A `zoneinfo` zone from its IANA name, matched ignoring case (the command line upper-cases some text)."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        pass
    by_lower = {z.lower(): z for z in available_timezones()}
    if (hit := by_lower.get(name.strip().lower())) is not None:
        return ZoneInfo(hit)
    raise CsvError(f"UNKNOWN TIME ZONE {name!r}: USE A NAME LIKE America/New_York OR Asia/Kolkata")


def _is_intraday(lines: list[str], header_len: int, date_col: int) -> bool:
    """Some date repeats AND the dates carry a time: see the module docstring. Looks at the date column only, so the
    daily path below keeps reporting its own errors in its own order."""
    seen: set[str] = set()
    timed = repeated = False
    for line in lines[1:]:
        cells = line.split(",")
        if len(cells) < header_len:
            continue
        cell = cells[date_col].strip()
        m = DATE_RE.match(cell)
        if m is None:
            continue
        timed = timed or TIME_RE.match(cell) is not None
        repeated = repeated or m.group(1) in seen
        seen.add(m.group(1))
    return timed and repeated


def _epoch(cell: str, zone, n: int) -> int:
    """UTC epoch seconds of one intraday timestamp cell (row `n`)."""
    m = TS_RE.match(cell)
    if m is None:
        raise CsvError(f"ROW {n}: BAD TIMESTAMP {cell!r} (INTRADAY ROWS LOOK LIKE 2026-01-02T09:30:00-05:00, OR 2026-01-02 09:30 WITH TZ=America/New_York)")
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    try:
        naive = dt.datetime(year, month, day, hh, mm, int(m.group(6) or 0))
    except ValueError:
        raise CsvError(f"ROW {n}: BAD TIMESTAMP {cell!r}") from None
    off = m.group(7)
    if off:
        if off.upper() == "Z":
            delta = dt.timedelta(0)
        else:
            digits = off[1:].replace(":", "")
            delta = dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0)) * (-1 if off[0] == "-" else 1)
        try:
            aware = naive.replace(tzinfo=dt.timezone(delta))
        except ValueError:
            raise CsvError(f"ROW {n}: BAD ZONE OFFSET {off!r}") from None
        return int(aware.timestamp())
    if zone is None:
        raise CsvError(f"ROW {n}: TIME {cell!r} HAS NO ZONE: ADD AN OFFSET (-05:00 OR Z) TO EVERY ROW, OR TZ=America/New_York TO THE COMMAND")
    aware = naive.replace(tzinfo=zone)
    # A wall-clock time skipped by a clock change (02:30 on the spring-forward day) does not exist: refuse, never guess.
    if aware.astimezone(dt.UTC).astimezone(zone).replace(tzinfo=None) != naive:
        raise CsvError(f"ROW {n}: {cell!r} DOES NOT EXIST IN {zone.key} (THE CLOCK SKIPS IT)")
    return int(aware.timestamp())


def _mins(seconds: int) -> str:
    return f"{seconds / 60:g} MIN"


def _spacing(ts: list[int]) -> tuple[int, str]:
    """(seconds, candle id) of the bars. The most common gap is the bar length; every gap must be a whole number of bars (the
    market is closed overnight and at weekends, so a gap of many bars is normal). Anything else means two bar lengths in one file."""
    gaps = [b - a for a, b in pairwise(ts)]
    counts = Counter(gaps)
    top = max(counts.values())
    step = min(g for g, k in counts.items() if k == top)  # ties: the shorter bar
    for i, g in enumerate(gaps):
        if g % step:
            when = dt.datetime.fromtimestamp(ts[i + 1], dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
            raise CsvError(f"MIXED BAR SPACING: MOST BARS ARE {_mins(step)} APART BUT THE BAR AT {when} COMES {_mins(g)} AFTER THE ONE BEFORE")
    if step not in STEPS:
        raise CsvError(f"BAR SPACING {_mins(step)} IS NOT A CANDLE LENGTH (USE 1, 2, 5, 15, 30, 60 OR 90 MINUTE BARS)")
    return step, STEPS[step]


def _parse_intraday(lines: list[str], header: list[str], at: dict[str, int], tz: str | None) -> dict:
    zone = zone_of(tz) if tz else None
    rows: list[tuple] = []
    for n, line in enumerate(lines[1:], start=1):
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < len(header):
            raise CsvError(f"ROW {n}: HAS {len(cells)} COLUMNS, THE HEADER HAS {len(header)}")
        ts = _epoch(cells[at["date"]], zone, n)
        o, h, lo, c = (_num(cells[at[k]], k, n) for k in ("open", "high", "low", "close"))
        if min(o, h, lo, c) <= 0:
            raise CsvError(f"ROW {n}: PRICES MUST BE POSITIVE")
        if h < lo:
            raise CsvError(f"ROW {n}: HIGH BELOW LOW")
        v = None
        if "volume" in at and cells[at["volume"]] != "":
            v = _num(cells[at["volume"]], "volume", n)
            if v < 0:
                raise CsvError(f"ROW {n}: NEGATIVE VOLUME")
        rows.append((ts, n, o, h, lo, c, v))
    rows.sort(key=lambda r: r[0])
    for a, b in pairwise(rows):
        if a[0] == b[0]:
            raise CsvError(f"ROW {max(a[1], b[1])}: DUPLICATE TIMESTAMP {dt.datetime.fromtimestamp(a[0], dt.UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    if len(rows) < 2:
        raise CsvError("NEEDS AT LEAST 2 ROWS")
    step, interval = _spacing([r[0] for r in rows])
    return {
        "d": [dt.datetime.fromtimestamp(r[0], dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ") for r in rows],
        "t": [r[0] for r in rows],
        "o": [r[2] for r in rows], "h": [r[3] for r in rows], "l": [r[4] for r in rows], "c": [r[5] for r in rows],
        "v": [r[6] for r in rows] if "volume" in at else None,
        # What marks the document as intraday (a daily document has none of these keys): the candle length it serves,
        # the bar spacing in seconds, and the zone the times were written in (labels only: `t` is already UTC).
        "iv": interval, "step": step, "tz": zone.key if zone is not None else "UTC",
    }


def parse_bars(text: str, tz: str | None = None) -> dict:
    """-> columnar bars {"d": ["YYYY-MM-DD"...], "t": epoch seconds (UTC midnight), "o", "h", "l", "c", "v" (None when
    the file has no volume column)}, oldest first. An intraday file (see the module docstring) also carries "iv", "step", "tz"
    and its "d" are UTC timestamps; `tz` is the zone name that times without an offset are written in."""
    lines = [ln for ln in text.lstrip("﻿").splitlines() if ln.strip()]
    if not lines:
        raise CsvError("EMPTY FILE")
    header = [h.strip().lower() for h in lines[0].split(",")]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise CsvError(f"NEEDS COLUMNS {','.join(REQUIRED)}[,volume] (MISSING {','.join(missing)}; HAS {','.join(header)})")
    if len(lines) - 1 > MAX_ROWS:
        raise CsvError(f"TOO MANY ROWS ({len(lines) - 1}; MAX {MAX_ROWS})")
    at = {c: header.index(c) for c in (*REQUIRED, "volume") if c in header}
    if _is_intraday(lines, len(header), at["date"]):
        return _parse_intraday(lines, header, at, tz)
    rows: list[tuple] = []
    seen: set[str] = set()
    for n, line in enumerate(lines[1:], start=1):
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < len(header):
            raise CsvError(f"ROW {n}: HAS {len(cells)} COLUMNS, THE HEADER HAS {len(header)}")
        m = DATE_RE.match(cells[at["date"]])
        try:
            day = dt.date.fromisoformat(m.group(1)) if m else None
        except ValueError:
            day = None
        if day is None:
            raise CsvError(f"ROW {n}: BAD DATE {cells[at['date']]!r} (USE YYYY-MM-DD)")
        if day.isoformat() in seen:
            raise CsvError(f"ROW {n}: DUPLICATE DATE {day.isoformat()}")
        seen.add(day.isoformat())
        o, h, lo, c = (_num(cells[at[k]], k, n) for k in ("open", "high", "low", "close"))
        if min(o, h, lo, c) <= 0:
            raise CsvError(f"ROW {n}: PRICES MUST BE POSITIVE")
        if h < lo:
            raise CsvError(f"ROW {n}: HIGH BELOW LOW")
        v = None
        if "volume" in at and cells[at["volume"]] != "":
            v = _num(cells[at["volume"]], "volume", n)
            if v < 0:
                raise CsvError(f"ROW {n}: NEGATIVE VOLUME")
        rows.append((day, o, h, lo, c, v))
    if len(rows) < 2:
        raise CsvError("NEEDS AT LEAST 2 ROWS")
    rows.sort(key=lambda r: r[0])
    return {
        "d": [r[0].isoformat() for r in rows],
        "t": [int(dt.datetime(r[0].year, r[0].month, r[0].day, tzinfo=dt.UTC).timestamp()) for r in rows],
        "o": [r[1] for r in rows], "h": [r[2] for r in rows], "l": [r[3] for r in rows], "c": [r[4] for r in rows],
        "v": [r[5] for r in rows] if "volume" in at else None,
    }
