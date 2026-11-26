"""The `bt.opt` job (Phase 26): run one strategy template over many parameter sets, then score the search.

Inside a job worker, like `bt.run`: the server already fetched the bars into a content-addressed data file. Every parameter
set goes through the SAME engine, costs and stop/target rules as a single BT run (`job.signals_for` + `engine.backtest`), one
after the other (about 0.1 s per run over 10 years of daily bars). Only small numbers come back: each run's metrics, plus the
guards computed here from the returns matrix (one column of bar returns per run), which never leaves the worker.
"""

from __future__ import annotations

import math
from collections.abc import Callable

# Metrics kept per run (the table's columns); everything else of a run is dropped to keep the result small.
RUN_METRICS = ("sharpe", "sortino", "calmar", "annual_return", "total_return", "max_drawdown", "profit_factor",
               "win_rate", "trade_count", "final_value")
def _fitness(metrics: dict, fit) -> float:
    """The run's fitness under the compiled FIT= formula (`fitexpr.Fit`); NaN when it cannot be computed."""
    return fit.from_metrics(metrics)


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    import numpy as np

    from . import fitexpr, limits, optspace, overfit
    from .engine import backtest
    from .job import _epoch, _num, load_data, scalar_metrics, signals_for, stops_config

    progress(0.02, "LOADING DATA")
    payload, data_map, adjusted = load_data(params)
    parts, space = optspace.parse(params["template"])
    method, fit_text, seed = params["method"], params["fit"], int(params["seed"])
    fit = fitexpr.parse(fit_text)  # FIT= is SHARPE, SORTINO, ... or a formula such as SHARPE-2*DD
    is_code, short = params["kind"] == "code", bool(params.get("short"))
    stops_cfg = stops_config(params, payload)
    bpy = int(params["bars_per_year"])
    cash = float(params["config"].get("initial_cash", 100_000))

    rows: list[dict] = []
    columns: dict[tuple[int, ...], np.ndarray] = {}
    times: list[int] = []
    budget = max(1, int(params["budget"]))

    def score(idx: tuple[int, ...]) -> float:
        text = optspace.render(parts, space, idx)
        row: dict = {"i": list(idx), "values": [p.values[i] for p, i in zip(space, idx, strict=True)]}
        try:
            sig = signals_for(None if is_code else text, text if is_code else None, data_map, short)
            res = backtest(data_map, sig, params["config"], engine=params["engine"], bars_per_year=bpy, stops=stops_cfg)
            m = scalar_metrics(res.metrics)
            row["metrics"] = {k: _num(m.get(k)) for k in RUN_METRICS}
            eq = res.equity
            if not times:
                times.extend(_epoch(ts) for ts in eq.index)
            if len(eq) == len(times):  # every run shares the bar index; a mismatch would misalign the guards
                columns[idx] = eq.pct_change(fill_method=None).fillna(0.0).to_numpy(dtype=float)
            row["fitness"] = _num(_fitness(row["metrics"], fit))
        except Exception as e:  # noqa: BLE001 - one bad parameter set is reported on its row, the search goes on
            row["error"] = str(e)[:200]
            row["fitness"] = None
        rows.append(row)
        progress(0.05 + 0.8 * min(1.0, len(rows) / budget), f"RUN {len(rows)} OF ~{budget}")
        return math.nan if row["fitness"] is None else float(row["fitness"])

    with limits.memory_cap(int(params.get("memory_limit_mb", 1024))):
        if method == "GA":
            optspace.genetic(space, score, int(params["pop"]), int(params["gen"]), seed)
        else:
            plan = optspace.grid(space) if method == "GRID" else optspace.random_sample(space, int(params["n"]), seed)
            for idx in plan:
                score(idx)

    progress(0.88, "OVERFITTING CHECKS")
    ok = [k for k, r in enumerate(rows) if r.get("fitness") is not None]
    best = max(ok, key=lambda k: rows[k]["fitness"]) if ok else None
    order = [tuple(r["i"]) for r in rows]
    have = [k for k, idx in enumerate(order) if idx in columns]
    matrix = np.column_stack([columns[order[k]] for k in have]) if have else np.zeros((0, 0))

    guards: dict = {"trials": len(rows), "failed": sum(1 for r in rows if "error" in r),
                    "no_fitness": sum(1 for r in rows if "error" not in r and r.get("fitness") is None),
                    "edge": [], "plateau": None, "pbo": None, "dsr": None}
    if best is not None:
        bidx = order[best]
        guards["edge"] = optspace.on_edge(bidx, space)
        by_idx = {idx: rows[k].get("fitness") for k, idx in enumerate(order)}
        near = [by_idx[n] for n in optspace.neighbours(bidx, space) if by_idx.get(n) is not None]
        guards["plateau"] = {"neighbours": len(near), "mean": float(np.mean(near)) if near else None,
                             "best": rows[best]["fitness"]}
        if matrix.size:
            guards["pbo"] = overfit.pbo_cscv(matrix)
            if bidx in columns:
                sharpes = overfit._sharpe_cols(matrix)
                guards["dsr"] = overfit.deflated(columns[bidx], sharpes, len(have))
    front = overfit.efficient([((r.get("metrics") or {}).get("annual_return"), (r.get("metrics") or {}).get("max_drawdown"))
                               for r in rows])
    for k in front:
        rows[k]["front"] = True

    wf = None
    if params.get("wf") and matrix.size:
        progress(0.94, "WALK-FORWARD")
        wf = overfit.walk_forward(matrix, times, int(params["wf"]), bool(params.get("anchored")), fit_text, bpy, cash)
        if wf is not None:
            for w in wf["windows"]:  # a column number means nothing to the user: name the parameter set
                w["values"] = rows[have[w.pop("best")]]["values"]

    labels = dict(params["labels"])
    labels["prices"] = "ADJ" if adjusted else "RAW"
    if params.get("stops"):
        st = params["stops"]
        labels["stops"] = (f"STOP {st.get('stop') or '-'}% TARGET {st.get('target') or '-'}% · "
                           + ("FILL=INTRABAR" if st.get("intrabar") else "STOP FIRST WHEN A BAR REACHES BOTH")
                           + (f" · {payload['intraday_note']}" if payload.get("intraday_note") else ""))
    if wf is not None:
        labels["wf"] = "WINDOWS SLICED FROM EACH PARAMETER SET'S FULL-HISTORY RUN (POSITIONS CARRY ACROSS WINDOW EDGES)"
    return {
        "opt_id": params["opt_id"], "template": params["template"], "shown": optspace.shown(parts, space),
        "kind": params["kind"], "method": method, "fit": fit.text, "seed": seed, "symbols": params["meta"]["symbols"],
        "interval": params["meta"]["interval"], "range": params["meta"]["range"], "strategy": params["meta"].get("strategy"),
        "params": [{"name": p.name, "values": list(p.values), "where": p.where} for p in space],
        "runs": rows, "best": best, "guards": guards, "wf": wf, "bars": len(times), "labels": labels,
    }
