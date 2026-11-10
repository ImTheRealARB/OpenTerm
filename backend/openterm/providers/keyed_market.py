"""Shared helpers for the keyed market-data adapters (Twelve Data, Alpha Vantage, Polygon, FMP).

Pure functions, no I/O: number parsing, the "last N sessions" cut for 1D / 5D intraday charts, the Yahoo-suffix to exchange-code maps,
and `build_fa`, which lays vendor financial statements out in the same shape SEC EDGAR's parser gives FA (`sec_parse._statements`),
so the FA panel needs no change when SEC cannot answer.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from .sec_parse import MAX_PERIODS, ROWS

# Yahoo-style interval -> bars in one regular US session (used to size a request and to declare `intraday_days`).
BARS_PER_SESSION = {"1m": 390, "2m": 195, "5m": 78, "15m": 26, "30m": 13, "60m": 7, "90m": 5}
# Candle length in minutes.
INTERVAL_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "90m": 90}
SESSIONS = {"1d": 1, "5d": 5}
"""Ranges that mean "the last N sessions": the window is fetched with a few spare days and cut to N sessions."""


def fnum(v: Any) -> float | None:
    """A vendor number as float: None for missing, 'None', '-', '' or anything that is not finite."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = str(v).strip().replace(",", "").rstrip("%")
    if s in ("", "None", "-", "N/A", "NA", "null"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def inum(v: Any) -> int | None:
    f = fnum(v)
    return int(f) if f is not None else None


def trim_sessions(rows: list[tuple[int, str]], n: int) -> int:
    """Index in `rows` (oldest first, (epoch, session-date text)) where the last `n` sessions start."""
    seen: list[str] = []
    for _t, day in reversed(rows):
        if day not in seen:
            seen.append(day)
        if len(seen) > n:
            break
    keep = set(seen[:n])
    for i, (_t, day) in enumerate(rows):
        if day in keep:
            return i
    return len(rows)


def depth_days(per_session_bars: int, max_bars: int) -> int:
    """Calendar days of a candle length that fit into `max_bars` (5 sessions of 7 days)."""
    return int(max_bars / per_session_bars * 7 / 5)


# Yahoo exchange suffix -> ISO 10383 market code (Twelve Data `mic_code`).
SUFFIX_MIC = {
    "NS": "XNSE", "BO": "XBOM", "L": "XLON", "TO": "XTSE", "V": "XTSX", "HK": "XHKG", "T": "XTKS", "DE": "XETR", "PA": "XPAR",
    "AS": "XAMS", "MI": "XMIL", "MC": "XMAD", "SW": "XSWX", "AX": "XASX", "SI": "XSES", "ST": "XSTO", "SS": "XSHG", "SZ": "XSHE",
    "KS": "XKRX", "TW": "XTAI",
}
MIC_SUFFIX = {v: k for k, v in SUFFIX_MIC.items()}
US_MICS = {"XNAS", "XNGS", "XNMS", "XNCM", "XNYS", "ARCX", "XASE", "BATS", "IEXG", "XNDQ", "OTCM", "XOTC"}


def build_fa(
    reports: dict[str, list[dict]],
    fields: dict[str, tuple[str, str | tuple[str, ...], Callable[[float], float] | None]],
    date_key: str,
    label: Callable[[dict], tuple[str, int | None, str | None]],
    mode: str,
) -> dict:
    """Vendor statements -> {"periods": [...], "statements": {"IS": [...], "BS": [...], "CF": [...]}} like sec_parse._statements.

    `reports`: {"IS": [row, ...], "BS": [...], "CF": [...]}, each row one period as the vendor sent it (strings or numbers).
    `fields`: row key (sec_parse.ROWS key) -> (statement, vendor field, transform or None). A row with no mapping stays all None:
    the panel shows it blank, never estimated. Free cash flow is computed (operating minus capex), flagged "c".
    `label(income_row)` -> (column label, fiscal year, fiscal period) for the period.
    """
    by: dict[str, dict[str, dict]] = {s: {str(r.get(date_key)): r for r in rows if r.get(date_key)} for s, rows in reports.items()}
    ends = sorted(set(by["IS"]) or set().union(*(set(d) for d in by.values())), reverse=True)[: MAX_PERIODS[mode]]
    statements: dict[str, list[dict]] = {"IS": [], "BS": [], "CF": []}
    for stmt, key, name, _kind, unit, _tags in ROWS:
        values: list[float | None] = []
        used: list[str | None] = []
        spec = fields.get(key)
        for end in ends:
            v, tag = None, None
            if spec is not None and spec[0] == stmt:
                row = by[stmt].get(end) or {}
                for field in (spec[1],) if isinstance(spec[1], str) else spec[1]:  # a tuple = first field the vendor filled
                    raw = fnum(row.get(field))
                    if raw is not None:
                        v, tag = (spec[2](raw) if spec[2] else raw), field
                        break
            values.append(v)
            used.append(tag)
        statements[stmt].append({"key": key, "label": name, "unit": unit, "values": values, "flags": [""] * len(ends), "tags": used})
    rows_by_key = {r["key"]: r for rows in statements.values() for r in rows}
    ocf, capex = rows_by_key["operating_cf"], rows_by_key["capex"]
    fcf: dict[str, Any] = {"key": "fcf", "label": "Free cash flow (computed)", "unit": "USD", "values": [], "flags": [], "tags": [], "computed": True}
    for i in range(len(ends)):
        a, b = ocf["values"][i], capex["values"][i]
        fcf["values"].append(a - b if a is not None and b is not None else None)
        fcf["flags"].append("c")
        fcf["tags"].append("operating cash flow - capital expenditure")
    statements["CF"].insert(2, fcf)
    periods = []
    for end in ends:
        lbl, fy, fp = label(by["IS"].get(end) or {date_key: end})
        periods.append({"key": end, "label": lbl, "end": end, "start": None, "fy": fy, "fp": fp, "form": None, "filed": None, "derived": False})
    return {"periods": periods, "statements": statements}
