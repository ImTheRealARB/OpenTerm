"""GF / DDIS / EM helpers (Phase 29): turn the FA statements (sec_parse) into per-period rows and metric series. Pure.

A "row" is one fiscal period as a flat dict: {"end", "filed", "form", "accn", "label", <FA keys>, <EXTRA keys>}.
Rows are returned OLDEST FIRST (FA columns are newest first).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

FLOWS = ("revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income", "eps_diluted", "operating_cf",
         "capex", "fcf", "da", "income_tax", "pretax_income", "interest_expense")
"""Duration items: summed over four quarters for a trailing-twelve-month (TTM) value."""


def rows_of(view: dict, extra: dict | None = None) -> list[dict]:
    """FA view ({"periods", "statements"}) + Phase 29 extra rows -> per-period dicts, oldest first."""
    periods = view["periods"]
    out = [{"end": p["end"], "filed": p.get("filed"), "form": p.get("form"), "accn": p.get("accn"), "label": p["label"]}
           for p in periods]
    for rows in view["statements"].values():
        for r in rows:
            for i, v in enumerate(r["values"]):
                out[i][r["key"]] = v
    for key, r in (extra or {}).items():
        for i, v in enumerate(r["values"]):
            out[i][key] = v
            out[i][f"{key}__tag"] = r["tags"][i]
    return out[::-1]


PER_SHARE = ("eps_basic", "eps_diluted")
SHARE_COUNTS = ("shares_diluted", "shares_out")


def split_adjust(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Put old per-share numbers on today's share basis (rows oldest first).

    SEC restates EPS for a split only in filings made after it, so a series mixes bases (Apple's FY2018 EPS is pre 4-for-1,
    FY2019 restated). Price histories are split-adjusted, so a P/E on the raw series is 4x too low. A jump in the diluted
    share count between two periods by 1.8x or more (or a drop to 0.55x or less) is read as a split of the rounded ratio;
    every older row's EPS is divided and share count multiplied by it. Returns (rows, notes naming each inferred split)."""
    out = [dict(r) for r in rows]
    notes: list[str] = []
    factor = 1.0
    for i in range(len(out) - 1, 0, -1):
        newer, older = rows[i].get("shares_diluted"), rows[i - 1].get("shares_diluted")
        if newer and older:
            ratio = newer / older
            step = float(round(ratio)) if ratio >= 1.8 else 1 / round(1 / ratio) if ratio <= 0.55 else 1.0
            if step != 1.0:
                factor *= step
                notes.append(f"SPLIT INFERRED FROM THE SHARE COUNT: x{step:g} BETWEEN {rows[i - 1]['end']} AND {rows[i]['end']}")
        if factor != 1.0:
            r = out[i - 1]
            for k in PER_SHARE:
                if r.get(k) is not None:
                    r[k] = r[k] / factor
            for k in SHARE_COUNTS:
                if r.get(k) is not None:
                    r[k] = r[k] * factor
    return out, notes


def ttm(rows: list[dict]) -> list[dict]:
    """Quarterly rows -> the same rows with flows replaced by the sum of the last four quarters (None until four exist,
    or when a quarter in the window is missing). Balance-sheet items stay as reported at the quarter end."""
    out = []
    for i, r in enumerate(rows):
        t = dict(r)
        window = rows[i - 3: i + 1] if i >= 3 else []
        for k in FLOWS:
            vals = [w.get(k) for w in window]
            t[k] = sum(vals) if len(vals) == 4 and all(v is not None for v in vals) else None
        out.append(t)
    return out


def _div(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0) else None


def _tax_rate(r: dict) -> float:
    """Effective tax rate clipped to 0-50%; 21% (US federal) when the filing gives no pretax income or tax line."""
    t = _div(r.get("income_tax"), r.get("pretax_income"))
    return 0.21 if t is None else min(max(t, 0.0), 0.5)


def _roic(r: dict) -> float | None:
    """NOPAT / invested capital = operating income x (1 - tax rate) / (debt + equity - cash)."""
    oi, eq = r.get("operating_income"), r.get("equity")
    if oi is None or eq is None:
        return None
    ic = (r.get("long_term_debt") or 0.0) + (r.get("current_debt") or 0.0) + eq - (r.get("cash") or 0.0)
    return oi * (1 - _tax_rate(r)) / ic if ic > 0 else None


def _ebitda(r: dict) -> float | None:
    oi, da = r.get("operating_income"), r.get("da")
    return oi + da if oi is not None and da is not None else None


def _net_debt(r: dict) -> float:
    return (r.get("long_term_debt") or 0.0) + (r.get("current_debt") or 0.0) - (r.get("cash") or 0.0)


# code -> (label, unit, per-period function). unit: money | pct | num | x (multiple)
FUNDAMENTAL: dict[str, tuple[str, str, Callable[[dict], float | None]]] = {
    "REVENUE": ("REVENUE", "money", lambda r: r.get("revenue")),
    "NI": ("NET INCOME", "money", lambda r: r.get("net_income")),
    "EPS": ("EPS DILUTED", "num", lambda r: r.get("eps_diluted")),
    "FCF": ("FREE CASH FLOW", "money", lambda r: r.get("fcf")),
    "GM": ("GROSS MARGIN", "pct", lambda r: _div(r.get("gross_profit"), r.get("revenue"))),
    "OM": ("OPERATING MARGIN", "pct", lambda r: _div(r.get("operating_income"), r.get("revenue"))),
    "NM": ("NET MARGIN", "pct", lambda r: _div(r.get("net_income"), r.get("revenue"))),
    "ROE": ("RETURN ON EQUITY", "pct", lambda r: _div(r.get("net_income"), r.get("equity"))),
    "ROIC": ("RETURN ON INVESTED CAPITAL", "pct", _roic),
    "DE": ("DEBT / EQUITY", "x", lambda r: _div((r.get("long_term_debt") or 0.0) + (r.get("current_debt") or 0.0), r.get("equity"))),
}

# code -> (label, function(row, market cap)) : valuation multiples, computed DAILY from the latest filed period.
VALUATION: dict[str, tuple[str, Callable[[dict, float], float | None]]] = {
    "PE": ("P/E (PRICE / TTM DILUTED EPS)", lambda r, mcap: None),  # computed from price / EPS below (per share)
    "PS": ("PRICE / SALES", lambda r, mcap: _div(mcap, r.get("revenue"))),
    "PB": ("PRICE / BOOK", lambda r, mcap: _div(mcap, r.get("equity"))),
    "EVEBITDA": ("EV / EBITDA", lambda r, mcap: _div(mcap + _net_debt(r), _ebitda(r))),
}
METRICS = sorted([*FUNDAMENTAL, *VALUATION])


def epoch(day: str) -> int:
    return int(datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC).timestamp())


def fundamental_series(rows: list[dict], code: str) -> list[tuple[int, float | None]]:
    """[(period end epoch, value)] oldest first."""
    fn = FUNDAMENTAL[code][2]
    return [(epoch(r["end"]), fn(r)) for r in rows]


def valuation_series(rows: list[dict], code: str, t: list[float], c: list[float]) -> list[tuple[int, float | None]]:
    """Daily multiple: each day uses the newest period FILED on or before that day (no look-ahead).
    Market cap = close x diluted shares of that period (the filing's weighted average, the closest SEC gives)."""
    filed = sorted((r for r in rows if r.get("filed")), key=lambda r: r["filed"])
    known = [(epoch(r["filed"]), r) for r in filed]
    out: list[tuple[int, float | None]] = []
    j, cur = 0, None
    for ts, px in zip(t, c, strict=True):
        while j < len(known) and known[j][0] <= ts:
            cur = known[j][1]
            j += 1
        if cur is None or px is None:
            continue
        if code == "PE":
            eps = cur.get("eps_diluted")
            v = px / eps if eps and eps > 0 else None  # a negative P/E is meaningless: a gap, not a number
        else:
            sh = cur.get("shares_diluted")
            v = VALUATION[code][1](cur, px * sh) if sh else None
            if v is not None and v <= 0:
                v = None
        out.append((int(ts), v))
    return out


def ladder(row: dict) -> list[dict]:
    """DDIS: the debt maturity ladder of one 10-K. Years are fiscal years after the balance-sheet date."""
    names = [("mat_y1", "NEXT 12 MONTHS"), ("mat_y2", "YEAR 2"), ("mat_y3", "YEAR 3"), ("mat_y4", "YEAR 4"),
             ("mat_y5", "YEAR 5"), ("mat_after", "AFTER YEAR 5")]
    vals = [row.get(k) for k, _ in names]
    total = sum(v for v in vals if v is not None)
    return [{"bucket": label, "amount": row.get(k), "share": _div(row.get(k), total) if total else None,
             "tag": row.get(f"{k}__tag")} for k, label in names]
