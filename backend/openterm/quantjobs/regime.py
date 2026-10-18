"""CORR REGIME (spec decision J): edge density of the rolling correlation graph and its FUSED / DIFFUSE hysteresis state (Vibe `regime.py`).

Plain rolling pairwise correlation exactly as Vibe's `compute_edge_density`: the share of distinct pairs whose |correlation| over the last
`win` returns is at least `edge`. Smoothed over 5 bars, FUSED from 0.65, back to DIFFUSE at 0.45. Descriptive risk context, not a signal.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ..quantlib.regime import _aligned_returns, compute_edge_density, detect_regimes
from ..research.table import col, head, payload, section
from . import common as cm

SMOOTH = 5
ENTER = 0.65
EXIT = 0.45


def episodes(dates: list[str], state: list[int], density: list[float]) -> list[dict]:
    """Contiguous runs of one state (FUSED / DIFFUSE) with their bars and mean raw density, oldest first."""
    out: list[dict] = []
    for d, s, v in zip(dates, state, density, strict=True):
        name = "FUSED" if s else "DIFFUSE"
        if out and out[-1]["state"] == name:
            out[-1]["end"] = d
            out[-1]["bars"] += 1
            out[-1]["_sum"] += v
        else:
            out.append({"state": name, "start": d, "end": d, "bars": 1, "_sum": v})
    for e in out:
        e["mean_density"] = e.pop("_sum") / e["bars"]
    return out


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    labels = params.get("labels") or {}
    title = "CORR REGIME"
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    win, edge = int(params["win"]), float(params["edge"])
    progress(0.1, "loading bars")
    data = cm.load(params)
    frames = {}
    for sym in sorted(params["symbols"]):
        days, px = cm.series((data.get("bars") or {}).get(sym))
        if days.size < 2:
            return cm.not_runnable(title, f"NO DAILY BARS FOR {sym}", labels)
        frames[sym] = pd.DataFrame({"close": px}, index=pd.to_datetime(days * 86400, unit="s"))
    try:
        returns = _aligned_returns(frames)
    except ValueError:
        return cm.not_runnable(title, "NO DAYS COMMON TO ALL SYMBOLS", labels)
    if len(returns) < win + 1:
        return cm.not_runnable(title, f"ONLY {len(returns)} COMMON RETURNS FOR A {win}-BAR WINDOW", labels)
    progress(0.3, "rolling correlation")
    dens = compute_edge_density(returns, corr_window=win, edge_threshold=edge)
    reg = detect_regimes(dens, smooth_window=SMOOTH, enter_threshold=ENTER, exit_threshold=EXIT).dropna(subset=["density"])
    if reg.empty:
        return cm.not_runnable(title, "THE CORRELATION WINDOW IS NEVER FULLY DEFINED (A CONSTANT SERIES?)", labels)
    progress(0.9, "episodes")
    dates = [d.strftime("%Y-%m-%d") for d in reg.index]
    raw = [float(v) for v in reg["density"]]
    state = [int(v) for v in reg["fused"]]
    eps = episodes(dates, state, raw)
    now = eps[-1]["state"]
    last, smooth = raw[-1], float(reg["smoothed"].iloc[-1])
    x = cm.year(reg.index.to_numpy().astype("datetime64[D]").astype(np.int64))
    pts = lambda ys: [[round(float(a), 4), round(float(b), 6)] for a, b in zip(x, ys, strict=True)]
    flat = lambda v: [[round(float(x[0]), 4), v], [round(float(x[-1]), 4), v]]
    chart = {"id": "density", "title": f"EDGE DENSITY ({win}-BAR |CORR| >= {edge:g}) AND THRESHOLDS", "xlabel": "YEAR", "ylabel": "EDGE DENSITY",
             "series": [{"name": "DENSITY", "points": pts(raw)}, {"name": f"SMOOTHED ({SMOOTH})", "points": pts(reg["smoothed"])},
                        {"name": f"ENTER FUSED {ENTER:g}", "points": flat(ENTER), "dash": True},
                        {"name": f"EXIT FUSED {EXIT:g}", "points": flat(EXIT), "dash": True}]}
    cols = [col("state", "STATE"), col("start", "START", "date"), col("end", "END", "date"), col("bars", "BARS", "int"),
            col("mean_density", "MEAN DENSITY", "num")]
    n = returns.shape[1]
    heads = [head("STATE", now), head("EDGE DENSITY", f"{last:.3f}", last), head("SMOOTHED", f"{smooth:.3f}", smooth),
             head("SYMBOLS", str(n), n), head("WINDOW / EDGE", f"{win} BARS / |CORR| >= {edge:g}"),
             head("SPAN", f"{dates[0]} TO {dates[-1]}"), head("EPISODES", str(len(eps)), len(eps))]
    notes = [
        f"EDGE DENSITY = SHARE OF SYMBOL PAIRS WITH |CORRELATION| >= {edge:g} OVER THE LAST {win} DAILY RETURNS; {n * (n - 1) // 2} PAIRS",
        f"FUSED FROM A {SMOOTH}-BAR SMOOTHED DENSITY OF {ENTER:g}, DIFFUSE AGAIN AT {EXIT:g} (HYSTERESIS: NO CHATTER IN BETWEEN)",
        f"THE FIRST {win - 1} RETURNS ARE WARM-UP AND NOT SHOWN. DESCRIPTIVE RISK CONTEXT, NOT A TRADING SIGNAL",
    ]
    notes += cm.data_notes(labels)
    out = payload(None, title, heads, [section("episodes", "EPISODES", cols, eps, "CONTIGUOUS RUNS OF ONE STATE, OLDEST FIRST")], notes,
                  status="RUNNABLE", charts=[chart])
    progress(1.0, "done")
    return cm.envelope(out, labels)
