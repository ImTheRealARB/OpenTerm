"""The table payload every Phase 13 function answers (spec decision A). Pure helpers, no I/O.

    {symbol, title, headline:[{label, value, raw?}], sections:[{id, title, columns:[{key,title,kind,align}], rows, note}],
     notes:[str], key_required:[{key, what}], source}

`kind` tells the browser how to print a cell: text, int, num (2 decimals), num4 (4 decimals: Greeks), pct (ratio ->
percent), bp (basis points, 1 decimal), money (K/M/B/T), price, date. A cell that is None prints as a dash. A row's
`url`, when present, is opened by Enter.

Phase 14 adds three optional keys: `status` ("RUNNABLE" or "NOT RUNNABLE: <missing inputs>"), `charts`
([{id, title, xlabel, ylabel, series:[{name, points:[[x, y|None]], dash?}], marks?:[{x, label}]}], drawn on a numeric x
axis) and `heat` ({id, title, xlabel, ylabel, x:[..], y:[..], z:[[..]], unit}, a cell map).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

KINDS = ("text", "int", "num", "num4", "pct", "bp", "money", "price", "date")


def col(key: str, title: str, kind: str = "text", width: int | None = None) -> dict:
    assert kind in KINDS, kind
    out = {"key": key, "title": title, "kind": kind, "align": "left" if kind in ("text", "date") else "right"}
    if width:
        out["width"] = width
    return out


def section(sid: str, title: str, columns: list[dict], rows: list[dict], note: str | None = None) -> dict:
    keys = [c["key"] for c in columns]
    return {"id": sid, "title": title, "columns": columns, "note": note,
            "rows": [{**{k: None for k in keys}, **r} for r in rows]}


def head(label: str, value: str | None, raw: Any = None) -> dict:
    out = {"label": label, "value": value if value is not None else "-"}
    if raw is not None:
        out["raw"] = raw
    return out


def payload(symbol: str | None, title: str, headline: list[dict], sections: list[dict], notes: list[str] | None = None,
            source: str | None = None, key_required: list[dict] | None = None, status: str | None = None,
            charts: list[dict] | None = None, heat: dict | None = None) -> dict:
    out = {"symbol": symbol, "title": title, "headline": headline, "sections": sections, "notes": notes or [],
           "key_required": key_required or [], "source": source}
    if status is not None:
        out["status"] = status
    if charts:
        out["charts"] = charts
    if heat:
        out["heat"] = heat
    return out


def iso_date(epoch: float | None) -> str | None:
    if epoch in (None, 0):
        return None
    return datetime.fromtimestamp(float(epoch), UTC).strftime("%Y-%m-%d")


def us_date(text: str | None) -> str | None:
    """Nasdaq prints MM/DD/YYYY (sometimes M/D/YYYY). Returns YYYY-MM-DD, or None for anything else."""
    if not text:
        return None
    try:
        m, d, y = (int(x) for x in text.strip().split("/"))
        return f"{y:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


def number(text: Any) -> float | None:
    """Nasdaq prints '$1,234.50', '9,375,000', 'N/A', ''. Returns a float or None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None
