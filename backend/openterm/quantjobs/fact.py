"""FACT (spec decision G): daily OLS of excess returns on the Fama-French 5 factors + momentum (Ken French library).

Inner join of the daily bars (a symbol, or a portfolio's weighted return) with the factor days; alpha annualised (x252), Newey-West t-stats
(5 lags, Bartlett weights), R2, residual vol and each factor's contribution to the (annualised) excess return.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from ..research.table import col, head, payload, section
from . import common as cm

FACTORS = ("MKT-RF", "SMB", "HML", "RMW", "CMA", "MOM")
NW_LAGS = 5
MIN_DAYS = 30
NON_US_NOTE = "LONG-ONLY US EQUITY FACTORS; NON-US NAMES LOAD ON THEM LOOSELY"


def ymd(v) -> str:
    s = str(int(v))
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def ols(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(beta, residuals) of y on x (x carries its own constant column)."""
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    return beta, y - x @ beta


def newey_west_se(x: np.ndarray, resid: np.ndarray, lags: int = NW_LAGS) -> np.ndarray:
    """Heteroskedasticity- and autocorrelation-consistent standard errors (Newey-West, Bartlett kernel)."""
    xe = x * resid[:, None]
    s = xe.T @ xe
    for lag in range(1, min(lags, len(resid) - 1) + 1):
        g = xe[lag:].T @ xe[:-lag]
        s += (1.0 - lag / (lags + 1.0)) * (g + g.T)
    bread = np.linalg.inv(x.T @ x)
    return np.sqrt(np.clip(np.diag(bread @ s @ bread), 0.0, None))


def _returns(params: dict, data: dict, title: str, labels: dict):
    """(day numbers, return series, problem) for the symbol or the portfolio."""
    pos = params.get("positions")
    if not pos:
        sym = params["symbol"]
        days, px = cm.series((data.get("bars") or {}).get(sym))
        if days.size < 2:
            return None, None, f"NO DAILY BARS FOR {sym}"
        return days[1:], px[1:] / px[:-1] - 1.0, None
    syms = [p["symbol"] for p in pos]
    cols = {s: cm.series(data["bars"].get(s)) for s in syms}
    short = [s for s in syms if cols[s][0].size < 2]
    if short:
        return None, None, f"NO DAILY BARS FOR {', '.join(short)}"
    days, px = cm.align(cols)
    if days.size < 2:
        return None, None, "NO DAYS COMMON TO ALL HOLDINGS"
    fx = data.get("fx") or {}
    # value every holding on the last day all series share (as RISK does), not each series' own last close (audit B-1)
    mv = np.array([p["qty"] * px[-1, i] * fx.get(p.get("ccy") or "", 1.0) for i, p in enumerate(pos)])
    value = float(mv.sum())
    if not value > 0:
        return None, None, "NET PORTFOLIO VALUE IS NOT POSITIVE"
    return days[1:], (px[1:] / px[:-1] - 1.0) @ (mv / value), None


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    labels = params.get("labels") or {}
    title = f"FACT {params.get('name') or params.get('symbol') or ''}".strip()
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    progress(0.1, "loading bars and factors")
    data = cm.load(params)
    fac = data["factors"]
    fdates = np.asarray(fac["dates"], dtype=np.int64)
    ends = ymd(fdates[-1])
    days, rets, problem = _returns(params, data, title, labels)
    if problem:
        return cm.not_runnable(title, problem, labels)
    keys = np.array([int(cm.iso(int(d)).replace("-", "")) for d in days], dtype=np.int64)
    fi = np.searchsorted(fdates, keys)
    ok = (fi < fdates.size) & (fdates[np.minimum(fi, fdates.size - 1)] == keys)
    if int(ok.sum()) < MIN_DAYS:
        return cm.not_runnable(title, f"ONLY {int(ok.sum())} DAYS COMMON TO THE BARS AND THE FACTOR DATA (NEED {MIN_DAYS}); FACTOR DATA ENDS {ends}", labels)
    fi, rets, keys = fi[ok], rets[ok], keys[ok]
    progress(0.4, "regression")
    f = np.column_stack([np.asarray(fac["cols"][n], dtype=float)[fi] / 100.0 for n in FACTORS])
    rf = np.asarray(fac["cols"]["RF"], dtype=float)[fi] / 100.0
    y = rets - rf
    x = np.column_stack([np.ones(y.size), f])
    beta, res = ols(x, y)
    se = newey_west_se(x, res)
    t = np.where(se > 0, beta / np.where(se > 0, se, 1.0), np.nan)
    n, k = x.shape
    r2 = 1.0 - res.var() / y.var() if y.var() > 0 else float("nan")
    resid_vol = float(res.std(ddof=k) * math.sqrt(252))
    alpha_ann = float(beta[0] * 252)
    mean_f = f.mean(axis=0) * 252
    contrib = beta[1:] * mean_f
    d0, d1 = ymd(keys[0]), ymd(keys[-1])
    rows = [{"factor": name, "beta": cm.fin(beta[i + 1]), "t": cm.fin(t[i + 1]), "premium": cm.fin(mean_f[i]), "contrib": cm.fin(contrib[i])}
            for i, name in enumerate(FACTORS)]
    rows.append({"factor": "ALPHA (ANN)", "beta": None, "t": cm.fin(t[0]), "premium": None, "contrib": cm.fin(alpha_ann)})
    cols = [col("factor", "FACTOR"), col("beta", "BETA", "num4"), col("t", "T (NW5)", "num"), col("premium", "FACTOR RET (ANN)", "pct"),
            col("contrib", "CONTRIB (ANN)", "pct")]
    notes = [
        "FACTOR REGRESSION, NOT A FORECAST: DAILY EXCESS RETURN (RF FROM THE LIBRARY) ON MKT-RF SMB HML RMW CMA MOM",
        f"T-STATS NEWEY-WEST {NW_LAGS} LAGS; ALPHA AND CONTRIBUTIONS ANNUALISED x252; CONTRIB = BETA x MEAN FACTOR RETURN",
        f"FACTOR DATA ENDS {ends}: THE LIBRARY LAGS ABOUT TWO MONTHS, SO THE REGRESSION WINDOW ENDS THERE",
    ]
    if params.get("non_us"):
        notes.append(NON_US_NOTE)
    if params.get("mixed_ccy"):
        notes.append("MIXED CURRENCIES: HOLDINGS VALUED AT THE LAST FX RATE; RETURNS ARE IN EACH LOCAL CURRENCY")
    notes += cm.data_notes({**labels, "sources": [s for s in labels.get("sources", []) if s.get("symbol") != "KEN FRENCH"]})
    if params.get("factor_label"):
        notes.append(str(params["factor_label"]))
    notes.append("FACTORS: KENNETH R. FRENCH DATA LIBRARY (DARTMOUTH TUCK)")
    head_rows = [
        head("ALPHA (ANN)", f"{alpha_ann * 100:+.2f}%", alpha_ann),
        head("ALPHA T", f"{t[0]:.2f}" if np.isfinite(t[0]) else None, cm.fin(t[0])),
        head("R2", f"{r2:.3f}" if np.isfinite(r2) else None, cm.fin(r2)),
        head("RESIDUAL VOL (ANN)", f"{resid_vol * 100:.2f}%", resid_vol),
        head("OBSERVATIONS", str(n), n),
        head("WINDOW", f"{d0} TO {d1}"),
        head("FACTOR DATA ENDS", ends),
    ]
    out = payload(params.get("symbol") or params.get("name"), title, head_rows,
                  [section("loadings", "FACTOR LOADINGS", cols, rows, "BETA ON DAILY EXCESS RETURNS; T: NEWEY-WEST, 5 LAGS")],
                  notes, status="RUNNABLE")
    progress(1.0, "done")
    return cm.envelope(out, labels)
