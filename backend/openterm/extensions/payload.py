"""The two payload shapes an extension route may return, checked and cleaned before they reach the browser.

table:  {"kind": "table", "title", "columns": [{"key", "title", "kind"?, "align"?}], "rows": [{key: value}], "notes"?: [str]}
series: {"kind": "series", "title", "unit"?, "t": [epoch seconds, ascending], "v": [number | null]}

The browser draws a table with the Grid and a series with the chart, so an extension needs no frontend build. A cell holds text,
a number, a boolean or null; a number that is not finite becomes null (a dash on screen), never a made-up value.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

MAX_ROWS = 2000
MAX_COLUMNS = 30
MAX_POINTS = 20_000
MAX_TEXT = 500
MAX_NOTES = 10
CELL_KINDS = {"text", "int", "num", "num4", "pct", "bp", "money", "price", "date"}
RIGHT = {"int", "num", "num4", "pct", "bp", "money", "price"}


class PayloadError(ValueError):
    pass


def _text(v: Any, what: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(v, str):
        raise PayloadError(f"{what} MUST BE TEXT")
    return v[:limit]


def _cell(v: Any) -> str | int | float | bool | None:
    if v is None or isinstance(v, (bool, int, str)):
        return v[:MAX_TEXT] if isinstance(v, str) else v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    raise PayloadError(f"A CELL MUST BE TEXT, A NUMBER, TRUE/FALSE OR NULL, NOT {type(v).__name__}")


def _number(v: Any) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PayloadError("A SERIES VALUE MUST BE A NUMBER OR NULL")
    return v if math.isfinite(v) else None


def _table(p: dict) -> dict:
    cols_in, rows_in = p.get("columns"), p.get("rows")
    if not isinstance(cols_in, list) or not 1 <= len(cols_in) <= MAX_COLUMNS:
        raise PayloadError(f"A TABLE NEEDS 1 TO {MAX_COLUMNS} COLUMNS")
    if not isinstance(rows_in, list) or len(rows_in) > MAX_ROWS:
        raise PayloadError(f"A TABLE HAS AT MOST {MAX_ROWS} ROWS")
    cols, keys = [], set()
    for c in cols_in:
        if not isinstance(c, dict):
            raise PayloadError("A COLUMN MUST BE AN OBJECT")
        key = _text(c.get("key"), "COLUMN KEY", 64)
        if not key or key in keys:
            raise PayloadError("COLUMN KEYS MUST BE UNIQUE AND NOT EMPTY")
        keys.add(key)
        kind = c.get("kind", "text")
        if kind not in CELL_KINDS:
            raise PayloadError(f"COLUMN KIND MUST BE ONE OF {', '.join(sorted(CELL_KINDS))}")
        align = c.get("align") or ("right" if kind in RIGHT else "left")
        if align not in ("left", "right"):
            raise PayloadError("COLUMN ALIGN MUST BE left OR right")
        cols.append({"key": key, "title": _text(c.get("title", key), "COLUMN TITLE", 40), "kind": kind, "align": align})
    rows = []
    for r in rows_in:
        if not isinstance(r, dict):
            raise PayloadError("A ROW MUST BE AN OBJECT")
        rows.append({k: _cell(r.get(k)) for k in keys})
    notes = p.get("notes") or []
    if not isinstance(notes, list) or len(notes) > MAX_NOTES:
        raise PayloadError(f"NOTES MUST BE A LIST OF AT MOST {MAX_NOTES} TEXTS")
    return {"kind": "table", "title": _text(p.get("title", ""), "TITLE", 200), "columns": cols, "rows": rows,
            "notes": [_text(n, "NOTE") for n in notes]}


def _series(p: dict) -> dict:
    t, v = p.get("t"), p.get("v")
    if not isinstance(t, list) or not isinstance(v, list) or len(t) != len(v):
        raise PayloadError("A SERIES NEEDS t AND v LISTS OF THE SAME LENGTH")
    if len(t) > MAX_POINTS:
        raise PayloadError(f"A SERIES HAS AT MOST {MAX_POINTS} POINTS")
    for x in t:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise PayloadError("t MUST HOLD EPOCH SECONDS")
    if any(b <= a for a, b in pairwise(t)):
        raise PayloadError("t MUST BE ASCENDING")
    return {"kind": "series", "title": _text(p.get("title", ""), "TITLE", 200), "unit": _text(p.get("unit", ""), "UNIT", 40),
            "t": [int(x) for x in t], "v": [_number(x) for x in v]}


def normalize(payload: Any) -> dict:
    """The cleaned payload, or PayloadError saying what is wrong. Unknown keys are dropped."""
    if not isinstance(payload, dict):
        raise PayloadError("A ROUTE MUST RETURN AN OBJECT")
    kind = payload.get("kind")
    if kind == "table":
        return _table(payload)
    if kind == "series":
        return _series(payload)
    raise PayloadError("PAYLOAD kind MUST BE table OR series")
