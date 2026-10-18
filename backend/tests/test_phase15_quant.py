"""Phase 15 step 2: the ported quant library (`openterm.quantlib`) against Vibe-Trading's OWN output.

tests/fixtures/quant15_vibe_expected.json was produced by running the original files (HKUDS/Vibe-Trading @ d0db2e3) with
scripts/vibe_quant15_crosscheck.py (see its docstring for the argument encodings, replayed by `revive` below). Each case is
{"fn": "<module>.<function>", "args": {...}, "result" | "raises"}; NaN is null, infinities are "inf" / "-inf". The ported modules keep
Vibe's names and signatures, so a case replays as `openterm.quantlib.<module>.<function>(**args)` with three exceptions the script's driver
defines: `optimizers.<module>` cases call that optimizer module's `optimize(...)` (or `TurnoverAwareOptimizer(...).optimize`) and compare the
weight rows at `record_rows`; `alpha.t_stat` / `alpha.categorise` live in `openterm.quantlib.alpha.bench`; `regime` and `risk_xray` are
`openterm.quantlib.regime` / `.risk_xray`. The alpha zoo is replayed from `alpha.panel` against `alpha.expected` (NaN positions must match).
Closed forms must agree to 1e-9 relative; fitted or iterative results (GARCH, GPD tail, optimizers, statsmodels tests) to the looser tolerance
in TOLERANCE. The server never imports any of this (test_phase15.py guards that). Strict xfail until step 2 lands: that step deletes the marker.
"""

import dataclasses
import importlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIX = Path(__file__).parent / "fixtures"
DATA = json.loads((FIX / "quant15_vibe_expected.json").read_bytes().decode("utf-8"))
CASES = DATA["cases"]
ALPHA = DATA["alpha"]


def xf(group: str, step: int):
    return pytest.mark.xfail(strict=True, reason=f"Phase 15 step {step}: {group}")


QUANT = xf("quantlib ports", 2)

TOLERANCE = {"timeseries.fit_garch": 1e-4, "risk.fit_gpd_tail": 1e-5, "timeseries.fit_ornstein_uhlenbeck": 1e-6,
             "timeseries.cointegration_test": 1e-6, "timeseries.adf_test": 1e-6, "timeseries.granger_test": 1e-6,
             "timeseries.find_hedge_ratio": 1e-7, "timeseries.heteroscedasticity_test": 1e-6, "optimizers": 1e-5,
             "factormodel.factor_risk_decomposition": 1e-7, "timeseries.bootstrap_sharpe": 1e-7, "regime": 1e-9}
DEFAULT_TOL = 1e-9
EXCEPTIONS = {"ValueError": ValueError, "KeyError": KeyError, "TypeError": TypeError, "ZeroDivisionError": ZeroDivisionError,
              "ImportError": ImportError, "IndexError": IndexError, "AssertionError": AssertionError}


def lib(name: str):
    return importlib.import_module(f"openterm.quantlib.{name}")


def nan_list(v):
    if isinstance(v, list):
        out = [nan_list(x) for x in v]
        return [float("nan") if x is None else x for x in out] if any(isinstance(x, int | float) for x in out) else out
    return v


def to_index(idx, date_index: bool):
    return pd.DatetimeIndex(pd.to_datetime(idx)) if date_index else (idx if idx is not None else None)


def revive(v):
    """Decodes the script's argument encodings (docstring of scripts/vibe_quant15_crosscheck.py)."""
    if isinstance(v, list):
        return nan_list([revive(x) for x in v])
    if not isinstance(v, dict):
        return v
    if "$array" in v:
        return np.array(nan_list(v["$array"]), dtype=float)
    if "$series" in v:
        s = v["$series"]
        vals = nan_list(s["values"])
        return pd.Series(vals, index=to_index(s.get("index"), s.get("date_index", False)), name=s.get("name"), dtype=float)
    if "$frame" in v:
        f = v["$frame"]
        data = [[float("nan") if x is None else x for x in row] for row in f["data"]]
        return pd.DataFrame(data, index=to_index(f["index"], f.get("date_index", False)), columns=f["columns"])
    if "$ts" in v:
        return pd.Timestamp(v["$ts"])
    if "$float" in v:
        return float(v["$float"])
    if "$ols" in v:
        import statsmodels.api as sm

        return sm.OLS(np.array(v["$ols"]["y"], float), np.array(v["$ols"]["X"], float)).fit()
    if "$brinson" in v:
        return lib("attribution").brinson_fachler(**revive(v["$brinson"]))
    if "$prices" in v:
        return {code: pd.DataFrame({"close": p["close"]}, index=pd.DatetimeIndex(pd.to_datetime(p["index"]))) for code, p in v["$prices"].items()}
    return {k: revive(x) for k, x in v.items() if not k.startswith("_")}


def norm(x):
    """Result encodings of the script: Series -> list or {label: value}, DataFrame -> {index, columns, data}, dataclass -> dict."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: norm(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, pd.DataFrame):
        return {"index": [str(i)[:10] if isinstance(i, pd.Timestamp) else i for i in x.index], "columns": list(map(str, x.columns)),
                "data": x.to_numpy(float).tolist()}
    if isinstance(x, pd.Series):
        if isinstance(x.index, pd.RangeIndex):
            return [norm(v) for v in x.tolist()]
        return {str(k)[:10] if isinstance(k, pd.Timestamp) else str(k): norm(v) for k, v in x.items()}
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    if isinstance(x, dict):
        return {str(k): norm(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [norm(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return x


def approx_tree(got, want, rel: float, path: str = ""):
    if isinstance(want, dict):
        assert isinstance(got, dict), f"{path}: {type(got).__name__} is not a mapping"
        for k, w in want.items():
            assert k in got, f"{path}.{k} missing"
            approx_tree(got[k], w, rel, f"{path}.{k}")
    elif isinstance(want, list):
        assert isinstance(got, list | tuple), f"{path}: {type(got).__name__} is not a list"
        assert len(got) == len(want), f"{path}: {len(got)} != {len(want)}"
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            approx_tree(g, w, rel, f"{path}[{i}]")
    elif want is None:
        assert got is None or (isinstance(got, float) and math.isnan(got)), f"{path}: {got!r} should be NaN"
    elif want in ("inf", "-inf"):
        assert got == float(want), path
    elif isinstance(want, bool | str):
        assert got == want, f"{path}: {got!r} != {want!r}"
    else:
        assert isinstance(got, int | float | np.number), f"{path}: {got!r}"
        assert float(got) == pytest.approx(float(want), rel=rel, abs=1e-12), path


def tolerance(fn: str) -> float:
    return TOLERANCE.get(fn, TOLERANCE.get(fn.split(".")[0], DEFAULT_TOL))


def replay(case: dict):
    mod, name = case["fn"].split(".", 1)
    args = revive(case["args"])
    if mod == "optimizers":
        m = lib(f"optimizers.{name}")
        ret, pos = args["returns"], args["positions"]
        if args["entry"] == "class":
            opt = m.TurnoverAwareOptimizer(lookback=args["lookback"], **args["params"])
            out = opt.optimize(ret, pos, pos.index)
            extra = {"realized_turnover": list(opt.realized_turnover)}
        else:
            out = m.optimize(ret, pos, pos.index, lookback=args["lookback"], **args["params"])
            extra = {}
        rows = args["record_rows"]
        return {"dates": [pos.index[i].strftime("%Y-%m-%d") for i in rows], "codes": list(out.columns),
                "weights": [out.iloc[i].tolist() for i in rows], **extra}
    if mod == "alpha":
        return getattr(lib("alpha.bench"), name)(**args)
    return getattr(lib(mod), name)(**args)


def ident(i_case):
    i, c = i_case
    return f"{c['fn']}#{i}"


@QUANT
@pytest.mark.parametrize("i_case", list(enumerate(CASES)), ids=ident)
def test_port_matches_vibe(i_case):
    _, case = i_case
    if "raises" in case:
        with pytest.raises(EXCEPTIONS.get(case["raises"], Exception)):
            replay(case)
        return
    approx_tree(norm(replay(case)), case["result"], tolerance(case["fn"]), case["fn"])


def test_the_cases_cover_every_ported_module():
    modules = {c["fn"].split(".")[0] for c in CASES}
    assert modules >= {"risk", "var_backtest", "portfolio", "optimizers", "attribution", "factormodel", "timeseries", "copula",
                       "microstructure", "eventstudy", "multipletesting", "regime", "risk_xray", "alpha"}
    assert len(CASES) > 350 and any("raises" in c for c in CASES)


# --- the alpha zoo ----------------------------------------------------------------------------------------------------------------------

def panel() -> dict:
    p = ALPHA["panel"]
    idx = pd.DatetimeIndex(pd.to_datetime(p["index"]))
    return {k: pd.DataFrame(p[k], index=idx, columns=p["columns"], dtype=float) for k in ("open", "high", "low", "close", "volume")}


@QUANT
def test_zoo_ids_are_pinned():
    from openterm.quantlib.alpha import ZOO

    assert [f["id"] for f in ZOO] == [z["id"] for z in ALPHA["zoo"]]
    assert 24 <= len(ZOO) <= 30
    assert {f["family"] for f in ZOO} <= {"alpha101", "qlib158", "academic"}


@QUANT
@pytest.mark.parametrize("zoo", ALPHA["zoo"], ids=lambda z: z["id"])
def test_zoo_factor_matches_vibes_values(zoo):
    from openterm.quantlib.alpha import compute_factor

    got = compute_factor(zoo["id"], panel())
    want = np.array(ALPHA["expected"][zoo["id"]], dtype=object)
    want = np.array([[np.nan if x is None else x for x in row] for row in want], dtype=float)
    assert got.shape == want.shape, zoo["id"]
    g = got.to_numpy(float)
    assert np.array_equal(np.isnan(g), np.isnan(want)), f"{zoo['id']}: NaN positions differ"
    assert np.allclose(g, want, rtol=1e-8, atol=1e-10, equal_nan=True), zoo["id"]
