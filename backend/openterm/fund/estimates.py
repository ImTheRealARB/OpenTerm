"""EM (earnings matrix) and REVS (estimate revision score), Phase 29. Pure.

Two different EPS numbers meet here and are never mixed: SEC's reported GAAP diluted EPS (from the 10-Q/10-K) and the
consensus estimate with its "actual" as Yahoo reports them (usually adjusted EPS). A surprise is always Yahoo actual vs
Yahoo estimate (same basis), never SEC EPS vs an adjusted estimate.
"""

from __future__ import annotations

from datetime import date

MATCH_DAYS = 20  # a Yahoo quarter (calendar end date) matches the SEC fiscal quarter ending within this many days


def _near(a: str, b: str) -> bool:
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days) <= MATCH_DAYS
    except ValueError:
        return False


def matrix(q_rows: list[dict], surprises: list[dict]) -> dict:
    """Quarters x fiscal years.

    q_rows: SEC quarterly rows (metrics.rows_of, oldest first), each with fy/fp from the label ("Q3 FY2025"), end,
            eps_diluted, revenue.
    surprises: Yahoo rows {"quarter": "YYYY-MM-DD", "actual", "estimate", "surprise"} (surprise as a ratio).
    Returns {"years": [fy...], "cells": {(fp, fy): {...}}} with fp in Q1..Q4.
    """
    cells: dict[tuple[str, int], dict] = {}
    years: set[int] = set()
    for r in q_rows:
        fp, fy = _fp_fy(r.get("label") or "")
        if fp is None:
            continue
        years.add(fy)
        hit = next((s for s in surprises if s.get("quarter") and _near(s["quarter"], r["end"])), None)
        cells[(fp, fy)] = {
            "end": r["end"], "eps": r.get("eps_diluted"), "revenue": r.get("revenue"),
            "est": hit.get("estimate") if hit else None, "actual_adj": hit.get("actual") if hit else None,
            "surprise": hit.get("surprise") if hit else None,
        }
    return {"years": sorted(years), "cells": cells}


def _fp_fy(label: str) -> tuple[str | None, int]:
    """'Q3 FY2025' -> ('Q3', 2025); anything else -> (None, 0)."""
    parts = label.split()
    if len(parts) == 2 and parts[0] in ("Q1", "Q2", "Q3", "Q4") and parts[1].startswith("FY") and parts[1][2:].isdigit():
        return parts[0], int(parts[1][2:])
    return None, 0


def revision_score(trend: list[dict], revisions: list[dict]) -> dict:
    """A transparent revision-momentum score from -100 to +100.

    trend rows: {"period", "now", "d30", "d90"} (EPS estimate now and 30 / 90 days ago).
    revisions rows: {"period", "up30", "down30"} (analysts who raised / lowered it in 30 days).
    SCORE = 50 x BREADTH + 50 x DRIFT, where BREADTH = mean over periods of (up30 - down30) / (up30 + down30) and
    DRIFT = mean 30-day change of the estimate, divided by 5% and capped to -1..+1 (a 5% move in a month is a full point).
    """
    breadth, drift, rows = [], [], []
    by_rev = {r.get("period"): r for r in revisions}
    for t in trend:
        p = t.get("period")
        now, d30, d90 = t.get("now"), t.get("d30"), t.get("d90")
        ch30 = (now / d30 - 1) if now is not None and d30 not in (None, 0) and d30 > 0 else None
        ch90 = (now / d90 - 1) if now is not None and d90 not in (None, 0) and d90 > 0 else None
        rv = by_rev.get(p) or {}
        up, down = rv.get("up30"), rv.get("down30")
        b = (up - down) / (up + down) if up is not None and down is not None and (up + down) > 0 else None
        if b is not None:
            breadth.append(b)
        if ch30 is not None:
            drift.append(max(-1.0, min(1.0, ch30 / 0.05)))
        rows.append({"period": p, "now": now, "ch30": ch30, "ch90": ch90, "up30": up, "down30": down, "breadth": b})
    if not breadth and not drift:
        return {"score": None, "breadth": None, "drift": None, "rows": rows}
    b_mean = sum(breadth) / len(breadth) if breadth else 0.0
    d_mean = sum(drift) / len(drift) if drift else 0.0
    return {"score": 50 * b_mean + 50 * d_mean, "breadth": b_mean if breadth else None, "drift": d_mean if drift else None,
            "rows": rows}
