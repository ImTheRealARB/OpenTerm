"""RISK (spec decision D): VaR / ES (historical, normal, EVT), beta, drawdown, contributions, stress replays, VaR backtest.

Today's weights are held constant over the window (labelled). The stress replays are ours; everything else calls the ported quantlib.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from ..research.table import col, head, payload, section
from . import common as cm

STRESS = [("2008", "2008 CRISIS", "2008-09-12", "2009-03-09"), ("2020", "2020 CRASH", "2020-02-19", "2020-03-23"),
          ("2022", "2022 BEAR", "2022-01-03", "2022-10-12")]
MIN_DAYS = 31


def _gpd_var(port: np.ndarray, conf: float, hor: int, fit: dict) -> tuple[float | None, float | None]:
    """EVT (peaks over threshold) VaR and ES of the one-day loss at `conf`, scaled by sqrt(hor). Valid at or beyond the 95% threshold."""
    n, nu = port.size, fit["n_exceedances"]
    xi, sigma, u = fit["shape_xi"], fit["scale_sigma"], -fit["threshold"]
    ratio = n / nu * (1.0 - conf)
    if conf < 0.95 - 1e-12 or ratio <= 0 or sigma <= 0:
        return None, None
    var = u - sigma * math.log(ratio) if abs(xi) < 1e-9 else u + sigma / xi * (ratio ** (-xi) - 1.0)
    es = (var + sigma - xi * u) / (1.0 - xi) if xi < 0.95 else None
    s = math.sqrt(hor)
    return var * s, (es * s if es is not None else None)


def _pair_returns(days: np.ndarray, ret: np.ndarray, bench: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray] | None:
    """Portfolio returns (indexed by their end day) paired with the benchmark's own daily returns on the same end day."""
    bd, bc = bench
    if bd.size < 3:
        return None
    br = bc[1:] / bc[:-1] - 1.0
    ends = bd[1:]
    common, i_p, i_b = np.intersect1d(days, ends, return_indices=True)
    if common.size < 30:
        return None
    return ret[i_p] if ret.ndim == 1 else ret[i_p, :], br[i_b]


def _beta(x: np.ndarray, b: np.ndarray) -> tuple[float | None, float | None]:
    vb = float(b.var(ddof=1))
    if vb <= 0:
        return None, None
    cov = float(np.cov(x, b)[0, 1])
    sx = float(x.std(ddof=1))
    return cov / vb, (cov / math.sqrt(vb * sx * sx) if sx > 0 else None)


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    from scipy.stats import norm

    from ..quantlib import risk as qr
    from ..quantlib import var_backtest as vb

    labels = params.get("labels") or {}
    title = f"RISK {params.get('name', '')}".strip()
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    progress(0.05, "loading bars")
    data = cm.load(params)
    pos = params["positions"]
    syms = [p["symbol"] for p in pos]
    cols = {s: cm.series(data["bars"].get(s)) for s in syms}
    short = [s for s in syms if cols[s][0].size < 2]
    if short:
        return cm.not_runnable(title, f"NO DAILY BARS FOR {', '.join(short)}", labels)
    days, px = cm.align(cols)
    if days.size < MIN_DAYS:
        return cm.not_runnable(title, f"ONLY {days.size} DAYS COMMON TO ALL HOLDINGS (NEED {MIN_DAYS})", labels)
    fx = data.get("fx") or {}
    mv = np.array([p["qty"] * cols[p["symbol"]][1][-1] * fx.get(p.get("ccy") or "", 1.0) for p in pos])
    value = float(mv.sum())
    if not value > 0:
        return cm.not_runnable(title, "NET PORTFOLIO VALUE IS NOT POSITIVE", labels)
    w = mv / value
    rets = px[1:] / px[:-1] - 1.0
    rdays = days[1:]
    port = rets @ w
    n = port.size
    conf = float(params.get("conf", 95))
    hor = int(params.get("hor", 1))
    progress(0.25, "var")

    vol = cm.eq_vol(port)
    eq = cm.cum(port)
    dd = cm.drawdown(eq)
    hhi = float((w**2).sum())
    absw = np.sort(np.abs(w))[::-1]
    bench_sym = params.get("bench")
    bench = cm.series(data.get("bench")) if data.get("bench") else None
    pair = _pair_returns(rdays, port, bench) if bench is not None else None
    beta, corr = (None, None)
    if pair is not None:
        beta, corr = _beta(*pair)
        corr = float(np.corrcoef(pair[0], pair[1])[0, 1])

    # --- VAR --------------------------------------------------------------------------------------------------------------------
    levels = sorted({95, 99, round(conf)})
    try:
        fit = qr.fit_gpd_tail(port, 5.0)
        evt_note = f"EVT: GENERALISED PARETO FIT TO THE WORST 5% ({fit['n_exceedances']} DAYS), TAIL {fit['tail_type'].upper()}, SHAPE {fit['shape_xi']:.3f}"
    except ValueError as e:
        fit, evt_note = None, f"EVT NOT FITTED: {e}"
    var_rows = []
    for lv in levels:
        c = lv / 100.0
        hv, hes = qr.historical_var(port, c, hor), qr.historical_cvar(port, c, hor)
        nv = qr.parametric_var(port, c, hor)
        mu, sd = float(port.mean()), float(port.std(ddof=1))
        z = float(norm.ppf(1 - c))
        phi = math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
        nes = (-mu + sd * phi / (1 - c)) * math.sqrt(hor)
        ev, ees = (None, None)
        if fit is not None:
            ev, ees = _gpd_var(port, c, hor, fit)
            if ev is not None and (ees is None or not math.isfinite(ees) or ees < ev):
                ees = hes  # EVT expected shortfall needs shape < 1; fall back to the historical one, said in the notes
        for method, v, es in (("HIST", hv, hes), ("NORMAL", nv, nes), ("EVT", ev, ees)):
            var_rows.append({"method": method, "conf": lv, "hor": hor, "var_pct": cm.fin(v), "var_money": cm.fin(v * value) if v is not None else None,
                             "es_pct": cm.fin(es), "es_money": cm.fin(es * value) if es is not None else None})
    var_sec = section("var", f"VALUE AT RISK, {hor} DAY", [
        col("method", "METHOD", "text", 8), col("conf", "CONF %", "int"), col("hor", "DAYS", "int"), col("var_pct", "VAR", "pct"),
        col("var_money", "VAR MONEY", "money"), col("es_pct", "ES", "pct"), col("es_money", "ES MONEY", "money")], var_rows,
        f"LOSS AS A POSITIVE NUMBER; SQRT-OF-TIME SCALING FOR {hor} DAYS; {evt_note}")
    progress(0.45, "contributions")

    # --- CONTRIB ----------------------------------------------------------------------------------------------------------------
    cov = np.cov(rets, rowvar=False).reshape(len(syms), len(syms))
    pvar = float(w @ cov @ w)
    contrib = w * (cov @ w) / pvar if pvar > 0 else np.zeros(len(w))
    q = np.sort(port)[qr._tail_index(n, 0.95)]
    tail = port <= q
    tail_c = -w * rets[tail].mean(axis=0) if tail.any() else np.zeros(len(w))
    hold_beta = [None] * len(syms)
    if bench is not None:
        paired = _pair_returns(rdays, rets, bench)
        if paired is not None:
            hold_beta = [_beta(paired[0][:, i], paired[1])[0] for i in range(len(syms))]
    ctr_rows = [{"symbol": s, "weight": cm.fin(w[i]), "vol": cm.fin(math.sqrt(cov[i, i]) * math.sqrt(252)), "var_contrib": cm.fin(contrib[i]),
                 "beta": cm.fin(hold_beta[i]), "tail_contrib": cm.fin(tail_c[i])} for i, s in enumerate(syms)]
    ctr_rows.sort(key=lambda r: -abs(r["var_contrib"] or 0))
    ctr_sec = section("contrib", "CONTRIBUTION BY HOLDING", [
        col("symbol", "SYMBOL", "text", 12), col("weight", "WEIGHT", "pct"), col("vol", "VOL (ANN)", "pct"),
        col("var_contrib", "VARIANCE SHARE", "pct"), col("beta", "BETA", "num"), col("tail_contrib", "TAIL CONTRIB", "pct")], ctr_rows,
        "VARIANCE SHARE ADDS TO 100%; TAIL CONTRIB IS THE HISTORICAL 95% EXPECTED-SHORTFALL DECOMPOSITION (ADDS TO ES, ONE DAY)")

    # --- STRESS (own history per holding at today's weights) ---------------------------------------------------------------------
    progress(0.6, "stress replays")
    hist = {s: cm.series((data.get("stress") or {}).get(s)) for s in syms}
    st_rows = []
    for sid, name, start, end in STRESS:
        d0, d1 = cm.day_of(start), cm.day_of(end)
        num = cover = 0.0
        for i, s in enumerate(syms):
            sd, sc = hist[s]
            if sd.size < 2 or sd[0] > d0 or sd[-1] < d1:
                continue
            a, b = cm.asof(sd, sc, d0), cm.asof(sd, sc, d1)
            if a and b:
                cover += w[i]
                num += w[i] * (b / a - 1.0)
        ret = num / cover if cover else None
        st_rows.append({"id": sid, "name": name, "start": start, "end": end, "coverage": cm.fin(cover),
                        "ret": cm.fin(ret), "loss_money": cm.fin(ret * cover * value) if ret is not None else None})
    st_sec = section("stress", "STRESS REPLAYS AT TODAY'S WEIGHTS", [
        col("id", "ID", "text", 6), col("name", "WINDOW", "text", 12), col("start", "START", "date"), col("end", "END", "date"),
        col("coverage", "COVERAGE", "pct"), col("ret", "RETURN", "pct"), col("loss_money", "P/L MONEY", "money")], st_rows,
        "COVERAGE = SHARE OF TODAY'S WEIGHT THAT HAS HISTORY OVER THE WINDOW; RETURN AND P/L ARE ON THE COVERED SHARE ONLY; "
        "PRICE RETURNS FROM DAILY CLOSES, DIVIDENDS NOT INCLUDED")

    # --- BACKTEST of the one-day 99% historical VaR over the last 250 days ----------------------------------------------------
    bt_rows, bt_note = [], "ONE-DAY HISTORICAL 99% VAR (IN-SAMPLE, CONSTANT) AGAINST THE LAST 250 DAILY RETURNS AT TODAY'S WEIGHTS"
    try:
        test_ret = port[-250:]
        rep = vb.var_backtest(test_ret, qr.historical_var(port, 0.99, 1), confidence=0.99)
        k, ind, tl = rep.kupiec, rep.independence, rep.traffic_light
        bt_rows = [
            {"test": "KUPIEC POF", "stat": cm.fin(k.statistic), "p": cm.fin(k.p_value), "result": "REJECT" if k.rejected else "PASS",
             "detail": f"{k.violations} BREACHES OF {k.observations} DAYS, EXPECTED {k.expected_violations:.1f}"},
            {"test": "CHRISTOFFERSEN INDEPENDENCE", "stat": cm.fin(ind.statistic), "p": cm.fin(ind.p_value),
             "result": "NOT IDENTIFIED" if not ind.identified else ("REJECT" if ind.rejected else "PASS"),
             "detail": f"P(BREACH|BREACH) {ind.prob_breach_after_breach:.3f}, P(BREACH|CALM) {ind.prob_breach_after_calm:.3f}"},
            {"test": "BASEL TRAFFIC LIGHT", "stat": None, "p": cm.fin(tl.cumulative_probability), "result": tl.zone.upper(),
             "detail": f"{tl.violations} EXCEPTIONS; {tl.scaling_factor_basis}"},
        ]
    except ValueError as e:
        bt_note += f". NOT RUN: {e}"
    bt_sec = section("backtest", "VAR BACKTEST", [
        col("test", "TEST", "text", 28), col("stat", "STATISTIC", "num"), col("p", "P", "num4"), col("result", "RESULT", "text", 14),
        col("detail", "DETAIL", "text", 56)], bt_rows, bt_note)

    summary = [
        ("VALUE", f"{value:,.2f} {params.get('base', '')}".strip()), ("DAILY RETURNS", f"{n} FROM {cm.iso(int(rdays[0]))} TO {cm.iso(int(rdays[-1]))}"),
        ("VOL (ANN)", f"{vol * 100:.2f}%"), ("MAX DD", f"{dd.min() * 100:.2f}%"),
        (f"BETA TO {bench_sym}", f"{beta:.2f}" if beta is not None else "-"), (f"CORR TO {bench_sym}", f"{corr:.2f}" if corr is not None else "-"),
        ("HHI", f"{hhi:.4f}"), ("EFFECTIVE N", f"{1 / hhi:.2f}"), ("TOP 1 WEIGHT", f"{absw[0] * 100:.1f}%"), ("TOP 5 WEIGHT", f"{absw[:5].sum() * 100:.1f}%"),
    ]
    sum_sec = section("summary", "SUMMARY", [col("metric", "METRIC", "text", 20), col("value", "VALUE", "text", 40)],
                      [{"metric": a, "value": b} for a, b in summary])
    h95 = next((r for r in var_rows if r["method"] == "HIST" and r["conf"] == 95), None)
    heads = [
        head("VALUE", f"{value:,.0f} {params.get('base', '')}".strip(), value), head("VOL (ANN)", f"{vol * 100:.1f}%", vol),
        head(f"BETA {bench_sym}", f"{beta:.2f}" if beta is not None else "-", beta), head("MAX DD", f"{dd.min() * 100:.1f}%", float(dd.min())),
        head("HHI", f"{hhi:.3f}", hhi), head("EFFECTIVE N", f"{1 / hhi:.1f}", 1 / hhi),
    ]
    if h95 and h95["var_pct"] is not None:
        heads.append(head(f"VAR 95% {hor}D HIST", f"{h95['var_pct'] * 100:.2f}%", h95["var_pct"]))
    notes = ["CURRENT WEIGHTS HELD CONSTANT: TODAY'S QUANTITY X LAST CLOSE, REBALANCED DAILY OVER THE WINDOW",
             f"COMPUTED HERE FROM {n} DAILY RETURNS ({params.get('range', '')}); NOT A FORECAST", *cm.data_notes(labels)]
    if params.get("mixed_ccy"):
        notes.append("LOCAL-CURRENCY RETURNS, FX RISK NOT INCLUDED")
    if bench is None:
        notes.append(f"NO BENCHMARK BARS FOR {bench_sym}: BETA AND CORRELATION NOT SHOWN")
    elif pair is None:
        notes.append(f"UNDER 30 DAYS OVERLAP WITH {bench_sym}: BETA AND CORRELATION NOT SHOWN")
    notes.append(evt_note)
    charts = [
        {"id": "equity", "title": "CUMULATIVE RETURN (CURRENT WEIGHTS HELD CONSTANT)", "xlabel": "YEAR", "ylabel": "RETURN",
         "series": [{"name": "PORTFOLIO", "points": [[round(float(x), 4), round(float(y), 6)] for x, y in zip(cm.year(rdays), eq - 1.0, strict=True)]}]},
        {"id": "drawdown", "title": "DRAWDOWN (CURRENT WEIGHTS HELD CONSTANT)", "xlabel": "YEAR", "ylabel": "DRAWDOWN",
         "series": [{"name": "PORTFOLIO", "points": [[round(float(x), 4), round(float(y), 6)] for x, y in zip(cm.year(rdays), dd, strict=True)]}]},
    ]
    progress(1.0, "done")
    body = payload(None, title, heads, [sum_sec, var_sec, ctr_sec, st_sec, bt_sec], notes, source=None, charts=charts)
    return cm.envelope(body, labels)
