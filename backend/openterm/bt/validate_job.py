"""The `bt.mc` and `bt.wf` jobs, run inside a job worker on a stored run's trades and equity curve.

`bt.mc` = Vibe's Monte Carlo trade-order permutation test plus the bootstrap Sharpe confidence interval;
`bt.wf` = Vibe's walk-forward analysis. The server copies the stored run into the job params, so a worker never
reads the database or the network.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from .job import HEADLINE


def plain(obj):
    """JSON-ready copy: numpy scalars and arrays become Python values, non-finite floats become None."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [plain(v) for v in obj]
    if hasattr(obj, "tolist"):
        return plain(obj.tolist())
    if isinstance(obj, bool | str) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    try:
        f = float(obj)
    except (TypeError, ValueError):
        return str(obj)
    return f if math.isfinite(f) else None


def _inputs(params: dict):
    import pandas as pd

    from .models import TradeRecord

    equity = pd.Series([float(v) for _, v in params["equity"]],
                       index=pd.to_datetime([int(t) for t, _ in params["equity"]], unit="s"))
    trades = [TradeRecord(
        symbol=t["symbol"], direction=int(t["direction"]), entry_price=float(t["entry_price"] or 0.0),
        exit_price=float(t["exit_price"] or 0.0), entry_time=pd.Timestamp(t["entry_time"]), exit_time=pd.Timestamp(t["exit_time"]),
        size=float(t["size"]), leverage=1.0, pnl=float(t["pnl"] or 0.0), pnl_pct=float(t["pnl_pct"] or 0.0),
        exit_reason=t["exit_reason"], holding_bars=float(t["holding_bars"] or 0.0), commission=float(t["commission"] or 0.0),
    ) for t in params["trades"]]
    return equity, trades


def _labels(params: dict, note: str) -> dict:
    return {**params.get("labels", {}), "headline": HEADLINE, "validation": note}


def monte_carlo(params: dict, progress: Callable[[float, str], None]) -> dict:
    from . import validation

    progress(0.05, "LOADING RUN")
    equity, trades = _inputs(params)
    cash, bpy = float(params["initial_cash"]), int(params["bars_per_year"])
    progress(0.15, "MONTE CARLO")
    mc = validation.monte_carlo_test(trades, cash, n_simulations=params["n_simulations"], seed=params["seed"],
                                     bars_per_year=bpy)
    if "error" in mc:
        raise ValueError(str(mc["error"]).upper())
    progress(0.7, "BOOTSTRAP")
    boot = validation.bootstrap_sharpe_ci(equity, n_bootstrap=params["n_bootstrap"], confidence=params["confidence"],
                                          bars_per_year=bpy, seed=params["seed"], initial_capital=cash)
    progress(0.95, "WRITING RESULT")
    note = (f"TRADE-ORDER PERMUTATION x{params['n_simulations']}, BOOTSTRAP x{params['n_bootstrap']} "
            f"AT {params['confidence']:.0%}, SEED {params['seed']}")
    return plain({**mc, "bootstrap": boot, "run_id": params["run_id"], "labels": _labels(params, note)})


def walk_forward(params: dict, progress: Callable[[float, str], None]) -> dict:
    from . import validation

    progress(0.05, "LOADING RUN")
    equity, trades = _inputs(params)
    progress(0.3, "WALK-FORWARD")
    wf = validation.walk_forward_analysis(equity, trades, n_windows=params["n_windows"],
                                          bars_per_year=int(params["bars_per_year"]))
    if "error" in wf:
        raise ValueError(str(wf["error"]).upper())
    progress(0.95, "WRITING RESULT")
    return plain({**wf, "run_id": params["run_id"],
                  "labels": _labels(params, f"{params['n_windows']} EQUAL WINDOWS, NO RE-FITTING")})
