"""QL (spec decision H): calculators over the ported quant library, one table each. Daily bars only (volume calcs say so).

Each calculator returns (headline, sections, notes, charts); `run` wraps it in the standard payload and envelope. A calculator that cannot
run on the inputs it was given raises `Unrunnable` and the job answers NOT RUNNABLE (a normal answer, never a fake number).
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from ..research.table import col, head, payload, section
from . import common as cm

MIN_RETURNS = 60
DAILY_NOTE = "DAILY BARS, NOT TICK DATA: ESTIMATES FROM DAILY OHLCV ARE COARSE PROXIES OF THE INTRADAY QUANTITIES"
FLOW_NOTE = "SIGNED FLOW FROM BULK VOLUME CLASSIFICATION OF EACH DAY (BUY SHARE = NORMAL CDF OF PRICE CHANGE / ITS STD)"


class Unrunnable(Exception):
    pass


def _pct(label: str, x, signed: bool = False) -> dict:
    v = cm.fin(x)
    return head(label, None if v is None else f"{v * 100:{'+' if signed else ''}.2f}%", v)


def _num(label: str, x, fmt: str = ".4f") -> dict:
    v = cm.fin(x)
    return head(label, None if v is None else format(v, fmt), v)


def _yes(label: str, flag: bool) -> dict:
    return head(label, "YES" if flag else "NO")


def _closes(data: dict, sym: str, need: int = 4) -> tuple[np.ndarray, np.ndarray]:
    days, c = cm.series((data.get("bars") or {}).get(sym))
    if days.size < need:
        raise Unrunnable(f"ONLY {days.size} DAILY BARS FOR {sym} (NEED {need})")
    return days, c


def _cv(data: dict, sym: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(days, closes, volumes) one bar a day (the last), without missing closes; a missing volume is NaN."""
    b = (data.get("bars") or {}).get(sym) or {}
    if not b.get("t"):
        raise Unrunnable(f"NO DAILY BARS FOR {sym}")
    t = np.asarray(b["t"], dtype=np.int64) // 86400
    c = np.array([np.nan if x is None else x for x in b["c"]], dtype=float)
    v = np.array([np.nan if x is None else x for x in b.get("v") or [None] * len(c)], dtype=float)
    ok = np.isfinite(c) & (c > 0)
    t, c, v = t[ok], c[ok], v[ok]
    if t.size < 5:
        raise Unrunnable(f"ONLY {t.size} DAILY BARS FOR {sym} (NEED 5)")
    last = np.append(t[1:] != t[:-1], True)
    return t[last], c[last], v[last]


def _volume_flow(c: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(price change, buy volume, sell volume, volume) per day from Easley's bulk volume classification, days with a volume only."""
    from scipy.stats import norm

    dp = np.diff(c)
    vol = v[1:]
    ok = np.isfinite(vol) & (vol > 0)
    if int(ok.sum()) < 5:
        raise Unrunnable("NO VOLUME IN THE DAILY BARS")
    dp, vol = dp[ok], vol[ok]
    sd = dp.std(ddof=1)
    if not sd > 0:
        raise Unrunnable("THE PRICE NEVER CHANGES")
    buy = vol * norm.cdf(dp / sd)
    return dp, buy, vol - buy, vol


# --- calculators --------------------------------------------------------------------------------------------------------------------
def garch(p: dict, data: dict, progress):
    import pandas as pd

    from ..quantlib.timeseries import fit_garch

    _, c = _closes(data, p["symbols"][0], MIN_RETURNS + 1)
    r = c[1:] / c[:-1] - 1.0
    h = int(p.get("h") or 5)
    progress(0.4, "fitting GARCH(1,1)")
    g = fit_garch(pd.Series(r), h)
    ann = math.sqrt(252)
    hl = [_num("OMEGA", g["omega"], ".6f"), _num("ALPHA", g["alpha"]), _num("BETA", g["beta"]), _num("PERSISTENCE", g["persistence"]),
          _pct("LONG-RUN VOL (ANN)", g["long_run_vol"] * ann if math.isfinite(g["long_run_vol"]) else None),
          _pct("CURRENT VOL (ANN)", g["current_vol"] * ann), _num("AIC", g["aic"], ".1f"), _num("BIC", g["bic"], ".1f"),
          head("OBSERVATIONS", str(r.size), r.size)]
    rows = [{"day": i + 1, "vol": cm.fin(v), "ann": cm.fin(v * ann)} for i, v in enumerate(np.asarray(g["forecast_vol"], dtype=float))]
    sec = section("forecast", "VOLATILITY FORECAST", [col("day", "DAYS AHEAD", "int"), col("vol", "DAILY VOL", "pct"), col("ann", "ANNUALISED", "pct")],
                  rows, "CONDITIONAL VOLATILITY FORECAST, GARCH(1,1) NORMAL, DAILY RETURNS")
    return hl, [sec], ["OMEGA IS IN PERCENT-SQUARED (RETURNS ARE FITTED IN PERCENT)", "A MODEL FIT, NOT A FORECAST YOU CAN TRADE ON"], []


def ou(p: dict, data: dict, progress):
    import pandas as pd

    from ..quantlib.timeseries import fit_ornstein_uhlenbeck

    _, c = _closes(data, p["symbols"][0], 30)
    progress(0.4, "fitting OU")
    f = fit_ornstein_uhlenbeck(pd.Series(np.log(c)), 1.0)
    hl = cm.fin(f["half_life"])
    hl = hl if hl is not None and hl > 0 else None
    mu = cm.fin(f["mu"])
    heads = [_num("KAPPA", f["theta"], ".5f"), head("HALF LIFE", None if hl is None else f"{hl:.1f} DAYS", hl),
             _num("MU (LOG PRICE)", mu), head("MU (PRICE)", None if mu is None else f"{math.exp(mu):.2f}", None if mu is None else math.exp(mu)),
             _pct("SIGMA (ANN)", f["sigma"] * math.sqrt(252)), _num("AR(1) B", f["ar1_b"]), _yes("MEAN REVERTING", bool(f["is_mean_reverting"]))]
    notes = ["FIT ON LOG CLOSES, DT = 1 DAY (KAPPA PER DAY)"]
    if not f["is_mean_reverting"]:
        notes.append("NOT MEAN REVERTING IN THIS WINDOW: THE HALF LIFE IS NOT DEFINED")
    return heads, [], notes, []


def _pair(p: dict, data: dict):
    import pandas as pd

    a, b = p["symbols"][:2]
    cols = {a: _closes(data, a, 30), b: _closes(data, b, 30)}
    days, mat = cm.align(cols)
    if days.size < 30:
        raise Unrunnable(f"ONLY {days.size} DAYS COMMON TO {a} AND {b} (NEED 30)")
    return a, b, days, pd.Series(mat[:, 0], index=days), pd.Series(mat[:, 1], index=days)


def _crit(d: dict) -> dict:
    return section("critical", "CRITICAL VALUES", [col("level", "LEVEL"), col("value", "VALUE", "num4")],
                   [{"level": k, "value": cm.fin(v)} for k, v in d.items()])


def coint(p: dict, data: dict, progress):
    from ..quantlib.timeseries import cointegration_test, find_hedge_ratio

    a, b, _, y, x = _pair(p, data)
    progress(0.4, "Engle-Granger")
    t = cointegration_test(y, x)
    h = find_hedge_ratio(y, x)
    hl = cm.fin(h["half_life"])
    hl = hl if hl is not None and hl > 0 else None
    heads = [_num("P-VALUE", t["p_value"]), _num("TEST STAT", t["test_statistic"], ".3f"), _yes("COINTEGRATED (5%)", t["is_cointegrated"]),
             _num("HEDGE RATIO", h["hedge_ratio"]), head("HALF LIFE", None if hl is None else f"{hl:.1f} DAYS", hl),
             head("OBSERVATIONS", str(len(y)), len(y))]
    return heads, [_crit(t["critical_values"])], [f"ENGLE-GRANGER ON CLOSE LEVELS, Y = {a}, X = {b}; H0: NO COINTEGRATION"], []


def hedge(p: dict, data: dict, progress):
    from ..quantlib.timeseries import find_hedge_ratio

    a, b, _, y, x = _pair(p, data)
    h = find_hedge_ratio(y, x)
    spread = float(y.iloc[-1] - h["hedge_ratio"] * x.iloc[-1])
    z = (spread - h["spread_mean"]) / h["spread_std"] if h["spread_std"] else None
    hl = cm.fin(h["half_life"])
    hl = hl if hl is not None and hl > 0 else None
    heads = [_num("HEDGE RATIO", h["hedge_ratio"]), _num("INTERCEPT", h["intercept"]), _num("SPREAD MEAN", h["spread_mean"]),
             _num("SPREAD STD", h["spread_std"]), _num("SPREAD Z (LAST)", z, "+.2f"), head("HALF LIFE", None if hl is None else f"{hl:.1f} DAYS", hl),
             head("OBSERVATIONS", str(len(y)), len(y))]
    return heads, [], [f"SPREAD = {a} - HEDGE RATIO x {b}, OLS ON CLOSE LEVELS"], []


def copula(p: dict, data: dict, progress):
    from scipy.stats import kendalltau, spearmanr

    from ..quantlib.copula import fit_copula_from_tau

    a, b = p["symbols"][:2]
    days, mat = cm.align({a: _closes(data, a, 30), b: _closes(data, b, 30)})
    if days.size < 30:
        raise Unrunnable(f"ONLY {days.size} DAYS COMMON TO {a} AND {b} (NEED 30)")
    r = mat[1:] / mat[:-1] - 1.0
    tau = float(kendalltau(r[:, 0], r[:, 1]).statistic)
    rho = float(spearmanr(r[:, 0], r[:, 1]).statistic)
    rows = []
    for fam, pname in (("clayton", "THETA"), ("gumbel", "THETA"), ("gaussian", "RHO")):
        try:
            f = fit_copula_from_tau(tau, fam)  # type: ignore[arg-type]
        except ValueError:
            rows.append({"family": fam.upper(), "name": "NOT DEFINED FOR THIS TAU"})
            continue
        rows.append({"family": fam.upper(), "name": pname, "param": cm.fin(f.get("theta", f.get("rho"))),
                     "lower": cm.fin(f.get("lambda_lower")), "upper": cm.fin(f.get("lambda_upper"))})
    sec = section("families", "COPULA FITS FROM KENDALL TAU", [col("family", "FAMILY"), col("name", "PARAMETER"), col("param", "VALUE", "num4"),
                                                               col("lower", "LOWER TAIL", "num4"), col("upper", "UPPER TAIL", "num4")], rows)
    heads = [_num("KENDALL TAU", tau), _num("SPEARMAN RHO", rho), head("OBSERVATIONS", str(r.shape[0]), r.shape[0])]
    return heads, [sec], [f"DAILY RETURNS OF {a} AND {b}; PARAMETERS CALIBRATED FROM TAU, NOT MAXIMUM LIKELIHOOD"], []


def roll(p: dict, data: dict, progress):
    from ..quantlib.microstructure import roll_effective_spread

    _, c = _closes(data, p["symbols"][0], 30)
    s = roll_effective_spread(c)
    heads = [_num("ROLL SPREAD", s, ".4f"), _pct("ROLL SPREAD % OF PRICE", s / float(c.mean())), head("OBSERVATIONS", str(c.size), c.size)]
    notes = [DAILY_NOTE, "ZERO WHEN THE SERIAL COVARIANCE OF DAILY PRICE CHANGES IS NOT NEGATIVE"]
    return heads, [], notes, []


def amihud(p: dict, data: dict, progress):
    from ..quantlib.microstructure import amihud_illiquidity

    _, c, v = _cv(data, p["symbols"][0])
    a = amihud_illiquidity(c[1:] / c[:-1] - 1.0, c[1:] * v[1:])
    if not math.isfinite(a):
        raise Unrunnable("NO VOLUME IN THE DAILY BARS")
    heads = [head("AMIHUD", f"{a:.3e}", a), head("PER 1M USD TRADED", f"{a * 1e8:.3g}% PRICE MOVE", a * 1e6),
             head("OBSERVATIONS", str(c.size - 1), c.size - 1)]
    return heads, [], [DAILY_NOTE, "MEAN OF |RETURN| / DOLLAR VOLUME (CLOSE x VOLUME)"], []


def kyle(p: dict, data: dict, progress):
    from ..quantlib.microstructure import kyles_lambda

    _, c, v = _cv(data, p["symbols"][0])
    dp, buy, sell, _ = _volume_flow(c, v)
    lam = kyles_lambda(dp, buy - sell)
    heads = [head("KYLE LAMBDA", f"{lam:.3e}", lam), head("OBSERVATIONS", str(dp.size), dp.size)]
    return heads, [], [DAILY_NOTE, FLOW_NOTE, "LAMBDA: PRICE CHANGE PER SHARE OF NET SIGNED FLOW, OLS WITH AN INTERCEPT"], []


def vpin(p: dict, data: dict, progress):
    from ..quantlib.microstructure import vpin as vpin_fn

    _, c, v = _cv(data, p["symbols"][0])
    _, buy, sell, vol = _volume_flow(c, v)
    n_buckets = int(p.get("buckets") or 50)
    size = float(vol.mean())
    series = vpin_fn(buy, sell, size, n_buckets)
    if series.size == 0:
        raise Unrunnable("TOO LITTLE VOLUME TO FILL A BUCKET")
    heads = [_num("VPIN", series[-1]), _num("VPIN MEAN", series.mean()), _num("VPIN MAX", series.max()),
             head("BUCKETS FILLED", str(series.size), series.size), head("BUCKET SIZE", f"{size:,.0f} SHARES", size),
             head("WINDOW (BUCKETS)", str(n_buckets), n_buckets)]
    chart = {"id": "vpin", "title": "VPIN BY VOLUME BUCKET", "xlabel": "BUCKET", "ylabel": "VPIN",
             "series": [{"name": "VPIN", "points": [[i + 1, cm.fin(x)] for i, x in enumerate(series)]}]}
    return heads, [], [DAILY_NOTE, FLOW_NOTE, "BUCKET SIZE = MEAN DAILY VOLUME, SO ABOUT ONE BUCKET PER BAR"], [chart]


def event(p: dict, data: dict, progress):
    import pandas as pd

    from ..quantlib.eventstudy import event_study

    sym, bench = p["symbols"][0], p.get("bench") or "SPY"
    cols = {sym: _closes(data, sym, 30), bench: _closes(data, bench, 30)}
    days, mat = cm.align(cols)
    if days.size < 30:
        raise Unrunnable(f"ONLY {days.size} DAYS COMMON TO {sym} AND {bench}")
    idx = pd.DatetimeIndex(days[1:].astype("datetime64[D]"))
    r = mat[1:] / mat[:-1] - 1.0
    frame = pd.DataFrame({sym: r[:, 0]}, index=idx)
    mkt = pd.Series(r[:, 1], index=idx)
    win = p.get("win") or [-5, 5]
    progress(0.5, "event study")
    res = event_study(frame, mkt, [(sym, pd.Timestamp(p["date"]))], (int(win[0]), int(win[1])), int(p.get("est") or 120))
    if not res.events:
        raise Unrunnable("; ".join(f"{s} {d}: {why}".upper() for s, d, why in res.dropped) or "NO EVENT COULD BE MEASURED")
    ev = res.events[0]
    heads = [_pct("CAR", ev.car, True), _num("CAR T", ev.standardised_car, "+.2f"), _num("BETA", ev.fit.beta), _pct("ALPHA (DAILY)", ev.fit.alpha, True),
             _pct("RESIDUAL STD (DAILY)", ev.fit.residual_std), head("EVENT ROW", str(ev.event_date)[:10]),
             head("WINDOW", f"{int(win[0]):+d} TO {int(win[1]):+d} DAYS"), head("ESTIMATION OBS", str(ev.fit.observations), ev.fit.observations)]
    rows = []
    cum_ = 0.0
    for rel, ar in ev.abnormal_returns.items():
        cum_ += float(ar)
        rows.append({"rel": int(rel), "ar": cm.fin(ar), "car": cm.fin(cum_)})
    sec = section("window", "ABNORMAL RETURNS", [col("rel", "DAY", "int"), col("ar", "ABNORMAL", "pct"), col("car", "CUMULATIVE", "pct")], rows,
                  f"MARKET MODEL VS {bench}, ESTIMATED OVER {ev.fit.observations} DAYS BEFORE THE WINDOW")
    return heads, [sec], ["ONE EVENT: THE CAR T-STAT IS ITS OWN ESTIMATION-WINDOW ERROR, NOT A CROSS-SECTIONAL TEST", f"BENCHMARK {bench}"], []


def dsr(p: dict, data: dict, progress):
    from ..quantlib.multipletesting import deflated_sharpe_ratio

    t_obs, n = int(p["t"]), int(p["n"])
    given = p.get("trial_sr_std")
    trial = float(given) if given is not None else 1.0 / math.sqrt(max(t_obs - 1, 1))
    r = deflated_sharpe_ratio(float(p["sr"]), n, t_obs, trial, float(p.get("skew", 0.0)), float(p.get("kurt", 3.0)))
    heads = [_num("DSR", r.deflated_sharpe_ratio, ".4f"), _num("EXPECTED MAX SR", r.expected_maximum_sharpe, ".4f"),
             _num("OBSERVED SR", r.observed_sharpe, ".4f"), _yes("SURVIVES (95%)", r.survives), head("TRIALS (N)", str(n), n),
             head("OBSERVATIONS (T)", str(t_obs), t_obs), _num("TRIAL SR STD", trial, ".4f")]
    notes = ["SHARPE RATIOS ARE PER OBSERVATION, NOT ANNUALISED", "DSR: PROBABILITY THE TRUE SHARPE BEATS THE BEST OF N TRIALS BY LUCK ALONE"]
    if given is None:
        notes.append("TRIAL_SR_STD NOT GIVEN: DEFAULT 1/SQRT(T-1), THE STD OF A SHARPE WITH NO EDGE")
    return heads, [], notes, []


def adf(p: dict, data: dict, progress):
    import pandas as pd

    from ..quantlib.timeseries import adf_test

    _, c = _closes(data, p["symbols"][0], 30)
    t = adf_test(pd.Series(c))
    heads = [_num("ADF STAT", t["adf_statistic"], ".3f"), _num("P-VALUE", t["p_value"]), head("LAGS USED", str(t["lags_used"]), t["lags_used"]),
             _yes("STATIONARY (5%)", t["is_stationary"]), head("OBSERVATIONS", str(c.size), c.size)]
    return heads, [_crit(t["critical_values"])], ["AUGMENTED DICKEY-FULLER ON CLOSE LEVELS (LAGS BY AIC); H0: A UNIT ROOT"], []


def hvar(p: dict, data: dict, progress):
    from ..quantlib import risk as qr

    _, c = _closes(data, p["symbols"][0], 30)
    r = c[1:] / c[:-1] - 1.0
    conf = float(p.get("conf") or 95.0) / 100.0
    hor = int(p.get("hor") or 1)
    heads = [_pct("HVAR", qr.historical_var(r, conf, hor)), _pct("CVAR", qr.historical_cvar(r, conf, hor)),
             _pct("PARAMETRIC VAR", qr.parametric_var(r, conf, hor)), head("CONFIDENCE", f"{conf * 100:g}%", conf * 100),
             head("HORIZON (DAYS)", str(hor), hor), _pct("WORST DAY", float(r.min()), True), head("OBSERVATIONS", str(r.size), r.size)]
    rows = [{"conf": lv, "hvar": cm.fin(qr.historical_var(r, lv / 100, hor)), "cvar": cm.fin(qr.historical_cvar(r, lv / 100, hor)),
             "pvar": cm.fin(qr.parametric_var(r, lv / 100, hor))} for lv in (95.0, 99.0)]
    sec = section("levels", "VAR BY CONFIDENCE", [col("conf", "CONFIDENCE %", "num"), col("hvar", "HISTORICAL", "pct"), col("cvar", "CVAR", "pct"),
                                                  col("pvar", "PARAMETRIC", "pct")], rows)
    return heads, [sec], ["HISTORICAL VAR: LOSS AT THE EMPIRICAL TAIL OF DAILY RETURNS, SQRT-OF-TIME FOR HORIZONS ABOVE 1 DAY"], []


CALCS: dict[str, Callable] = {"GARCH": garch, "OU": ou, "COINT": coint, "HEDGE": hedge, "COPULA": copula, "ROLL": roll, "AMIHUD": amihud,
                              "KYLE": kyle, "VPIN": vpin, "EVENT": event, "DSR": dsr, "ADF": adf, "HVAR": hvar}


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    labels = params.get("labels") or {}
    calc = params.get("calc") or "QL"
    syms = params.get("symbols") or []
    title = f"{calc} {' '.join(syms[:2])}".strip()
    if params.get("not_runnable"):
        return cm.not_runnable(title, params["not_runnable"], labels)
    progress(0.05, "loading bars")
    data = cm.load(params) if params.get("data_path") else {}
    try:
        heads, sections, notes, charts = CALCS[calc](params, data, progress)
    except Unrunnable as e:
        return cm.not_runnable(title, str(e), labels)
    except ValueError as e:
        return cm.not_runnable(title, f"BAD INPUT: {e}".upper(), labels)
    all_notes = [*notes, *([] if calc == "DSR" else cm.data_notes(labels))]
    out = payload(syms[0] if syms else None, title, heads, sections, all_notes, status="RUNNABLE", charts=charts)
    env = cm.envelope(out, labels)
    if calc == "DSR":
        env["source"] = "openterm.quantlib"
    progress(1.0, "done")
    return env
