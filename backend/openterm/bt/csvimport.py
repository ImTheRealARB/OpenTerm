"""IMPORT: daily bars from the user's own CSV (spec decision K). Pure Python, no pandas, so the server parses them.

Columns (any order, any case): date, open, high, low, close, volume (optional). Dates are `YYYY-MM-DD` (a time after
it is ignored: the data is daily). Rows are sorted by date; a duplicate date, a non-numeric or non-positive price, or a
high below the low rejects the whole file with the row number, never a silent fix. The browser parser
(`frontend/src/bt/csvImport.ts`) applies the same rules for the preview; this one is the authority.
"""

from __future__ import annotations

import datetime as dt
import math
import re

REQUIRED = ("date", "open", "high", "low", "close")
MAX_ROWS = 200_000
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T].*)?$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.^=_-]{0,15}$")


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


def parse_bars(text: str) -> dict:
    """-> columnar bars {"d": ["YYYY-MM-DD"...], "t": epoch seconds (UTC midnight), "o", "h", "l", "c", "v" (None when
    the file has no volume column)}, oldest first."""
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
