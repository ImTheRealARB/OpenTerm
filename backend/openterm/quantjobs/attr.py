"""PORT ATTR (spec decision F): Brinson-Fachler by sector (Carino-linked monthly sub-periods) and TWR / MWR / Modified Dietz / simple return
from a stored valuation table. Today's holdings are held constant (labelled); benchmark sectors come from the benchmark ETF's sector weights
and the SPDR sector ETFs.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from itertools import pairwise

import numpy as np

from ..research.table import col, head, payload, section
from . import common as cm
from .sectors import SPDR, UNCLASSIFIED

NEEDS_VALS = "NEEDS 2 VALUATIONS: PORT ATTR ADD <date> VALUE= [FLOW=]"


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised internal rate (act/365) of dated flows. The rate is searched on [-0.9, 10] by scanning for a sign change, then bisecting
    inside it. None when there is no sign change (no root) or more than one (ambiguous: two different rates would both fit)."""
    t0 = flows[0][0]

    def f(r: float) -> float:
        return sum(a / (1.0 + r) ** ((d - t0).days / 365.0) for d, a in flows)

    # scan evenly in log(1 + r) space: it is fine near -90% and still cheap near +1000%
    grid = [math.exp(math.log(0.1) + (math.log(11.0) - math.log(0.1)) * k / 400) - 1.0 for k in range(401)]
    vals = [f(r) for r in grid]
    brackets = [(grid[k], grid[k + 1]) for k in range(400) if vals[k] == 0.0 or vals[k] * vals[k + 1] < 0]
    if len(brackets) != 1:
        return None
    lo, hi = brackets[0]
    flo = f(lo)
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def return_measures(vals: list[dict]) -> list[dict]:
    """Rows [{measure, value, note}] from valuations [{date, value, flow}] sorted by date. Flows are end of day; the first row's flow is part of
    its opening value. A measure that cannot be computed (zero or negative base after big withdrawals) has value None and a NOT DEFINED note."""
    d = [date.fromisoformat(v["date"]) for v in vals]
    v = [float(x["value"]) for x in vals]
    f = [float(x.get("flow") or 0.0) for x in vals]
    twr: float | None = 1.0
    for k in range(1, len(vals)):
        if v[k - 1] <= 0:  # nothing was invested at the start of this sub-period
            twr = None
            break
        twr *= (v[k] - f[k]) / v[k - 1]
    total_days = (d[-1] - d[0]).days
    flows_sum = sum(f[1:])
    weighted = sum(f[k] * (d[-1] - d[k]).days / total_days for k in range(1, len(vals))) if total_days else 0.0
    base = v[0] + weighted  # Modified Dietz denominator: average capital at work
    dietz = (v[-1] - v[0] - flows_sum) / base if base > 0 else None
    simple = (v[-1] - v[0] - flows_sum) / v[0] if v[0] > 0 else None
    cash = [(d[0], -v[0])] + [(d[k], -f[k]) for k in range(1, len(vals))]
    cash[-1] = (d[-1], cash[-1][1] + v[-1])
    irr = xirr(cash)
    undefined = "NOT DEFINED: START VALUE OR AVERAGE CAPITAL IS ZERO OR NEGATIVE (BIG WITHDRAWALS)"
    return [
        {"measure": "TWR", "value": None if twr is None else twr - 1.0,
         "note": "TIME-WEIGHTED, SUB-PERIODS END AT EACH VALUATION" if twr is not None else undefined},
        {"measure": "MWR (XIRR)", "value": irr, "note": "MONEY-WEIGHTED, ANNUALISED (ACT/365)" if irr is not None else "NOT DEFINED FOR THESE FLOWS"},
        {"measure": "MODIFIED DIETZ", "value": dietz, "note": "PERIOD RETURN, FLOWS WEIGHTED BY DAYS HELD" if dietz is not None else undefined},
        {"measure": "SIMPLE", "value": simple, "note": "(END - START - FLOWS) / START" if simple is not None else undefined},
    ]


def _brinson(params: dict, data: dict, w: np.ndarray, syms: list[str], notes: list[str]) -> tuple[list[dict], dict | None, str | None]:
    """(rows, headline numbers, problem). A problem is a NOT RUNNABLE reason for the BRINSON section."""
    from ..quantlib import attribution as qa

    bench_w = params.get("bench_weights")
    if params.get("sector_problem"):
        return [], None, params["sector_problem"]
    if not bench_w:
        return [], None, f"NOT RUNNABLE: NO SECTOR WEIGHTS FOR BENCHMARK {params.get('bench')}"
    sector_of = params.get("sector_of") or {}
    cols = {s: cm.series(data["bars"].get(s)) for s in syms}
    days, px = cm.align(cols)
    if days.size < 25:
        return [], None, f"NOT RUNNABLE: ONLY {days.size} DAYS COMMON TO ALL HOLDINGS"
    sec_of = [sector_of.get(s) or UNCLASSIFIED for s in syms]
    wp: dict[str, float] = {}
    for s, x in zip(sec_of, w, strict=True):
        wp[s] = wp.get(s, 0.0) + float(x)
    etf = {sec: cm.series((data.get("etf") or {}).get(sec)) for sec in set(wp) | set(bench_w) if sec in SPDR}
    missing = sorted(f"{SPDR[sec]} ({sec})" for sec in set(bench_w) | set(wp) if sec in SPDR and (bench_w.get(sec, 0) > 0 or wp.get(sec, 0) != 0)
                     and etf.get(sec, (np.array([]),))[0].size < 2)
    if missing:
        return [], None, f"NOT RUNNABLE: NO BARS FOR {', '.join(missing)}"
    # monthly boundaries: first common day, then the last common day of every calendar month
    dates = [date.fromordinal(719163 + int(x)) for x in days]  # 719163 = date(1970, 1, 1).toordinal()
    ym = np.array([d.year * 12 + d.month for d in dates])
    ends = [i for i in range(days.size) if i == days.size - 1 or ym[i + 1] != ym[i]]
    idx = [0, *[i for i in ends if i > 0]]
    periods = []
    for a, b in pairwise(idx):
        da, db = int(days[a]), int(days[b])
        r_hold = px[b] / px[a] - 1.0
        rp: dict[str, float] = {}
        for sec in wp:
            members = [i for i, s in enumerate(sec_of) if s == sec]
            tw = sum(w[i] for i in members)
            if abs(tw) > 1e-15:
                rp[sec] = float(sum(w[i] * r_hold[i] for i in members) / tw)
        rb: dict[str, float] = {}
        for sec, (ed, ec) in etf.items():
            if bench_w.get(sec, 0) > 0:
                s0, s1 = cm.asof(ed, ec, da), cm.asof(ed, ec, db)
                if s0 is None or s1 is None:
                    return [], None, f"NOT RUNNABLE: {SPDR[sec]} HAS NO BAR ON OR BEFORE {cm.iso(da)}"
                rb[sec] = s1 / s0 - 1.0
        periods.append(qa.brinson_fachler(wp, bench_w, rp, rb))
    try:
        link = qa.carino_link(periods)
    except ValueError as e:
        return [], None, f"NOT RUNNABLE: {e}"
    by = {s.sector: s for s in link.sectors}
    order = sorted(set(wp) | set(bench_w), key=lambda s: -(wp.get(s, 0) + bench_w.get(s, 0)))
    rows = []
    for s in order:
        e = by.get(s)
        a, sel, inter = (e.allocation, e.selection, e.interaction) if e else (0.0, 0.0, 0.0)
        rows.append({"sector": s, "wp": wp.get(s, 0.0), "wb": bench_w.get(s, 0.0), "allocation": a, "selection": sel, "interaction": inter,
                     "total": a + sel + inter})
    rows.append({"sector": "TOTAL", "wp": sum(wp.values()), "wb": sum(bench_w.values()), "allocation": link.allocation, "selection": link.selection,
                 "interaction": link.interaction, "total": link.total_effect})
    notes.append(f"BRINSON-FACHLER OVER {len(periods)} MONTHLY SUB-PERIODS ({cm.iso(int(days[0]))} TO {cm.iso(int(days[-1]))}), CARINO-LINKED")
    return rows, {"port": link.portfolio_return, "bench": link.benchmark_return, "active": link.active_return}, None


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    labels = params.get("labels") or {}
    title = f"PORT ATTR {params.get('name', '')}".strip()
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    progress(0.1, "loading bars")
    data = cm.load(params)
    pos = params["positions"]
    syms = [p["symbol"] for p in pos]
    bench = params.get("bench")
    notes: list[str] = []

    # --- RETURNS (stored valuations) --------------------------------------------------------------------------------------------
    vals = params.get("vals") or []
    if len(vals) >= 2:
        ret_rows = return_measures(vals)
        ret_note = f"{len(vals)} VALUATIONS, {vals[0]['date']} TO {vals[-1]['date']}; MWR IS ANNUALISED, THE OTHERS ARE FOR THE PERIOD"
    else:
        ret_rows, ret_note = [], NEEDS_VALS
        notes.append(NEEDS_VALS)
    returns_sec = section("returns", "RETURN MEASURES (FROM YOUR VALUATIONS)", [
        col("measure", "MEASURE", "text", 18), col("value", "VALUE", "pct"), col("note", "BASIS", "text", 50)], ret_rows, ret_note)

    # --- BRINSON ----------------------------------------------------------------------------------------------------------------
    progress(0.4, "brinson-fachler")
    short = [s for s in syms if cm.series(data["bars"].get(s))[0].size < 2]
    nums = None
    b_rows: list[dict] = []
    problem = None
    if short:
        problem = f"NOT RUNNABLE: NO DAILY BARS FOR {', '.join(short)}"
    else:
        fx = data.get("fx") or {}
        # value every holding on the last day all series share (as RISK does), not each series' own last close (audit B-1)
        common, px = cm.align({s: cm.series(data["bars"][s]) for s in syms})
        mv = (np.array([p["qty"] * px[-1, i] * fx.get(p.get("ccy") or "", 1.0) for i, p in enumerate(pos)])
              if common.size else np.zeros(0))
        if not common.size:
            problem = "NOT RUNNABLE: NO DAYS COMMON TO ALL HOLDINGS"
        elif not mv.sum() > 0:
            problem = "NOT RUNNABLE: NET PORTFOLIO VALUE IS NOT POSITIVE"
        else:
            b_rows, nums, problem = _brinson(params, data, mv / mv.sum(), syms, notes)
    bnote = (f"TODAY'S HOLDINGS HELD CONSTANT, NOT YOUR HISTORICAL WEIGHTS. BENCHMARK SECTORS FROM {bench} SECTOR WEIGHTS AND SPDR SECTOR ETFS"
             if not problem else problem)
    brinson = section("brinson", "BRINSON-FACHLER BY SECTOR", [
        col("sector", "SECTOR", "text", 24), col("wp", "PORT WT", "pct"), col("wb", "BENCH WT", "pct"), col("allocation", "ALLOCATION", "pct"),
        col("selection", "SELECTION", "pct"), col("interaction", "INTERACTION", "pct"), col("total", "TOTAL", "pct")], b_rows, bnote)
    heads = []
    if nums:
        heads += [head("PORTFOLIO RETURN", f"{nums['port'] * 100:.2f}%", nums["port"]), head("BENCH RETURN", f"{nums['bench'] * 100:.2f}%", nums["bench"]),
                  head("ACTIVE", f"{nums['active'] * 100:.2f}%", nums["active"])]
    else:
        heads.append(head("BRINSON", problem or "NOT RUNNABLE"))
        notes.append(problem or "NOT RUNNABLE")
    twr = next((r for r in ret_rows if r["measure"] == "TWR"), None)
    if twr:
        heads.append(head("TWR", f"{twr['value'] * 100:.2f}%", twr["value"]))
    notes[:0] = [f"TODAY'S HOLDINGS HELD CONSTANT, NOT YOUR HISTORICAL WEIGHTS; BENCHMARK SECTORS FROM {bench} SECTOR WEIGHTS (YAHOO) AND SPDR SECTOR ETFS",
                 "SECTORS: NASDAQ SCREENER NAMES MAPPED TO THE 11 SPDR SECTOR ETFS; NAMES WITHOUT A SECTOR ARE UNCLASSIFIED (NO BENCHMARK WEIGHT)",
                 "BENCH RETURN IS BUILT FROM SECTOR WEIGHTS AND SPDR SECTOR ETF RETURNS, SO IT DIFFERS SLIGHTLY FROM THE ETF'S OWN RETURN",
                 *cm.data_notes(labels)]
    if params.get("mixed_ccy"):
        notes.append("LOCAL-CURRENCY RETURNS, FX RISK NOT INCLUDED")
    progress(1.0, "done")
    return cm.envelope(payload(None, title, heads, [brinson, returns_sec], notes), labels)
