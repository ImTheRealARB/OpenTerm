"""BT OPT custom fitness formulas (Phase 26 gap): the safe parser, walk-forward with a formula, and one API run."""

import math
import time

import numpy as np
import pytest

from openterm.bt import fitexpr, overfit

METRICS = {"sharpe": 1.5, "sortino": 2.0, "calmar": 0.8, "annual_return": 0.12, "total_return": 0.5, "max_drawdown": -0.25,
           "profit_factor": 1.8, "win_rate": 0.55, "trade_count": 20, "final_value": 150_000.0}


def score(text: str, metrics=METRICS) -> float:
    return fitexpr.parse(text).from_metrics(metrics)


def test_single_names_equal_the_old_fit_words():
    assert score("SHARPE") == 1.5 and score("sortino") == 2.0 and score("PF") == 1.8
    assert score("NET") == 150_000.0 and score("RETURN") == 0.5


def test_arithmetic_and_precedence():
    assert score("SHARPE-2*DD") == pytest.approx(1.0)  # DD is the POSITIVE depth 0.25, even though max_drawdown is -0.25
    assert score("(SHARPE+SORTINO)/2") == pytest.approx(1.75)
    assert score("-SHARPE + 2**3") == pytest.approx(6.5)
    assert score("SHARPE*0+2**3**2") == 512  # ** is right-associative
    assert score("MIN(1, TRADES/40)*CALMAR") == pytest.approx(0.4)
    assert score("MAX(SHARPE, SORTINO, 0)") == 2.0
    assert score("ABS(-3)+SQRT(16)+LOG(1)+SHARPE*0") == pytest.approx(7.0)


def test_names_are_collected():
    f = fitexpr.parse("sharpe - 2*dd + MIN(trades, 5)")
    assert f.names == {"SHARPE", "DD", "TRADES"} and f.text == "SHARPE - 2*DD + MIN(TRADES, 5)"


def test_cannot_compute_is_nan_not_a_made_up_number():
    assert math.isnan(score("SHARPE/0"))
    assert math.isnan(score("SQRT(-1)+SHARPE"))
    assert math.isnan(score("LOG(0)+SHARPE"))
    assert math.isnan(score("(0-8)**0.5+SHARPE"))  # math.pow, never a complex number
    assert math.isnan(score("10**10**10 + SHARPE"))  # overflow
    assert math.isnan(score("SHARPE", {**METRICS, "sharpe": None}))  # a missing metric
    assert math.isnan(score("SHARPE", {**METRICS, "sharpe": math.nan}))
    assert math.isnan(score("MIN(SHARPE, 1)", {**METRICS, "sharpe": math.nan}))  # NaN poisons MIN / MAX
    assert math.isnan(score("MAX(1, SHARPE)", {**METRICS, "sharpe": math.nan}))


@pytest.mark.parametrize("bad", [
    "", "   ", "1+2",  # no metric name
    "SHARPE +", "SHARPE SORTINO", "((SHARPE)",  # not arithmetic
    "SHARPE.real", "SHARPE[0]", "__import__('os')", "open('x')", "().__class__",  # attribute, subscript, calls
    "SHARPE if 1 else 2", "lambda: 1", "SHARPE > 1", "SHARPE and 1", "not SHARPE",  # not arithmetic operators
    "'SHARPE'", "True + SHARPE", "SHARPE @ SHARPE", "SHARPE // 2", "SHARPE % 2", "SHARPE & 1", "~SHARPE",
    "FOO", "SHARPE + FOO", "EVAL(SHARPE)", "ABS()", "ABS(1, 2)", "MIN(1)", "MAX(SHARPE, key=1)",
    "[SHARPE]", "{SHARPE}", "(SHARPE, 1)", "SHARPE; 1", "x := 1", "1j + SHARPE", "SHARPE\n+1\nimport os",
])
def test_refuses_anything_that_is_not_plain_arithmetic(bad):
    with pytest.raises(fitexpr.FitError):
        fitexpr.parse(bad)


def test_refuses_huge_and_deep_input():
    with pytest.raises(fitexpr.FitError, match="TOO LONG"):
        fitexpr.parse("SHARPE+" * 40 + "1")
    with pytest.raises(fitexpr.FitError):
        fitexpr.parse("(" * 100 + "SHARPE" + ")" * 100)  # ast.parse itself gives up on this one


def test_walk_forward_with_a_formula():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0, 0.004, (240, 3))
    r[:, 2] += 0.01  # column 2 is the best in every slice
    times = list(range(240))
    for fit in ("SHARPE", "SHARPE-2*DD", "RETURN*100", "NET/100000"):
        wf = overfit.walk_forward(r, times, 4, False, fit, 252, 100_000.0)
        assert [w["best"] for w in wf["windows"]] == [2] * 4, fit
    # a formula that is a plain name ranks the same as the old word
    assert overfit.slice_fitness(r[:, 0], "SHARPE*1", 252) == pytest.approx(overfit.slice_fitness(r[:, 0], "SHARPE", 252))
    assert overfit.slice_fitness(r[:, 0], "DD", 252) == pytest.approx(abs((np.cumprod(1 + r[:, 0]) / np.maximum.accumulate(np.cumprod(1 + r[:, 0])) - 1).min()))


# --- API ------------------------------------------------------------------------------------------------------------------

def _wait(client, job_id, timeout=120.0) -> dict:
    end = time.monotonic() + timeout
    job = {"state": "?"}
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


BODY = {"rule": "SMA{10..30:10}>SMA{50..100:50}", "symbols": ["AAPL"], "interval": "1D", "range": "10Y"}


def test_api_formula_fit_ranks_runs(client):
    r = client.post("/api/bt/opt", json={**BODY, "fit": "calmar*min(1,trades/10)"})
    assert r.status_code == 200, r.text
    job = _wait(client, r.json()["id"])
    assert job["state"] == "done", job
    res = job["result"]
    assert res["fit"] == "CALMAR*MIN(1,TRADES/10)" and len(res["runs"]) == 6
    for run in res["runs"]:  # the stored fitness is the formula over that run's own metrics
        m = run["metrics"]
        if run.get("fitness") is not None and m["calmar"] is not None and m["trade_count"] is not None:
            assert run["fitness"] == pytest.approx(m["calmar"] * min(1, m["trade_count"] / 10), abs=1e-6)


def test_api_refuses_a_bad_formula_and_wf_with_trade_names(client):
    bad = client.post("/api/bt/opt", json={**BODY, "fit": "__import__('os')"})
    assert bad.status_code == 400 and "UNKNOWN FUNCTION" in bad.json()["error"]
    bad = client.post("/api/bt/opt", json={**BODY, "fit": "SHARPE+FOO"})
    assert bad.status_code == 400 and "FOO" in bad.json()["error"]
    wf = client.post("/api/bt/opt", json={**BODY, "fit": "SHARPE*MIN(1,TRADES/10)", "wf": 3})
    assert wf.status_code == 400 and "TRADES" in wf.json()["error"]
