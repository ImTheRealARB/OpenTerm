"""Produces backend/tests/fixtures/quant15_vibe_expected.json by running Vibe-Trading's OWN code (Phase 15 library).

Not part of the app and never imported by it. Needs numpy, pandas, scipy, statsmodels and arch (the last three are NOT OpenTerm
dependencies yet: run through uv's `--with`) and a directory with the original files from HKUDS/Vibe-Trading @ d0db2e3 laid out as in
the repo (the `agent` folder):
  agent/src/quantlib/*.py   agent/backtest/{risk_xray,regime,correlation,metrics,validation,models}.py
  agent/backtest/optimizers/*.py   agent/src/factors/{base,_backend,bench_runner}.py   agent/src/factors/zoo/{alpha101,qlib158,academic}/*.py
The files are never copied into this repo.

    cd backend
    uv run --with scipy --with statsmodels --with arch python ../scripts/vibe_quant15_crosscheck.py <path to the agent folder>

Output shape: {"source", "versions", "cases": [...], "alpha": {...}}. Each case is {"fn": "<module>.<function>", "args": {...}} plus
"result" or "raises" (the exception class name). Modules: risk, var_backtest, portfolio, optimizers, attribution, factormodel,
timeseries, copula, microstructure, eventstudy, multipletesting, regime, risk_xray, alpha (bench_runner t_stat / categorise).
NaN is written as null, infinities as "inf" / "-inf" (in results only). Argument encodings (the replay must decode them):
  {"$array": nested list}                          numpy float array
  {"$series": {"values": [...], "index": [...]?, "date_index": true?, "name": "x"?}}   pandas Series (no index = RangeIndex)
  {"$frame": {"index": [...], "columns": [...], "data": [[...]], "date_index": true?}}  pandas DataFrame
  {"$ts": "2026-01-02"}                            pandas Timestamp
  {"$float": "nan" | "inf" | "-inf"}             a non-finite float scalar
  {"$ols": {"y": [...], "X": [[...]]}}             statsmodels OLS(y, X).fit() (X already holds the constant column)
  {"$brinson": {<brinson_fachler args>}}           a BrinsonResult built by brinson_fachler (for carino_link)
  {"$prices": {code: {"index": [...dates], "close": [...]}}}   dict of close-price frames with a DatetimeIndex (regime timeline)
In argument lists null means NaN. Plain lists / dicts / scalars are passed as they are.
Result encodings: pandas Series -> list (RangeIndex) or {label: value}; DataFrame -> {"index","columns","data"}; Timestamp/date -> ISO
string; dataclasses -> dict; tuples -> lists; dict keys -> strings.
`optimizers.<module>` cases are run by this script's own driver (see run_optimizer): args hold the call, the result holds the position
rows at `record_rows`. `alpha.t_stat` / `alpha.categorise` are Vibe's bench_runner functions, copied verbatim out of that file's AST (the
file itself imports the whole app). The factor modules' bottleneck fast path is switched off (pure numpy), the path an OpenTerm port has.
"""

import ast
import contextlib
import dataclasses
import datetime as dt
import importlib
import io
import json
import math
import shutil
import sys
import tempfile
import types
import typing
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "quant15_vibe_expected.json"

QUANTLIB = ["risk", "var_backtest", "portfolio", "attribution", "factormodel", "timeseries", "copula", "microstructure", "eventstudy",
            "multipletesting"]
BACKTEST = ["risk_xray", "regime", "correlation", "metrics", "validation", "models"]
OPTIMIZERS = ["base", "equal_volatility", "risk_parity", "mean_variance", "max_diversification", "turnover_aware"]
MODULES = {m: f"src.quantlib.{m}" for m in QUANTLIB}
MODULES.update({"regime": "backtest.regime", "risk_xray": "backtest.risk_xray"})

ALPHA_CANDIDATES = {
    "alpha101": [f"alpha_{n:03d}" for n in (1, 2, 3, 4, 6, 9, 12, 13, 16, 21, 33, 34, 101)],
    "qlib158": ["roc10", "std20", "ma20", "beta10", "resi10", "rsqr20", "rank20", "corr10", "rsv10", "wvma20"],
    "academic": ["strev", "illiq", "retskew", "mkt_rf", "rmw", "smb"],
}


# --------------------------------------------------------------------------------------------------------------- package
def build_package() -> Path:
    root = Path(tempfile.mkdtemp(prefix="vibe_quant15_"))
    pkgs = ["src", "src/quantlib", "src/factors", "src/factors/zoo", "backtest", "backtest/optimizers"] + \
           [f"src/factors/zoo/{f}" for f in ALPHA_CANDIDATES]
    for pkg in pkgs:
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")

    def cp(rel: str) -> None:
        shutil.copy(SRC / rel, root / rel)

    for m in QUANTLIB:
        cp(f"src/quantlib/{m}.py")
    for m in BACKTEST:
        cp(f"backtest/{m}.py")
    for m in OPTIMIZERS:
        cp(f"backtest/optimizers/{m}.py")
    cp("src/factors/base.py")
    cp("src/factors/_backend.py")
    for fam, names in ALPHA_CANDIDATES.items():
        for n in names:
            cp(f"src/factors/zoo/{fam}/{n}.py")
    # _backend reads a config flag through the app's settings; the flag is replaced by its "disabled" value. Nothing else changes.
    p = root / "src/factors/_backend.py"
    s = p.read_text(encoding="utf-8")
    needle = "    from src.config.accessor import get_env_config\n"
    assert needle in s
    s = s.replace(needle, "")
    s = s.replace("    if get_env_config().agent_tuning.vibe_trading_disable_bottleneck:\n        return\n", "    return\n")
    assert "get_env_config()" not in s and "src.config" not in s
    p.write_text(s, encoding="utf-8")
    return root


def bench_helpers() -> types.SimpleNamespace:
    """t_stat and categorise out of bench_runner.py, source unchanged (the module itself needs the whole app)."""
    src = (SRC / "src/factors/bench_runner.py").read_text(encoding="utf-8")
    ns: dict = {"math": math, "Any": typing.Any}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name in ("t_stat", "categorise"):
            exec(compile(ast.Module([node], []), "bench_runner", "exec"), ns)
    return types.SimpleNamespace(t_stat=ns["t_stat"], categorise=ns["categorise"])


# --------------------------------------------------------------------------------------------------------------- encoding
def plain(o):
    """Result / argument encoder (see the module docstring)."""
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, dict):
        return {str(plain_key(k)): plain(v) for k, v in o.items()}
    if isinstance(o, pd.DataFrame):
        return {"index": [plain(plain_key(x)) for x in o.index], "columns": [plain(plain_key(x)) for x in o.columns],
                "data": [[plain(x) for x in row] for row in o.to_numpy().tolist()]}
    if isinstance(o, pd.Series):
        if isinstance(o.index, pd.RangeIndex):
            return [plain(x) for x in o.tolist()]
        return {str(plain_key(k)): plain(v) for k, v in o.items()}
    if isinstance(o, np.ndarray):
        return [plain(x) for x in o.tolist()]
    if isinstance(o, (list, tuple)):
        return [plain(x) for x in o]
    if o is pd.NaT:
        return None
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d") if o == o.normalize() else o.isoformat()
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) else ("inf" if f == math.inf else "-inf" if f == -math.inf else f)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if callable(o):
        return "<callable>"
    return o


def plain_key(k):
    if isinstance(k, pd.Timestamp):
        return k.strftime("%Y-%m-%d") if k == k.normalize() else k.isoformat()
    if isinstance(k, (np.integer,)):
        return int(k)
    return k


def numlist(v: list) -> list:
    out = [revive(x) for x in v]
    if any(x is None for x in out) and any(isinstance(x, (int, float)) for x in out):
        out = [math.nan if x is None else x for x in out]
    return out


def mkindex(idx, date_index: bool):
    return pd.DatetimeIndex(idx) if date_index else pd.Index(idx)


def revive(v):
    if isinstance(v, dict):
        if "$array" in v:
            return np.asarray(numlist(v["$array"]), dtype=float)
        if "$ts" in v:
            return pd.Timestamp(v["$ts"])
        if "$float" in v:
            return float(v["$float"])
        if "$series" in v:
            s = v["$series"]
            idx = mkindex(s["index"], s.get("date_index", False)) if "index" in s else None
            return pd.Series(np.asarray(numlist(s["values"]), dtype=float), index=idx, name=s.get("name"))
        if "$frame" in v:
            f = v["$frame"]
            return pd.DataFrame(np.asarray(numlist(f["data"]), dtype=float), index=mkindex(f["index"], f.get("date_index", False)),
                                columns=f["columns"])
        if "$ols" in v:
            import statsmodels.api as sm
            return sm.OLS(np.asarray(v["$ols"]["y"], dtype=float), np.asarray(v["$ols"]["X"], dtype=float)).fit()
        if "$brinson" in v:
            return MODS["attribution"].brinson_fachler(**revive(v["$brinson"]))
        if "$prices" in v:
            return {code: pd.DataFrame({"close": np.asarray(d["close"], dtype=float)}, index=pd.DatetimeIndex(d["index"]))
                    for code, d in v["$prices"].items()}
        return {k: revive(x) for k, x in v.items()}
    if isinstance(v, list):
        return numlist(v)
    return v


def rd(x, n: int = 8):
    return np.round(np.asarray(x, dtype=float), n)


def arr(x, n: int = 10) -> dict:
    return {"$array": rd(x, n).tolist()}


def ser(values, index=None, date_index: bool = False, n: int = 10, name=None) -> dict:
    s: dict = {"values": rd(values, n).tolist()}
    if index is not None:
        s["index"] = [str(i) for i in index]
        if date_index:
            s["date_index"] = True
    if name:
        s["name"] = name
    return {"$series": s}


def frm(data, index, columns, date_index: bool = False, n: int = 10) -> dict:
    f: dict = {"index": [str(i) for i in index], "columns": list(columns), "data": rd(data, n).tolist()}
    if date_index:
        f["date_index"] = True
    return {"$frame": f}


def iso(idx) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in idx]


def fl(x: float):
    return {"$float": repr(float(x))} if not math.isfinite(x) else x


def ts(s: str) -> dict:
    return {"$ts": s}


# --------------------------------------------------------------------------------------------------------------- case lists
def case(fn: str, _note: str | None = None, _bad: bool = False, **args) -> dict:
    c: dict = {"fn": fn, "args": plain(args)}
    if _note:
        c["note"] = _note
    if _bad:
        c["_expect_raise"] = True
    return c


def bad(fn: str, **args) -> dict:
    return case(fn, _bad=True, **args)


def risk_cases() -> list[dict]:
    rng = np.random.default_rng(1501)
    normal = rd(rng.normal(0.0004, 0.012, 120))
    fat = rd(rng.standard_t(3, 250) * 0.008)
    small = rd(rng.normal(0.0, 0.01, 12))
    with_nan = normal[:60].copy().tolist()
    with_nan[5] = math.nan
    with_nan[17] = math.nan
    out: list[dict] = []
    grid = [(normal, 0.95, 1), (normal, 0.99, 1), (normal, 0.99, 10), (fat, 0.95, 1), (fat, 0.975, 5), (fat, 0.99, 1),
            (small, 0.9, 1), (with_nan, 0.95, 3)]
    for fn in ("historical_var", "parametric_var", "historical_cvar"):
        for r, conf, h in grid:
            out.append(case(f"risk.{fn}", returns=list(r), confidence=conf, horizon=h))
        out.append(bad(f"risk.{fn}", returns=list(normal[:20]), confidence=1.5))
        out.append(bad(f"risk.{fn}", returns=list(normal[:20]), confidence=0.95, horizon=0))
        out.append(bad(f"risk.{fn}", returns=[]))
        out.append(bad(f"risk.{fn}", returns=[math.nan, math.nan]))
    out.append(bad("risk.parametric_var", returns=[0.01]))
    # equity curves: a volatile one with several drawdowns, a monotone one, a short one, bad ones
    eq = rd(100 * np.cumprod(1 + rng.normal(0.0003, 0.014, 200)), 6)
    eq_dates = iso(pd.bdate_range("2025-03-03", periods=200))
    mono = rd(100 * np.cumprod(1 + np.full(40, 0.002)), 6)
    short = [100.0, 98.0, 99.5, 97.0, 101.0, 95.0, 96.0]
    for fn in ("drawdown_series", "ulcer_index", "pain_index", "max_drawdown_analysis", "drawdown_distribution_analysis"):
        out.append(case(f"risk.{fn}", equity=list(eq)))
        out.append(case(f"risk.{fn}", equity=ser(eq, eq_dates, True, 6), _note="date-indexed series"))
        out.append(case(f"risk.{fn}", equity=list(mono)))
        out.append(case(f"risk.{fn}", equity=short))
        out.append(bad(f"risk.{fn}", equity=[100.0, -5.0, 90.0]))
        out.append(bad(f"risk.{fn}", equity=[]))
    for pct in (5.0, 10.0):
        out.append(case("risk.fit_gpd_tail", returns=list(fat), threshold_pct=pct))
    out.append(case("risk.fit_gpd_tail", returns=list(normal), threshold_pct=5.0))
    out.append(bad("risk.fit_gpd_tail", returns=list(normal[:20]), threshold_pct=0.0))
    out.append(bad("risk.fit_gpd_tail", returns=list(normal[:20]), threshold_pct=100.0))
    out.append(bad("risk.fit_gpd_tail", returns=[0.01, 0.01, 0.01, 0.01]))
    # Monte Carlo: seeded, so the original's own generator (default_rng) is part of the contract
    out.append(case("risk.monte_carlo_gbm", s0=100.0, mu=0.08, sigma=0.2, n_steps=12, n_paths=20, seed=7, steps_per_year=12))
    out.append(case("risk.monte_carlo_gbm", s0=50.0, mu=0.05, sigma=0.0, n_steps=5, n_paths=4, seed=1))
    out.append(case("risk.monte_carlo_gbm", s0=100.0, mu=-0.1, sigma=0.35, n_steps=30, n_paths=8, seed=2024))
    out.append(bad("risk.monte_carlo_gbm", s0=0.0, mu=0.05, sigma=0.2, n_steps=5, n_paths=4, seed=1))
    out.append(bad("risk.monte_carlo_gbm", s0=100.0, mu=0.05, sigma=-0.2, n_steps=5, n_paths=4, seed=1))
    out.append(bad("risk.monte_carlo_gbm", s0=100.0, mu=0.05, sigma=0.2, n_steps=5, n_paths=0, seed=1))
    prng = np.random.default_rng(3)
    s0, mu, sg, steps, npaths, spy = 100.0, 0.06, 0.25, 10, 40, 252
    z = prng.standard_normal((npaths, steps))
    paths = np.empty((npaths, steps + 1))
    paths[:, 0] = s0
    paths[:, 1:] = s0 * np.exp(np.cumsum((mu - 0.5 * sg ** 2) / spy + sg * math.sqrt(1 / spy) * z, axis=1))
    paths = rd(paths, 8)
    for conf in (0.95, 0.99):
        out.append(case("risk.analyze_mc_results", paths=arr(paths, 8), confidence=conf))
    out.append(bad("risk.analyze_mc_results", paths=arr(paths[:, 0], 8), confidence=0.95))
    out.append(bad("risk.analyze_mc_results", paths=arr(np.zeros((3, 4)), 8), confidence=0.95))
    out.append(bad("risk.analyze_mc_results", paths=arr(paths[:3], 8), confidence=0.0))
    return out


def var_backtest_cases() -> list[dict]:
    rng = np.random.default_rng(1502)
    out: list[dict] = []
    for v, n, c, s in ((5, 250, 0.99, 0.05), (0, 250, 0.99, 0.05), (250, 250, 0.99, 0.05), (12, 250, 0.95, 0.05),
                       (3, 500, 0.99, 0.01), (1, 250, 0.99, 0.05), (8, 252, 0.99, 0.10), (0, 50, 0.9, 0.05)):
        out.append(case("var_backtest.kupiec_pof", violations=v, observations=n, confidence=c, significance=s))
    out.append(bad("var_backtest.kupiec_pof", violations=300, observations=250))
    out.append(bad("var_backtest.kupiec_pof", violations=1, observations=0))
    out.append(bad("var_backtest.kupiec_pof", violations=1, observations=250, confidence=1.0))
    iid = (rng.random(250) < 0.02).tolist()
    clustered = [False] * 250
    for i in (40, 41, 42, 43, 120, 121, 122, 200, 201):
        clustered[i] = True
    seqs = [("iid", iid), ("clustered", clustered), ("alternating", [i % 2 == 0 for i in range(60)]),
            ("none", [False] * 100), ("all", [True] * 30), ("single", [False] * 50 + [True] + [False] * 49)]
    for name, b in seqs:
        out.append(case("var_backtest.christoffersen_independence", breaches=b, _note=name))
        out.append(case("var_backtest.christoffersen_conditional_coverage", breaches=b, confidence=0.99, _note=name))
    out.append(case("var_backtest.christoffersen_conditional_coverage", breaches=clustered, confidence=0.95, significance=0.10))
    out.append(bad("var_backtest.christoffersen_independence", breaches=[True]))
    out.append(bad("var_backtest.christoffersen_conditional_coverage", breaches=[], confidence=0.99))
    for v, n, c in ((0, 250, 0.99), (3, 250, 0.99), (4, 250, 0.99), (5, 250, 0.99), (7, 250, 0.99), (9, 250, 0.99), (10, 250, 0.99),
                    (4, 500, 0.99), (2, 100, 0.99), (8, 250, 0.95)):
        out.append(case("var_backtest.basel_traffic_light", violations=v, observations=n, confidence=c))
    out.append(bad("var_backtest.basel_traffic_light", violations=-1, observations=250))
    out.append(bad("var_backtest.basel_traffic_light", violations=3, observations=0))
    rets = rd(rng.normal(0.0, 0.01, 250))
    dates = iso(pd.bdate_range("2025-01-02", periods=250))
    out.append(case("var_backtest.var_backtest", returns=list(rets), var=0.0233, confidence=0.99))
    out.append(case("var_backtest.var_backtest", returns=list(rets), var=0.0165, confidence=0.95, significance=0.10))
    vol = rd(0.008 + 0.004 * np.abs(np.sin(np.arange(250) / 20.0)))
    out.append(case("var_backtest.var_backtest", returns=ser(rets, dates, True, 8), var=ser(vol * 2.326, dates, True, 8), confidence=0.99,
                    _note="indexed: breach dates"))
    r2 = rets.copy().tolist()
    r2[10] = math.nan
    out.append(case("var_backtest.var_backtest", returns=r2, var=0.02, confidence=0.99, _note="a NaN return is dropped"))
    out.append(case("var_backtest.violation_indicator", returns=list(rets[:40]), var=0.012))
    out.append(bad("var_backtest.var_backtest", returns=list(rets), var=list(vol[:10]), confidence=0.99))
    return out


def portfolio_cases() -> list[dict]:
    rng = np.random.default_rng(1503)
    n = 6
    vols = np.array([0.15, 0.22, 0.18, 0.30, 0.12, 0.25])
    factor = rng.normal(size=(n, 2))
    corr = factor @ factor.T + np.diag(rng.uniform(0.5, 1.5, n))
    d = np.sqrt(np.diag(corr))
    corr = corr / np.outer(d, d)
    cov = rd(corr * np.outer(vols, vols), 10)
    corr = rd(corr, 10)
    cov_arr, corr_arr = arr(cov, 10), arr(corr, 10)
    out = [case("portfolio.correlation_distance", corr=corr_arr),
           case("portfolio.inverse_variance_weights", cov=cov_arr)]
    for method in ("single", "complete", "average", "ward"):
        out.append(case("portfolio.hierarchical_risk_parity", cov=cov_arr, method=method))
    out.append(case("portfolio.hierarchical_risk_parity", cov=cov_arr, corr=corr_arr, method="single", _note="explicit corr"))
    names = [f"S{i}" for i in range(n)]
    out.append(case("portfolio.hierarchical_risk_parity", cov=frm(cov, names, names), method="single", _note="DataFrame in, Series out"))
    out.append(case("portfolio.inverse_variance_weights", cov=arr(np.diag([0.04, 0.09, 0.01]))))
    out.append(bad("portfolio.hierarchical_risk_parity", cov=arr(np.ones((3, 4)))))
    out.append(bad("portfolio.inverse_variance_weights", cov=arr(np.diag([0.04, 0.0, 0.01]))))
    return out


def optimizer_cases() -> list[dict]:
    rng = np.random.default_rng(1504)
    n_days, codes = 120, [f"A{i}" for i in range(5)]
    dates = iso(pd.bdate_range("2025-06-02", periods=n_days))
    mu = np.array([0.0008, 0.0004, 0.0006, 0.0002, 0.0005])
    sd = np.array([0.010, 0.015, 0.020, 0.012, 0.008])
    common = rng.normal(0, 0.006, (n_days, 1))
    ret = rd(mu + common * np.array([1.0, 0.8, 1.2, 0.5, 0.7]) + rng.normal(0, 1, (n_days, 5)) * sd)
    returns = frm(ret, dates, codes, True, 8)
    ones = frm(np.ones((n_days, 5)), dates, codes, True)
    mixed = np.ones((n_days, 5))
    mixed[:, 2] = -1.0
    mixed[:, 4] = 0.0
    mixed[100:, 1] = 0.0   # an asset drops out part-way
    mixed_f = frm(mixed, dates, codes, True)
    rec = [59, 60, 61, 80, 100, 119]
    out = []

    def opt(module, entry="optimize", positions=ones, note=None, **params):
        out.append(case(f"optimizers.{module}", entry=entry, lookback=60, params=params, returns=returns, positions=positions,
                        record_rows=rec, _note=note))

    opt("equal_volatility")
    opt("risk_parity")
    opt("mean_variance")
    opt("mean_variance", risk_free=0.0001, note="risk_free")
    opt("max_diversification")
    opt("equal_volatility", positions=mixed_f, note="short, flat and dropped-out assets")
    opt("risk_parity", positions=mixed_f, note="short, flat and dropped-out assets")
    opt("mean_variance", positions=mixed_f, note="short, flat and dropped-out assets")
    opt("max_diversification", positions=mixed_f, note="short, flat and dropped-out assets")
    opt("turnover_aware", entry="class", risk_aversion=5.0, turnover_penalty=0.0, note="gamma 0: mean-variance utility")
    opt("turnover_aware", entry="class", risk_aversion=5.0, turnover_penalty=0.05, max_per_name=0.4,
        groups={"A0": "g1", "A1": "g1", "A2": "g2", "A3": "g2", "A4": "g2"}, max_per_group={"g1": 0.55}, note="caps and penalty")
    opt("turnover_aware", entry="class", positions=mixed_f, risk_aversion=2.0, turnover_penalty=0.01, note="signed positions")
    out.append(bad("optimizers.turnover_aware", entry="class", lookback=60, params={"max_per_name": 1.5}, returns=returns,
                   positions=ones, record_rows=rec))
    return out


def run_optimizer(modname: str, a: dict) -> dict:
    mod = importlib.import_module(f"backtest.optimizers.{modname}")
    ret, pos = revive(a["returns"]), revive(a["positions"])
    params = dict(a["params"])
    extra: dict = {}
    if a["entry"] == "class":
        opt = mod.TurnoverAwareOptimizer(lookback=a["lookback"], **params)
        out = opt.optimize(ret, pos, pos.index)
        extra["realized_turnover"] = list(opt.realized_turnover)
    else:
        out = mod.optimize(ret, pos, pos.index, lookback=a["lookback"], **params)
    rows = a["record_rows"]
    return {"dates": [pos.index[i].strftime("%Y-%m-%d") for i in rows], "codes": list(out.columns),
            "weights": [out.iloc[i].tolist() for i in rows], **extra}


def attribution_cases() -> list[dict]:
    sectors = ["Tech", "Health", "Energy", "Fin", "Util"]
    bw = dict(zip(sectors, [0.30, 0.20, 0.15, 0.25, 0.10]))
    pw = dict(zip(sectors, [0.40, 0.15, 0.10, 0.25, 0.10]))
    p1 = dict(portfolio_weights=pw, benchmark_weights=bw, portfolio_returns=dict(zip(sectors, [0.050, 0.020, -0.010, 0.030, 0.010])),
              benchmark_returns=dict(zip(sectors, [0.040, 0.025, -0.020, 0.028, 0.012])))
    p2 = dict(portfolio_weights=dict(zip(sectors, [0.35, 0.20, 0.15, 0.20, 0.10])), benchmark_weights=bw,
              portfolio_returns=dict(zip(sectors, [-0.020, 0.010, 0.040, -0.015, 0.005])),
              benchmark_returns=dict(zip(sectors, [-0.025, 0.012, 0.030, -0.020, 0.006])))
    p3 = dict(portfolio_weights=pw, benchmark_weights=dict(zip(sectors, [0.25, 0.25, 0.15, 0.25, 0.10])),
              portfolio_returns=dict(zip(sectors, [0.080, -0.030, 0.020, 0.010, 0.000])),
              benchmark_returns=dict(zip(sectors, [0.070, -0.020, 0.025, 0.012, 0.001])))
    out = [case("attribution.brinson_fachler", **p) for p in (p1, p2, p3)]
    out.append(case("attribution.brinson_fachler", portfolio_weights={"A": 0.5, "B": 0.5}, benchmark_weights={"A": 0.5, "B": 0.5},
                    portfolio_returns={"A": 0.02, "B": 0.01}, benchmark_returns={"A": 0.02, "B": 0.01}, _note="no active return"))
    out.append(case("attribution.brinson_fachler", portfolio_weights={"A": 0.6, "B": 0.4, "C": 0.0}, benchmark_weights={"A": 0.5, "B": 0.3, "D": 0.2},
                    portfolio_returns={"A": 0.02, "B": 0.01, "C": 0.0}, benchmark_returns={"A": 0.02, "B": 0.01, "D": 0.03},
                    _note="sectors held on one side only"))
    out.append(bad("attribution.brinson_fachler", portfolio_weights={"A": 0.6, "B": 0.3}, benchmark_weights={"A": 0.5, "B": 0.5},
                   portfolio_returns={"A": 0.02, "B": 0.01}, benchmark_returns={"A": 0.02, "B": 0.01}))
    for pr, br in ((0.05, 0.03), (0.03, 0.03), (-0.04, 0.02), (0.0, 0.0), (0.2, -0.1), (1e-12, 2e-12)):
        out.append(case("attribution.carino_factor", portfolio_return=pr, benchmark_return=br))
    out.append(case("attribution.carino_link", periods=[{"$brinson": p1}, {"$brinson": p2}]))
    out.append(case("attribution.carino_link", periods=[{"$brinson": p1}, {"$brinson": p2}, {"$brinson": p3}]))
    out.append(case("attribution.carino_link", periods=[{"$brinson": p1}], _note="one period"))
    out.append(bad("attribution.carino_link", periods=[]))
    return out


def factormodel_cases() -> list[dict]:
    rng = np.random.default_rng(1506)
    n = 24
    assets = [f"X{i:02d}" for i in range(n)]
    facs = ["value", "momentum", "quality"]
    exp = rd(rng.normal(size=(n, 3)), 8)
    caps = rd(np.exp(rng.normal(22, 1.2, n)), 0)
    true_f = np.array([0.004, -0.002, 0.003])
    rets = rd(0.001 + exp @ true_f + rng.normal(0, 0.01, n), 8)
    raw = rd(rng.normal(size=n) * 3 + rng.standard_t(2, n), 8)
    out = [case("factormodel.standardise_exposures", values=ser(raw, assets, n=8)),
           case("factormodel.standardise_exposures", values=ser(raw, assets, n=8), market_caps=ser(caps, assets, n=0)),
           case("factormodel.standardise_exposures", values=ser(raw, assets, n=8), market_caps=ser(caps, assets, n=0), winsorise=0.1),
           case("factormodel.standardise_exposures", values=ser(raw, assets, n=8), winsorise=0.0),
           bad("factormodel.standardise_exposures", values=ser(raw[:5], assets[:5], n=8)),
           bad("factormodel.standardise_exposures", values=ser(raw, assets, n=8), winsorise=0.6)]
    chars = ["log_market_cap", "book_to_price", "earnings_to_price", "return_12m_ex_1m", "realised_volatility", "turnover",
             "sales_growth", "earnings_growth", "return_on_equity", "gross_profitability", "debt_to_equity"]
    cdata = rd(rng.normal(size=(n, len(chars))), 8)
    out.append(case("factormodel.build_style_exposures", characteristics=frm(cdata, assets, chars, n=8)))
    out.append(case("factormodel.build_style_exposures", characteristics=frm(cdata, assets, chars, n=8), market_caps=ser(caps, assets, n=0)))
    out.append(case("factormodel.build_style_exposures", characteristics=frm(cdata[:, :1], assets, chars[:1], n=8), _note="only one characteristic present"))
    e_frame = frm(exp, assets, facs, n=8)
    out.append(case("factormodel.cross_sectional_factor_returns", returns=ser(rets, assets, n=8), exposures=e_frame, date="2026-03-02"))
    out.append(case("factormodel.cross_sectional_factor_returns", returns=ser(rets, assets, n=8), exposures=e_frame,
                    market_caps=ser(caps, assets, n=0), date="2026-03-02", _note="cap-weighted regression"))
    out.append(bad("factormodel.cross_sectional_factor_returns", returns=ser(rets[:5], assets[:5], n=8), exposures=e_frame))
    hold = rd(rng.dirichlet(np.ones(n)), 10)
    bench = rd(rng.dirichlet(np.ones(n)), 10)
    out.append(case("factormodel.portfolio_style_exposure", holdings=ser(hold, assets), exposures=e_frame))
    out.append(case("factormodel.portfolio_style_exposure", holdings=ser(hold, assets), exposures=e_frame, benchmark=ser(bench, assets),
                    _note="active exposure"))
    out.append(bad("factormodel.portfolio_style_exposure", holdings=ser([], []), exposures=e_frame))
    hist_dates = iso(pd.bdate_range("2025-09-01", periods=24, freq="MS"))
    hist = rd(np.cumsum(rng.normal(0, 0.15, (24, 3)), axis=0) + np.array([0.2, -0.1, 0.0]), 8)
    out.append(case("factormodel.style_drift", exposure_history=frm(hist, hist_dates, facs, True, 8)))
    pe = rd(np.array([0.35, -0.2, 0.6]), 8)
    fr_ = rd(np.array([0.002, 0.001, -0.0015, 0.0003]), 8)
    out.append(case("factormodel.factor_return_attribution", portfolio_exposures=ser(pe, facs, n=8),
                    factor_returns=ser(fr_[:3], facs, n=8), portfolio_return=0.0042))
    out.append(case("factormodel.factor_return_attribution", portfolio_exposures=ser(pe, facs, n=8),
                    factor_returns=ser(np.append(fr_[:3], 0.001), facs + ["market"], n=8), portfolio_return=0.0042,
                    _note="market factor present in the returns"))
    a = rng.normal(size=(3, 3))
    fcov = rd((a @ a.T) * 1e-4, 12)
    spec = rd(rng.uniform(0.01, 0.04, n) ** 2, 10)
    w = rd(rng.dirichlet(np.ones(n)), 10)
    out.append(case("factormodel.factor_risk_decomposition", portfolio_weights=ser(w, assets), exposures=e_frame,
                    factor_cov=frm(fcov, facs, facs, n=12), specific_variances=ser(spec, assets, n=10)))
    out.append(case("factormodel.factor_risk_decomposition", portfolio_weights=ser(w, assets), exposures=e_frame,
                    factor_cov=frm(fcov, facs, facs, n=12), _note="no specific variances"))
    out.append(bad("factormodel.factor_risk_decomposition", portfolio_weights=ser(w, assets), exposures=e_frame,
                   factor_cov=frm(np.array([[1, 2, 0], [0, 1, 0], [0, 0, 1.0]]), facs, facs)))
    dates = iso(pd.bdate_range("2025-06-02", periods=24))
    sig = rng.normal(size=(24, n))
    fwd = rd(0.15 * sig + rng.normal(size=(24, n)), 8)
    sig = rd(sig, 8)
    out.append(case("factormodel.factor_ic_analysis", factor_panel=frm(sig, dates, assets, True, 8),
                    forward_returns=frm(fwd, dates, assets, True, 8), method="spearman"))
    out.append(case("factormodel.factor_ic_analysis", factor_panel=frm(sig, dates, assets, True, 8),
                    forward_returns=frm(fwd, dates, assets, True, 8), method="pearson"))
    out.append(bad("factormodel.factor_ic_analysis", factor_panel=frm(sig[:3], dates[:3], assets, True, 8),
                   forward_returns=frm(fwd[:3], dates[:3], assets, True, 8), method="kendall"))
    return out


def timeseries_cases() -> list[dict]:
    rng = np.random.default_rng(1507)
    n = 250

    def ar1(phi, sd, n_, c=0.0):
        x = np.zeros(n_)
        for i in range(1, n_):
            x[i] = c + phi * x[i - 1] + rng.normal(0, sd)
        return x

    rw = rd(100 + np.cumsum(rng.normal(0, 1, n)), 6)
    rw2 = rd(50 + np.cumsum(rng.normal(0, 0.8, n)), 6)
    stat = rd(ar1(0.6, 1.0, n), 6)
    x = rd(100 + np.cumsum(rng.normal(0, 1, n)), 6)
    y = rd(2.0 + 1.5 * x + ar1(0.5, 0.5, n), 6)
    ou = np.zeros(n)
    ou[0] = 5.0
    for i in range(1, n):
        ou[i] = ou[i - 1] + 0.15 * (5.0 - ou[i - 1]) + 0.3 * rng.normal()
    ou = rd(ou, 8)
    # simulated GARCH(1,1) returns, fractions
    m = 750
    h, e = np.zeros(m), np.zeros(m)
    h[0] = 1e-4
    for i in range(1, m):
        h[i] = 2e-6 + 0.08 * e[i - 1] ** 2 + 0.9 * h[i - 1]
        e[i] = math.sqrt(h[i]) * rng.normal()
    garch_r = rd(0.0003 + e, 8)
    gx, gy = np.zeros(200), np.zeros(200)
    for i in range(1, 200):
        gx[i] = 0.5 * gx[i - 1] + rng.normal()
        gy[i] = 0.4 * gy[i - 1] + 0.5 * gx[i - 1] + rng.normal()
    gframe = frm(np.column_stack([gx, gy]), range(200), ["x", "y"], n=8)
    out = [case("timeseries.adf_test", series=ser(rw, n=6), _note="random walk"),
           case("timeseries.adf_test", series=ser(stat, n=6), _note="stationary AR(1)"),
           case("timeseries.adf_test", series=ser(stat, n=6), significance=0.01),
           bad("timeseries.adf_test", series=ser([1.0], n=6)),
           case("timeseries.cointegration_test", y=ser(y, n=6), x=ser(x, n=6), _note="cointegrated"),
           case("timeseries.cointegration_test", y=ser(rw, n=6), x=ser(rw2, n=6), _note="independent walks"),
           bad("timeseries.cointegration_test", y=ser(y[:100], n=6), x=ser(x, n=6)),
           case("timeseries.compute_half_life", spread=ser(stat, n=6)),
           case("timeseries.compute_half_life", spread=ser(ou, n=8)),
           bad("timeseries.compute_half_life", spread=ser([1.0] * 20)),
           case("timeseries.fit_ornstein_uhlenbeck", series=ser(ou, n=8)),
           case("timeseries.fit_ornstein_uhlenbeck", series=ser(ou, n=8), dt=1 / 252),
           bad("timeseries.fit_ornstein_uhlenbeck", series=ser(ou, n=8), dt=0.0),
           case("timeseries.find_hedge_ratio", y=ser(y, n=6), x=ser(x, n=6)),
           bad("timeseries.find_hedge_ratio", y=ser(y, n=6), x=ser([5.0] * n, n=6)),
           case("timeseries.granger_test", data=gframe, x_col="x", y_col="y", max_lag=3),
           case("timeseries.granger_test", data=gframe, x_col="y", y_col="x", max_lag=3, _note="reverse direction"),
           bad("timeseries.granger_test", data=gframe, x_col="x", y_col="y", max_lag=0),
           bad("timeseries.granger_test", data=gframe, x_col="x", y_col="nope", max_lag=2),
           case("timeseries.fit_garch", returns=ser(garch_r, n=8), horizon=5),
           case("timeseries.fit_garch", returns=ser(garch_r, n=8), horizon=10),
           bad("timeseries.fit_garch", returns=ser(garch_r, n=8), horizon=0)]
    xs = rd(rng.normal(size=(150, 2)), 8)
    ys = 1.0 + xs @ np.array([0.5, -0.3]) + rng.normal(size=150) * (1 + np.abs(xs[:, 0]))
    X = np.column_stack([np.ones(150), xs])
    out.append(case("timeseries.heteroscedasticity_test", model_result={"$ols": {"y": rd(ys, 8).tolist(), "X": rd(X, 8).tolist()}}))
    homo = 1.0 + xs @ np.array([0.5, -0.3]) + rng.normal(size=150)
    out.append(case("timeseries.heteroscedasticity_test", model_result={"$ols": {"y": rd(homo, 8).tolist(), "X": rd(X, 8).tolist()}},
                    significance=0.01, _note="homoskedastic"))
    out.append(case("timeseries.autocorrelation_test", residuals=ser(stat, n=6), lags=10, _note="AR(1) residuals"))
    out.append(case("timeseries.autocorrelation_test", residuals=ser(rng.normal(size=200), n=8), lags=5, _note="white noise"))
    out.append(bad("timeseries.autocorrelation_test", residuals=ser(stat, n=6), lags=0))
    out.append(bad("timeseries.autocorrelation_test", residuals=ser(stat[:8], n=6), lags=10))
    r = rd(rng.normal(0.0006, 0.01, 252), 8)
    out.append(case("timeseries.bootstrap_sharpe", returns=ser(r, n=8), n_bootstrap=500, confidence=0.95, seed=11))
    out.append(case("timeseries.bootstrap_sharpe", returns=ser(r, n=8), n_bootstrap=300, confidence=0.9, periods_per_year=52, seed=5, ddof=0))
    out.append(bad("timeseries.bootstrap_sharpe", returns=ser([], n=8), n_bootstrap=100, seed=1))
    return out


def copula_cases() -> list[dict]:
    rng = np.random.default_rng(1508)
    z = rng.multivariate_normal([0, 0], [[1, 0.6], [0.6, 1]], 25)
    out = [case("copula.pseudo_observations", data=arr(z, 8)),
           case("copula.pseudo_observations", data=arr([[1, 5], [2, 5], [2, 7], [3, 1]]), _note="ties")]
    for th in (0.5, 2.0, 8.0):
        out.append(case("copula.clayton_tail_dependence", theta=th))
    for th in (1.0, 1.5, 4.0):
        out.append(case("copula.gumbel_tail_dependence", theta=th))
    out.append(bad("copula.clayton_tail_dependence", theta=-1.5))
    out.append(bad("copula.gumbel_tail_dependence", theta=0.5))
    uv = [(0.3, 0.7), (0.5, 0.5), (0.05, 0.1), (0.9, 0.95), (1.0, 0.4), (0.4, 1.0)]
    for th in (0.5, 2.0):
        for u, v in uv:
            out.append(case("copula.clayton_copula_cdf", u=u, v=v, theta=th))
    for th in (1.0, 1.8, 3.0):
        for u, v in uv:
            out.append(case("copula.gumbel_copula_cdf", u=u, v=v, theta=th))
    for th in (-4.0, 2.5, 9.0):
        for u, v in uv[:4]:
            out.append(case("copula.frank_copula_cdf", u=u, v=v, theta=th))
    for rho in (-0.7, 0.0, 0.5, 0.95):
        for u, v in uv[:4]:
            out.append(case("copula.gaussian_copula_cdf", u=u, v=v, rho=rho))
    out.append(case("copula.clayton_copula_cdf", u=arr([0.1, 0.4, 0.8]), v=arr([0.2, 0.5, 0.9]), theta=1.5, _note="arrays"))
    out.append(case("copula.gumbel_copula_cdf", u=arr([0.1, 0.4, 0.8]), v=arr([0.2, 0.5, 0.9]), theta=2.0, _note="arrays"))
    out.append(case("copula.frank_copula_cdf", u=arr([0.1, 0.4, 0.8]), v=arr([0.2, 0.5, 0.9]), theta=3.0, _note="arrays"))
    out.append(bad("copula.clayton_copula_cdf", u=0.5, v=0.5, theta=-3.0))
    out.append(bad("copula.clayton_copula_cdf", u=0.0, v=0.5, theta=1.0))
    out.append(bad("copula.gumbel_copula_cdf", u=0.5, v=1.2, theta=2.0))
    out.append(bad("copula.frank_copula_cdf", u=0.5, v=0.5, theta=0.0))
    out.append(bad("copula.gaussian_copula_cdf", u=0.5, v=0.5, rho=1.0))
    for fam in ("clayton", "gumbel", "gaussian"):
        for tau in (0.2, 0.5, 0.8):
            out.append(case("copula.fit_copula_from_tau", tau=tau, family=fam))
    out.append(case("copula.fit_copula_from_tau", tau=-0.4, family="gaussian"))
    out.append(bad("copula.fit_copula_from_tau", tau=-0.4, family="clayton"))
    out.append(bad("copula.fit_copula_from_tau", tau=1.0, family="gumbel"))
    out.append(bad("copula.fit_copula_from_tau", tau=0.3, family="frank"))
    return out


def microstructure_cases() -> list[dict]:
    rng = np.random.default_rng(1509)
    mid = 50 + np.cumsum(rng.normal(0, 0.05, 200))
    px = rd(mid + 0.03 * rng.choice([-1.0, 1.0], 200), 4)
    rets = rd(rng.normal(0, 0.012, 100), 8)
    dvol = rd(rng.uniform(1e6, 5e6, 100), 2)
    dp = rd(rng.normal(0, 0.05, 100), 8)
    flow = rd(rng.normal(0, 1000, 100), 4)
    dp = rd(dp + 0.00002 * flow, 8)
    buy = rd(rng.uniform(800, 1500, 120), 2)
    sell = rd(rng.uniform(700, 1500, 120), 2)
    out = [case("microstructure.roll_effective_spread", prices=list(px)),
           case("microstructure.roll_effective_spread", prices=list(rd(mid, 4)), _note="positive serial covariance"),
           bad("microstructure.roll_effective_spread", prices=[10.0, 10.1]),
           case("microstructure.amihud_illiquidity", returns=list(rets), dollar_volumes=list(dvol)),
           case("microstructure.amihud_illiquidity", returns=list(rets[:20]), dollar_volumes=list(np.r_[dvol[:19], 0.0]), _note="a zero volume"),
           bad("microstructure.amihud_illiquidity", returns=list(rets[:10]), dollar_volumes=list(dvol[:9])),
           case("microstructure.kyles_lambda", price_changes=list(dp), signed_order_flow=list(flow)),
           case("microstructure.kyles_lambda", price_changes=list(dp[:3]), signed_order_flow=[0.0, 0.0, 0.0], _note="no order flow"),
           case("microstructure.vpin", buy_volume=arr(buy, 2), sell_volume=arr(sell, 2), bucket_size=5000.0, n_buckets=10),
           case("microstructure.vpin", buy_volume=arr(buy, 2), sell_volume=arr(sell, 2), bucket_size=2500.0, n_buckets=20),
           bad("microstructure.vpin", buy_volume=arr(buy, 2), sell_volume=arr(sell[:50], 2), bucket_size=5000.0, n_buckets=10),
           bad("microstructure.vpin", buy_volume=arr(buy, 2), sell_volume=arr(sell, 2), bucket_size=0.0, n_buckets=10)]
    return out


def eventstudy_cases() -> list[dict]:
    rng = np.random.default_rng(1510)
    n = 260
    idx = pd.bdate_range("2025-01-01", periods=n)
    mkt = rng.normal(0.0004, 0.010, n)
    syms = ["S0", "S1", "S2", "S3"]
    betas = [1.2, 0.8, 1.0, 0.5]
    data = np.column_stack([0.0002 + b * mkt + rng.normal(0, 0.008, n) for b in betas])
    data[190, 0] += 0.06
    data[210, 1] -= 0.05
    data[235, 2] += 0.03
    data = rd(data, 8)
    mkt = rd(mkt, 8)
    frame = frm(data, iso(idx), syms, True, 8)
    market = ser(mkt, iso(idx), True, 8)
    ev = [["S0", ts(iso(idx)[190])], ["S1", ts(iso(idx)[210])], ["S2", ts(iso(idx)[235])], ["S3", ts(iso(idx)[160])]]
    sframe = frm(data[:40], iso(idx)[:40], syms, True, 8)
    smarket = ser(mkt[:40], iso(idx)[:40], True, 8)
    sev = [["S0", ts(iso(idx)[30])]]
    out = []
    for model in ("market", "market_adjusted", "mean_adjusted"):
        out.append(case("eventstudy.estimate_market_model", asset_returns=list(data[100:220, 0]), market_returns=list(mkt[100:220]), model=model))
        out.append(case("eventstudy.event_study", returns=frame, market_returns=market, events=ev, model=model))
    out.append(case("eventstudy.event_study", returns=frame, market_returns=market, events=ev, event_window=[-3, 3], estimation_window=100,
                    estimation_gap=5, _note="windows"))
    out.append(case("eventstudy.event_study", returns=frame, market_returns=market, events=ev + [["ZZ", ts(iso(idx)[190])]],
                    _note="unknown symbol is dropped"))
    out.append(bad("eventstudy.estimate_market_model", asset_returns=list(data[:10, 0]), market_returns=list(mkt[:10])))
    out.append(bad("eventstudy.estimate_market_model", asset_returns=list(data[:100, 0]), market_returns=list(mkt[:90])))
    out.append(bad("eventstudy.estimate_market_model", asset_returns=list(data[:100, 0]), market_returns=list(mkt[:100]), model="capm"))
    out.append(bad("eventstudy.event_study", returns=sframe, market_returns=smarket, events=[]))
    out.append(bad("eventstudy.event_study", returns=sframe, market_returns=smarket, events=sev, event_window=[5, -5]))
    out.append(bad("eventstudy.event_study", returns=sframe, market_returns=smarket, events=[["ZZ", ts(iso(idx)[30])]]))
    return out


def multipletesting_cases() -> list[dict]:
    rng = np.random.default_rng(1511)
    r = rd(rng.normal(0.0006, 0.01, 252), 8)
    out = [case("multipletesting.sharpe_ratio", returns=list(r)),
           case("multipletesting.sharpe_ratio", returns=list(r), risk_free=0.0001, ddof=0),
           bad("multipletesting.sharpe_ratio", returns=[0.01]),
           case("multipletesting.sharpe_ratio", returns=[0.01, 0.01, 0.01], _note="zero variance")]
    for sr, n, bm, sk, ku in ((0.1, 252, 0.0, 0.0, 3.0), (0.15, 500, 0.05, -0.5, 6.0), (-0.05, 120, 0.0, 0.2, 3.5), (0.3, 60, 0.1, 0.0, 3.0)):
        out.append(case("multipletesting.probabilistic_sharpe_ratio", observed_sharpe=sr, n_observations=n, benchmark_sharpe=bm, skew=sk,
                        kurtosis=ku))
    out.append(bad("multipletesting.probabilistic_sharpe_ratio", observed_sharpe=0.1, n_observations=1))
    for nt, sd in ((1, 0.1), (10, 0.1), (100, 0.2), (1000, 0.15)):
        out.append(case("multipletesting.expected_maximum_sharpe", n_trials=nt, trial_sharpe_std=sd))
    out.append(bad("multipletesting.expected_maximum_sharpe", n_trials=0, trial_sharpe_std=0.1))
    out.append(bad("multipletesting.expected_maximum_sharpe", n_trials=10, trial_sharpe_std=-0.1))
    for sr, nt, n, sd, sk, ku, conf in ((0.2, 50, 500, 0.1, 0.0, 3.0, 0.95), (0.15, 200, 252, 0.08, -0.4, 5.0, 0.95),
                                        (0.3, 10, 1000, 0.15, 0.1, 3.2, 0.99), (0.05, 100, 100, 0.1, 0.0, 3.0, 0.9)):
        out.append(case("multipletesting.deflated_sharpe_ratio", observed_sharpe=sr, n_trials=nt, n_observations=n, trial_sharpe_std=sd,
                        skew=sk, kurtosis=ku, confidence=conf))
    out.append(bad("multipletesting.deflated_sharpe_ratio", observed_sharpe=0.1, n_trials=0, n_observations=100, trial_sharpe_std=0.1))
    p = np.concatenate([rng.uniform(0, 0.002, 4), rng.uniform(0.01, 0.06, 4), rng.uniform(0.05, 1.0, 12)])
    p = rd(p, 8)
    out.append(case("multipletesting.benjamini_hochberg", p_values=list(p), fdr=0.05))
    out.append(case("multipletesting.benjamini_hochberg", p_values=list(p), fdr=0.20))
    out.append(case("multipletesting.benjamini_hochberg", p_values=[0.5, 0.6, 0.9], fdr=0.05, _note="nothing passes"))
    out.append(bad("multipletesting.benjamini_hochberg", p_values=[0.1, 1.5]))
    out.append(bad("multipletesting.benjamini_hochberg", p_values=[], fdr=0.05))
    perf = rng.normal(0.0002, 0.01, (160, 8)) + np.array([0.0, 0.0, 0.0006, 0.0, 0.0003, 0.0, 0.0, 0.0])
    out.append(case("multipletesting.probability_of_backtest_overfitting", performance=arr(perf, 8), n_splits=8))
    out.append(case("multipletesting.probability_of_backtest_overfitting", performance=arr(perf, 8), n_splits=10))
    out.append(case("multipletesting.probability_of_backtest_overfitting", performance=arr(perf[:, :3], 8), n_splits=4, ddof=0))
    out.append(bad("multipletesting.probability_of_backtest_overfitting", performance=arr(perf[:, :1], 8), n_splits=8))
    out.append(bad("multipletesting.probability_of_backtest_overfitting", performance=arr(perf, 8), n_splits=7))
    return out


def regime_cases(mods) -> list[dict]:
    rng = np.random.default_rng(1512)
    n, k = 170, 6
    idx = pd.bdate_range("2025-01-01", periods=n)
    codes = [f"R{i}" for i in range(k)]
    common = rng.normal(0, 0.01, n)
    w = np.zeros(n)
    w[85:] = 1.0   # correlation jumps half-way
    rets = rng.normal(0, 0.008, (n, k)) + (0.9 * w * common)[:, None] * np.linspace(0.8, 1.2, k)
    rets = rd(rets, 8)
    rframe = frm(rets, iso(idx), codes, True, 8)
    dens = mods["regime"].compute_edge_density(pd.DataFrame(rets, index=idx, columns=codes), corr_window=30, edge_threshold=0.5)
    out = [case("regime.compute_edge_density", returns=rframe, corr_window=30, edge_threshold=0.5),
           case("regime.compute_edge_density", returns=rframe, corr_window=20, edge_threshold=0.3),
           case("regime.compute_edge_density", returns=frm(rets[:20, :1], iso(idx)[:20], codes[:1], True, 8), corr_window=10, _note="one asset")]
    dser = ser(dens.to_numpy(), iso(idx), True, 12)
    out.append(case("regime.detect_regimes", density=dser, smooth_window=5, enter_threshold=0.65, exit_threshold=0.45))
    out.append(case("regime.detect_regimes", density=dser, smooth_window=3, enter_threshold=0.5, exit_threshold=0.4))
    out.append(bad("regime.detect_regimes", density=dser, enter_threshold=0.4, exit_threshold=0.5))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    pr = {"$prices": {c: {"index": iso(idx), "close": rd(prices[:, i], 6).tolist()} for i, c in enumerate(codes)}}
    out.append(case("regime.compute_regime_timeline", codes=codes, days=100, corr_window=30, edge_threshold=0.5, smooth_window=5,
                    enter_threshold=0.65, exit_threshold=0.45, price_series=pr))
    out.append(case("regime.compute_regime_timeline", codes=codes, days=400, corr_window=20, edge_threshold=0.4, smooth_window=3,
                    enter_threshold=0.5, exit_threshold=0.3, price_series=pr, _note="window longer than the data"))
    spr = {"$prices": {c: {"index": iso(idx)[:5], "close": rd(prices[:5, i], 6).tolist()} for i, c in enumerate(codes)}}
    out.append(bad("regime.compute_regime_timeline", codes=codes, days=120, exit_threshold=0.7, enter_threshold=0.6, price_series=spr))
    out.append(bad("regime.compute_regime_timeline", codes=codes[:1], days=50,
                   price_series={"$prices": {codes[0]: {"index": iso(idx)[:5], "close": rd(prices[:5, 0], 6).tolist()}}}))
    return out


def risk_xray_cases() -> list[dict]:
    rng = np.random.default_rng(1513)
    n = 260
    idx = pd.bdate_range("2025-02-03", periods=n)
    syms = ["AAA", "BBB", "CCC", "DDD"]
    common = rng.normal(0.0003, 0.006, n)
    r = common[:, None] * np.array([1.0, 0.8, 1.3, 0.4]) + rng.normal(0, 1, (n, 4)) * np.array([0.008, 0.012, 0.015, 0.006])
    closes = rd(np.array([120.0, 45.0, 310.0, 22.0]) * np.cumprod(1 + r, axis=0), 4)
    cf = frm(closes, iso(idx), syms, True, 4)
    w = {"AAA": 0.4, "BBB": 0.3, "CCC": 0.2, "DDD": 0.1}
    sf = frm(closes[:40], iso(idx)[:40], syms, True, 4)
    out = [case("risk_xray.compute_risk_xray", closes=cf, weights=w),
           case("risk_xray.compute_risk_xray", closes=cf, weights={"AAA": 2.0, "BBB": 1.0, "CCC": 1.0}, _note="unnormalised weights"),
           case("risk_xray.compute_risk_xray", closes=cf, weights=w, periods_per_year=None, _note="effective bars per year"),
           case("risk_xray.compute_risk_xray", closes=cf, weights=w, periods_per_year=365, var_levels=[0.9, 0.975]),
           bad("risk_xray.compute_risk_xray", closes=sf, weights={"ZZZ": 1.0}),
           bad("risk_xray.compute_risk_xray", closes=sf, weights={}),
           bad("risk_xray.compute_risk_xray", closes=sf, weights={"AAA": -1.0, "BBB": 1.0}),
           bad("risk_xray.compute_risk_xray", closes=sf, weights=w, min_history=1000)]
    return out


def alpha_t_cases() -> list[dict]:
    out = []
    for m, s, n in ((0.03, 0.1, 100), (-0.02, 0.08, 60), (0.0, 0.1, 50), (0.05, 0.0, 100), (0.05, math.nan, 100), (0.05, 0.1, 0),
                    (0.05, math.inf, 10), (0.04, 0.12, 1)):
        out.append(case("alpha.t_stat", ic_mean=m, ic_std=fl(s), n=n))
    rows = [(0.03, 0.6, 0.1, 100), (0.03, 0.5, 0.1, 100), (0.01, 0.7, 0.1, 100), (-0.03, 0.4, 0.1, 100), (-0.03, 0.4, 0.4, 50),
            (0.025, 0.55, 0.1, 100), (0.03, 0.6, 0.0, 100), (0.03, 0.6, 0.5, 20)]
    for m, p, s, n in rows:
        out.append(case("alpha.categorise", row={"ic_mean": m, "ic_positive_ratio": p, "ic_std": s, "ic_count": n}))
    return out


# --------------------------------------------------------------------------------------------------------------- alpha zoo
def seeded_panel() -> tuple[pd.DatetimeIndex, list[str], dict[str, np.ndarray]]:
    rng = np.random.default_rng(1514)
    n, k = 80, 12
    idx = pd.bdate_range("2025-09-01", periods=n)
    cols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA", "JPM", "XOM", "JNJ", "WMT", "KO"]
    p0 = np.round(rng.uniform(25, 320, k), 2)
    mkt = rng.normal(0.0004, 0.008, n)
    beta = rng.uniform(0.6, 1.5, k)
    idio = rng.uniform(0.008, 0.022, k)
    close = np.zeros((n, k))
    open_ = np.zeros((n, k))
    prev = p0.copy()
    for t in range(n):
        gap = rng.normal(0, 0.004, k)
        open_[t] = prev * (1 + gap)
        intraday = beta * mkt[t] + rng.normal(0, 1, k) * idio
        close[t] = open_[t] * (1 + intraday)
        prev = close[t]
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, (n, k))))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, (n, k))))
    absret = np.abs(close / open_ - 1)
    vol = np.round(np.exp(rng.normal(14.0, 0.35, (n, k))) * (1 + 15 * absret))
    return idx, cols, {"open": np.round(open_, 4), "high": np.round(hi, 4), "low": np.round(lo, 4), "close": np.round(close, 4),
                       "volume": vol}


def mat(df: pd.DataFrame) -> list[list]:
    out = []
    for row in df.to_numpy(dtype=float).tolist():
        out.append([None if math.isnan(x) else ("inf" if x == math.inf else "-inf" if x == -math.inf else round(x, 10)) for x in row])
    return out


def alpha_block() -> tuple[dict, list[str]]:
    idx, cols, arrays = seeded_panel()
    panel = {k: pd.DataFrame(v, index=idx, columns=cols) for k, v in arrays.items()}
    zoo, expected, notes = [], {}, []
    for fam, names in ALPHA_CANDIDATES.items():
        for n in names:
            m = importlib.import_module(f"src.factors.zoo.{fam}.{n}")
            meta = m.__alpha_meta__
            fid = meta["id"]
            try:
                with np.errstate(all="ignore"), warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    out = m.compute({k: v.copy() for k, v in panel.items()})
                if not isinstance(out, pd.DataFrame):
                    raise TypeError(f"returned {type(out).__name__}, not a DataFrame")
                if out.shape != (len(idx), len(cols)):
                    raise ValueError(f"shape {out.shape}")
                out = out.reindex(index=idx, columns=cols)
                if not np.isfinite(out.to_numpy(dtype=float)).any():
                    raise ValueError("no finite value on this panel (warm-up longer than 80 bars)")
            except Exception as e:
                notes.append(f"DROPPED {fid}: {type(e).__name__}: {e}")
                continue
            zoo.append({"id": fid, "family": fam, "file": f"agent/src/factors/zoo/{fam}/{n}.py",
                        "columns_required": list(meta["columns_required"]), "decay_horizon": meta.get("decay_horizon"),
                        "min_warmup_bars": meta.get("min_warmup_bars")})
            expected[fid] = mat(out)
    pnl = {"index": iso(idx), "columns": cols}
    for k, v in arrays.items():
        pnl[k] = v.tolist()
    return {"panel": pnl, "zoo": zoo, "expected": expected, "dropped": notes}, notes


# --------------------------------------------------------------------------------------------------------------- driver
MODS: dict = {}


def run(c: dict, bench) -> dict:
    modname, fname = c["fn"].split(".", 1)
    entry = {k: v for k, v in c.items() if k != "_expect_raise"}
    try:
        if modname == "optimizers":
            entry["result"] = plain(run_optimizer(fname, c["args"]))
        elif modname == "alpha":
            a = revive(c["args"])
            entry["result"] = plain(getattr(bench, fname)(**a))
        else:
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with contextlib.redirect_stdout(io.StringIO()):
                    entry["result"] = plain(getattr(MODS[modname], fname)(**revive(c["args"])))
    except Exception as e:  # recorded: the port must refuse the same inputs
        entry["raises"] = type(e).__name__
        entry["_msg"] = str(e)[:160]
    return entry


def main() -> int:
    root = build_package()
    sys.path.insert(0, str(root))
    for k, v in MODULES.items():
        MODS[k] = importlib.import_module(v)
    bench = bench_helpers()
    builders = [risk_cases, var_backtest_cases, portfolio_cases, optimizer_cases, attribution_cases, factormodel_cases, timeseries_cases,
                copula_cases, microstructure_cases, eventstudy_cases, multipletesting_cases, lambda: regime_cases(MODS), risk_xray_cases,
                alpha_t_cases]
    cases: list[dict] = []
    for b in builders:
        cases.extend(b())
    results, problems = [], []
    for c in cases:
        e = run(c, bench)
        expected = c.get("_expect_raise", False)
        if "raises" in e and not expected:
            problems.append(f"UNEXPECTED RAISE {c['fn']} {c.get('note', '')}: {e['raises']}: {e['_msg']}")
        if "raises" not in e and expected:
            problems.append(f"EXPECTED RAISE BUT RAN {c['fn']} {c['args'] if len(json.dumps(c['args'])) < 200 else '...'}")
        e.pop("_msg", None)
        results.append(e)
    alpha, notes = alpha_block()
    versions = {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__}
    for m in ("scipy", "statsmodels", "arch"):
        versions[m] = importlib.import_module(m).__version__
    data = {"source": "HKUDS/Vibe-Trading@d0db2e3", "versions": versions, "cases": results, "alpha": alpha}
    blob = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    OUT.write_bytes(blob)
    per: dict[str, int] = {}
    for r in results:
        per[r["fn"].split(".")[0]] = per.get(r["fn"].split(".")[0], 0) + 1
    print(f"wrote {len(results)} cases + {len(alpha['zoo'])} factors to {OUT} ({len(blob) / 1e6:.2f} MB)")
    print("cases per module:", per)
    print("raised (recorded):", sum("raises" in r for r in results))
    print("zoo:", [z["id"] for z in alpha["zoo"]])
    print("versions:", versions)
    for line in notes + problems:
        print(line)
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
