"""PORT OPT (spec decision E): a long-only optimizer PREVIEW. Methods are Vibe's optimizers (`_build_context` + `_calc_weights` on one window);
a CAP is a re-solve with bounds for the SLSQP methods (objectives copied from Vibe below) and clip-and-redistribute for EQVOL and HRP.
Nothing here edits a portfolio or places an order.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from ..research.table import col, head, payload, section
from . import common as cm

METHODS = ("EQVOL", "RP", "MV", "MAXDIV", "HRP", "TURN")
MIN_WINDOW = 30


def clip_redistribute(w: np.ndarray, cap: float) -> np.ndarray:
    """Clip every weight at `cap` and give the excess to the names still below it, pro rata, until none is above."""
    w = w.astype(float).copy()
    for _ in range(len(w) + 1):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        free = ~over & (w < cap - 1e-12)
        if not free.any():
            break
        share = w[free] if w[free].sum() > 1e-15 else np.ones(int(free.sum()))
        w[free] += excess * share / share.sum()
    return w


def solve_capped(method: str, mu: np.ndarray, cov: np.ndarray, cap: float, rf_daily: float) -> np.ndarray | None:
    """Vibe's objective for RP / MV / MAXDIV (copied from backtest/optimizers), re-solved with bounds (0, cap)."""
    from scipy.optimize import minimize

    n = cov.shape[0]
    vols = np.sqrt(np.diag(cov))

    if method == "RP":
        def obj(w: np.ndarray) -> float:
            variance = float(w @ cov @ w)
            if not np.isfinite(variance) or variance <= 1e-18:
                return 1e12
            return float(np.sum((w * (cov @ w) - variance / n) ** 2) / variance**2)
        opts = {"maxiter": 200, "ftol": 1e-12}
    elif method == "MV":
        def obj(w: np.ndarray) -> float:
            pv = math.sqrt(max(float(w @ cov @ w), 0.0))
            return 0.0 if pv < 1e-12 else -(float(w @ mu) - rf_daily) / pv
        opts = {"maxiter": 200, "ftol": 1e-10}
    else:  # MAXDIV
        def obj(w: np.ndarray) -> float:
            pv = math.sqrt(max(float(w @ cov @ w), 0.0))
            return 0.0 if pv < 1e-12 else -float(w @ vols) / pv
        opts = {"maxiter": 200, "ftol": 1e-10}
    x0 = clip_redistribute(np.full(n, 1.0 / n), cap)
    res = minimize(obj, x0, method="SLSQP", bounds=[(0.0, cap)] * n, constraints={"type": "eq", "fun": lambda w: w.sum() - 1.0}, options=opts)
    if not (res.success and np.isfinite(res.x).all()):
        return None
    w = np.maximum(res.x, 0.0)
    return clip_redistribute(w / w.sum(), cap)


def _stats(w: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float) -> dict[str, float | None]:
    var = float(w @ cov @ w)
    vol = math.sqrt(max(var, 0.0)) * math.sqrt(252)
    ret = float(w @ mu) * 252
    return {"VOL": vol, "EXP RETURN": ret, "SHARPE": (ret - rf) / vol if vol > 0 else None, "MAX WEIGHT": float(np.max(np.abs(w))),
            "EFFECTIVE N": 1.0 / float((w**2).sum())}


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    import pandas as pd

    from ..quantlib import portfolio as qp
    from ..quantlib.optimizers.equal_volatility import EqualVolatilityOptimizer
    from ..quantlib.optimizers.max_diversification import MaxDiversificationOptimizer
    from ..quantlib.optimizers.mean_variance import MeanVarianceOptimizer
    from ..quantlib.optimizers.risk_parity import RiskParityOptimizer
    from ..quantlib.optimizers.turnover_aware import TurnoverAwareOptimizer

    labels = params.get("labels") or {}
    title = f"PORT OPT {params.get('name', '')}".strip()
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    progress(0.1, "loading bars")
    data = cm.load(params)
    pos = params["positions"]
    syms = [p["symbol"] for p in pos]
    method, cap, tc = params["method"], params.get("cap"), float(params.get("tc", 0.0))
    rf = float(params.get("rf", 0.0))
    if len(syms) < 2:
        return cm.not_runnable(title, "OPT NEEDS AT LEAST 2 HOLDINGS", labels)
    neg = [p["symbol"] for p in pos if p["qty"] < 0]
    if neg:
        return cm.not_runnable(title, f"OPT IS LONG-ONLY: SHORT POSITIONS {', '.join(neg)}", labels)
    cols = {s: cm.series(data["bars"].get(s)) for s in syms}
    short = [s for s in syms if cols[s][0].size < 2]
    if short:
        return cm.not_runnable(title, f"NO DAILY BARS FOR {', '.join(short)}", labels)
    _, px = cm.align(cols)
    rets = px[1:] / px[:-1] - 1.0
    lb = min(int(params["lookback"]), rets.shape[0])
    if lb < MIN_WINDOW:
        return cm.not_runnable(title, f"ONLY {rets.shape[0]} DAYS COMMON TO ALL HOLDINGS (NEED {MIN_WINDOW})", labels)
    win = rets[-lb:]
    df = pd.DataFrame(win, columns=syms)
    n = len(syms)
    fx = data.get("fx") or {}
    # value every holding on the last day all series share (as RISK does), not each series' own last close (audit B-1)
    price = px[-1].astype(float)
    rate = np.array([fx.get(p.get("ccy") or "", 1.0) for p in pos])
    mv = np.array([p["qty"] for p in pos]) * price * rate
    total = float(mv.sum())
    if not total > 0:
        return cm.not_runnable(title, "PORTFOLIO VALUE IS NOT POSITIVE", labels)
    w_now = mv / total
    mu, cov = win.mean(axis=0), np.cov(win, rowvar=False).reshape(n, n)
    if np.any(np.diag(cov) < 1e-14):
        return cm.not_runnable(title, "A HOLDING HAS NO VARIANCE IN THE WINDOW", labels)
    if cap is not None and cap * n < 1.0 - 1e-9:
        return cm.not_runnable(title, f"CAP {cap:g} IS BELOW 1/N ({1 / n:.4f}) FOR {n} HOLDINGS", labels)
    progress(0.4, f"optimising ({method})")

    cap_note = None
    rf_daily = rf / 252.0
    if method == "EQVOL":
        w = EqualVolatilityOptimizer(lookback=lb)._calc_weights({"vols": pd.Series(np.sqrt(np.diag(cov)), index=syms)})
        w = np.asarray(w, dtype=float)
        if cap is not None:
            w = clip_redistribute(w, cap)
            cap_note = f"CAP {cap:g} BY CLIPPING, NOT RE-OPTIMISED"
    elif method == "HRP":
        w = np.asarray(qp.hierarchical_risk_parity(pd.DataFrame(cov, index=syms, columns=syms)), dtype=float)
        if cap is not None:
            w = clip_redistribute(w, cap)
            cap_note = f"CAP {cap:g} BY CLIPPING, NOT RE-OPTIMISED"
    elif method == "TURN":
        opt = TurnoverAwareOptimizer(lookback=lb, risk_aversion=1.0, turnover_penalty=tc, max_per_name=cap)
        opt._prev = {s: float(w_now[i]) for i, s in enumerate(syms)}
        ctx = opt._build_context(df, syms)
        ctx["position_signs"] = np.ones(n)
        try:
            w = np.asarray(opt._calc_weights(ctx), dtype=float)
        except (RuntimeError, ValueError) as e:
            return cm.not_runnable(title, f"TURN SOLVER FAILED: {e}", labels)
        if cap is not None:
            cap_note = f"CAP {cap:g} AS A BOUND IN THE SOLVE"
    else:
        cls = {"RP": RiskParityOptimizer, "MV": MeanVarianceOptimizer, "MAXDIV": MaxDiversificationOptimizer}[method]
        kw = {"risk_free": rf_daily} if method == "MV" else {}
        if cap is None:
            opt = cls(lookback=lb, **kw)
            ctx = opt._build_context(df, syms)
            w = np.asarray(opt._calc_weights(ctx), dtype=float)
        else:
            w = solve_capped(method, mu, cov, cap, rf_daily)
            if w is None:
                return cm.not_runnable(title, f"{method} SOLVER DID NOT CONVERGE WITH CAP {cap:g}", labels)
            cap_note = f"CAP {cap:g} RE-SOLVED WITH BOUNDS"
    w = np.maximum(w, 0.0)
    w = w / w.sum()

    progress(0.8, "trades")
    delta = w - w_now
    shares = [round(delta[i] * total / (price[i] * rate[i])) for i in range(n)]
    trade_rows = [{"symbol": s, "qty_now": pos[i]["qty"], "w_now": float(w_now[i]), "w_target": float(w[i]), "w_delta": float(delta[i]),
                   "shares": shares[i], "cash": float(shares[i] * price[i]), "price": float(price[i]),
                   "ccy": pos[i].get("ccy")} for i, s in enumerate(syms)]  # ccy is not a column: A (save .OPT) keeps it
    trade_rows.sort(key=lambda r: -abs(r["w_delta"]))
    trades = section("trades", "PROPOSED TRADES", [
        col("symbol", "SYMBOL", "text", 12), col("qty_now", "QTY NOW", "num"), col("w_now", "WEIGHT NOW", "pct"), col("w_target", "TARGET", "pct"),
        col("w_delta", "CHANGE", "pct"), col("shares", "SHARES", "int"), col("cash", "CASH", "money"), col("price", "LAST CLOSE", "price")],
        trade_rows, "WHOLE SHARES AT THE LAST CLOSE, POSITIVE = BUY; CASH IN EACH NAME'S OWN CURRENCY; A PREVIEW, NO ORDER IS PLACED")

    before, after = _stats(w_now, mu, cov, rf), _stats(w, mu, cov, rf)
    before["TURNOVER"], after["TURNOVER"] = 0.0, float(0.5 * np.abs(delta).sum())
    cmp_rows = [{"metric": k, "before": cm.fin(before[k]), "after": cm.fin(after[k])}
                for k in ("VOL", "EXP RETURN", "SHARPE", "MAX WEIGHT", "EFFECTIVE N", "TURNOVER")]
    compare = section("compare", "BEFORE AND AFTER", [col("metric", "METRIC", "text", 14), col("before", "BEFORE", "num4"), col("after", "AFTER", "num4")],
                      cmp_rows, f"VOL AND EXP RETURN ARE ANNUALISED FROM THE {lb}-DAY WINDOW MEAN AND COVARIANCE; SHARPE AT RF {rf:g}; TURNOVER IS ONE-WAY")

    def rc(x: np.ndarray) -> np.ndarray:
        v = float(x @ cov @ x)
        return x * (cov @ x) / v if v > 0 else np.zeros(n)
    rc_now, rc_new = rc(w_now), rc(w)
    risk_rows = [{"symbol": s, "vol": cm.fin(math.sqrt(cov[i, i]) * math.sqrt(252)), "rc_now": cm.fin(rc_now[i]), "rc_target": cm.fin(rc_new[i])}
                 for i, s in enumerate(syms)]
    risk = section("risk", "RISK CONTRIBUTION", [col("symbol", "SYMBOL", "text", 12), col("vol", "VOL (ANN)", "pct"),
                                                 col("rc_now", "SHARE NOW", "pct"), col("rc_target", "SHARE TARGET", "pct")], risk_rows,
                   "SHARE OF PORTFOLIO VARIANCE, ADDS TO 100%")
    notes = [f"ESTIMATED FROM {lb} DAYS OF HISTORY, NOT A FORECAST",
             "PREVIEW ONLY: THE PORTFOLIO IS NOT EDITED AND NO ORDER IS PLACED; COSTS AND TAXES ARE NOT MODELLED",
             f"{method}: LONG-ONLY, FULLY INVESTED, WEIGHTS FROM THE LAST {lb} DAILY RETURNS COMMON TO ALL HOLDINGS", *cm.data_notes(labels)]
    if cap_note:
        notes.append(cap_note)
    if method == "TURN":
        notes.append(f"TURN: MEAN-VARIANCE UTILITY (RISK AVERSION 1 ON DAILY VARIANCE) WITH TC={tc:g} PER UNIT OF TURNOVER AGAINST THE CURRENT WEIGHTS")
    if params.get("mixed_ccy"):
        notes.append("LOCAL-CURRENCY RETURNS, FX RISK NOT INCLUDED")
    heads = [head("METHOD", method), head("LOOKBACK", f"{lb} DAYS", lb), head("VALUE", f"{total:,.0f} {params.get('base', '')}".strip(), total),
             head("MAX WEIGHT", f"{after['MAX WEIGHT'] * 100:.1f}%", after["MAX WEIGHT"]), head("TURNOVER", f"{after['TURNOVER'] * 100:.1f}%", after["TURNOVER"]),
             head("NOT A FORECAST", f"ESTIMATED FROM {lb} DAYS")]
    progress(1.0, "done")
    return cm.envelope(payload(None, title, heads, [trades, compare, risk], notes), labels)
