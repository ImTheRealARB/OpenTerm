"""SEC XBRL frames (Phase 29): one concept for EVERY filer in one period, point-in-time rules, screen backtest. Pure.

Frames URL: https://data.sec.gov/api/xbrl/frames/us-gaap/<tag>/<unit>/<period>.json, period = CY2023 (a calendar-year
duration), CY2023Q4 (a quarter) or CY2023Q4I (an instant at the quarter end). Each data row is
{accn, cik, entityName, loc, start?, end, val}. SEC picks for each filer the fiscal period that best fits the calendar
period, so a June fiscal year lands in the CY it mostly covers.

POINT IN TIME: frames carry NO filing date. A value is treated as KNOWN only after its period end plus the SEC's longest
filing deadline (90 days for an annual report, 45 for a quarter, the deadlines for the smallest filers), so a screen run
"as of" a date never uses numbers that could not have been public. Late filers make this optimistic; it says so on screen.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from statistics import median

ANNUAL_LAG_DAYS = 90
QUARTER_LAG_DAYS = 45
KNOWN_RULE = "KNOWN DATE = PERIOD END + SEC DEADLINE (90 DAYS ANNUAL, 45 QUARTERLY): THE FRAMES API HAS NO FILING DATES"

# Concepts the screen fields use: (frame tag, unit, instant?) in priority order (first tag found per filer wins).
CONCEPTS: dict[str, list[tuple[str, str, bool]]] = {
    "revenue": [("Revenues", "USD", False), ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", False)],
    "net_income": [("NetIncomeLoss", "USD", False)],
    "operating_income": [("OperatingIncomeLoss", "USD", False)],
    "equity": [("StockholdersEquity", "USD", True)],
    "liabilities": [("Liabilities", "USD", True)],
}

# Screen fields -> (label, needs). Ratios are computed per filer from the concepts of the same calendar year.
FIELDS = {
    "MARGIN": "NET MARGIN = NET INCOME / REVENUE",
    "OPMARGIN": "OPERATING MARGIN = OPERATING INCOME / REVENUE",
    "ROE": "RETURN ON EQUITY = NET INCOME / YEAR-END EQUITY",
    "GROWTH": "REVENUE GROWTH = REVENUE / PRIOR-YEAR REVENUE - 1",
    "DE": "LIABILITIES / EQUITY",
    "MOM12": "12-MONTH PRICE RETURN (FROM THE BARS)",
}
RULE_RE = re.compile(r"^(MARGIN|OPMARGIN|ROE|GROWTH|DE|MOM12)(<=|>=|<|>)(-?\d+(?:\.\d+)?)%?$")


def frame_period(year: int, instant: bool) -> str:
    return f"CY{year}Q4I" if instant else f"CY{year}"


def known_date(end: str, annual: bool = True) -> date:
    return date.fromisoformat(end) + timedelta(days=ANNUAL_LAG_DAYS if annual else QUARTER_LAG_DAYS)


def parse_frame(body: dict) -> dict[int, dict]:
    """{cik: {"val", "end", "accn", "name"}} from one frames answer (rows without a number are dropped)."""
    out: dict[int, dict] = {}
    for r in body.get("data") or []:
        if isinstance(r.get("val"), (int, float)) and r.get("cik") and r.get("end"):
            out[int(r["cik"])] = {"val": float(r["val"]), "end": r["end"], "accn": r.get("accn"), "name": r.get("entityName")}
    return out


def merge_concept(frames: list[dict[int, dict]]) -> dict[int, dict]:
    """First frame (highest-priority tag) wins per filer: [Revenues, RevenueFromContract...] -> one revenue map."""
    out: dict[int, dict] = {}
    for f in frames:
        for cik, row in f.items():
            out.setdefault(cik, row)
    return out


def year_values(by_concept: dict[str, dict[int, dict]], cik: int) -> dict[str, float | None]:
    return {k: (m.get(cik) or {}).get("val") for k, m in by_concept.items()}


def fields_for(cur: dict[str, float | None], prev: dict[str, float | None]) -> dict[str, float | None]:
    """Screen field values of one filer for one calendar year (prev = the year before, for GROWTH)."""
    def div(a, b):
        return a / b if a is not None and b not in (None, 0) else None

    eq = cur.get("equity")
    return {
        "MARGIN": div(cur.get("net_income"), cur.get("revenue")),
        "OPMARGIN": div(cur.get("operating_income"), cur.get("revenue")),
        "ROE": div(cur.get("net_income"), eq) if eq and eq > 0 else None,
        "GROWTH": (div(cur.get("revenue"), prev.get("revenue")) - 1) if div(cur.get("revenue"), prev.get("revenue")) is not None else None,
        "DE": div(cur.get("liabilities"), eq) if eq and eq > 0 else None,
    }


def parse_rules(words: list[str]) -> list[tuple[str, str, float]]:
    """`MARGIN>0.2 ROE>15%` -> [(field, op, value)]; a trailing % divides by 100. Raises ValueError on a bad word."""
    rules = []
    for w in words:
        m = RULE_RE.match(w.upper())
        if not m:
            raise ValueError(f"BAD RULE {w}: USE FIELD<OP>NUMBER, FIELDS {' '.join(FIELDS)}")
        field, op, num = m.groups()
        v = float(num) / (100 if w.endswith("%") else 1)
        rules.append((field, op, v))
    if not rules:
        raise ValueError(f"NO RULES: E.G. MARGIN>0.15 GROWTH>0.05 (FIELDS {' '.join(FIELDS)})")
    return rules


def passes(values: dict[str, float | None], rules: list[tuple[str, str, float]]) -> bool:
    """A missing value fails the rule (the filer did not report it, so the screen cannot claim it passed)."""
    for field, op, v in rules:
        x = values.get(field)
        if x is None:
            return False
        if not ((op == ">" and x > v) or (op == "<" and x < v) or (op == ">=" and x >= v) or (op == "<=" and x <= v)):
            return False
    return True


def month_ends(t: list[float]) -> list[int]:
    """Indexes of the last bar of each calendar month in daily epoch seconds (UTC)."""
    idx = []
    for i, (a, b) in enumerate(pairwise(t)):
        if datetime.fromtimestamp(a, UTC).month != datetime.fromtimestamp(b, UTC).month:
            idx.append(i)
    if t:
        idx.append(len(t) - 1)
    return idx


def stats(rets: list[float]) -> dict:
    """CAGR, annual vol, max drawdown and hit rate of monthly returns."""
    if not rets:
        return {"months": 0, "cagr": None, "vol": None, "maxdd": None, "hit": None, "total": None}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    n = len(rets)
    mean = sum(rets) / n
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1)) * math.sqrt(12) if n > 1 else None
    return {"months": n, "total": eq - 1, "cagr": eq ** (12 / n) - 1, "vol": vol, "maxdd": mdd,
            "hit": sum(1 for r in rets if r > 0) / n}


def median_or_none(xs: list[float]) -> float | None:
    return median(xs) if xs else None


def iqr(xs: list[float]) -> float | None:
    """Interquartile range (75th minus 25th percentile, linear interpolation): the dispersion IBQ shows."""
    if len(xs) < 4:
        return None
    s = sorted(xs)

    def q(p):
        k = (len(s) - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    return q(0.75) - q(0.25)
