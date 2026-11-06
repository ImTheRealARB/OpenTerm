"""Phase 12 step 7 additions: BT EXPORT (CSV parts, Pine translation) and BT compare (no network)."""

import importlib
import time

import pytest


def _export():
    return importlib.import_module("openterm.bt.export")


def _wait(client, job_id, timeout=90.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


def _run(client, rule="SMA20>SMA50", **opts):
    r = client.post("/api/bt/run", json={"rule": rule, "symbols": ["AAPL"], "interval": "1D", "range": "10Y",
                                         "options": opts})
    job = _wait(client, r.json()["id"])
    assert job["state"] == "done", job
    return job["result"]["run_id"]


def test_pine_translates_each_term_and_operator():
    pine = _export().pine_script("EMA12>=EMA26 AND RSI14<30 OR HIGH20>LOW10 AND RET5<0.05 AND CLOSE>100", short=False,
                                 cash=50_000, fees_bps=10, symbols=["AAPL"], interval="1D")
    for text in ("//@version=5", "ta.ema(close, 12) >= ta.ema(close, 26)", "ta.rsi(close, 14) < 30",
                 "ta.highest(high, 20) > ta.lowest(low, 10)", "(close / close[5] - 1) < 0.05", "close > 100",
                 "initial_capital=50000", "commission_value=0.1", 'strategy.close("Long")',
                 "HISTORICAL SIMULATION, NOT A FORECAST"):
        assert text in pine, text
    assert pine.index("//@version=5") < pine.index("strategy(")


def test_pine_cross_is_a_persistent_flag_and_short_reverses():
    pine = _export().pine_script("SMA20 CROSS> SMA50", short=True, cash=1000, fees_bps=0, symbols=["A", "B"], interval="1W")
    assert "var bool cross0 = false" in pine
    assert "cross0 := ta.crossover(ta.sma(close, 20), ta.sma(close, 50)) ? true : ta.crossunder(" in pine
    assert 'strategy.entry("Short", strategy.short)' in pine and "strategy.close" not in pine
    assert "apply it to each one" in pine
    down = _export().pine_script("SMA20 CROSS< SMA50", short=False, cash=1, fees_bps=0, symbols=["A"], interval="1D")
    assert "ta.crossunder(ta.sma(close, 20), ta.sma(close, 50)) ? true : ta.crossover(" in down


def test_csv_parts_and_errors(client):
    rid = _run(client)
    eq = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "csv", "part": "equity"})
    assert eq.headers["content-disposition"].endswith('_equity.csv"') and eq.text.splitlines()[0] == "date,equity,benchmark"
    assert len(eq.text.splitlines()) > 1000
    m = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "csv", "part": "metrics"}).text.splitlines()
    assert m[0] == "metric,value" and any(line.startswith("sharpe,") for line in m)
    trades = client.get(f"/api/bt/runs/{rid}/export", params={"part": "trades"}).text.splitlines()
    assert trades[0].split(",")[:3] == ["symbol", "direction", "entry_time"] and len(trades) > 3
    assert client.get(f"/api/bt/runs/{rid}/export", params={"part": "nope"}).status_code == 400
    assert client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "xls"}).status_code == 400
    assert client.get("/api/bt/runs/nope/export").status_code == 404


def test_pine_from_the_api_carries_the_run_options(client):
    rid = _run(client, "SMA20>SMA50", short=True, fees_bps=5, cash=20_000)
    pine = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "pine"}).text
    assert "initial_capital=20000" in pine and "commission_value=0.05" in pine and 'strategy.entry("Short"' in pine


@pytest.mark.parametrize("params", [{}, {"a": "x"}, {"b": "x"}])
def test_compare_needs_both_ids(client, params):
    assert client.get("/api/bt/compare", params=params).status_code == 400


def test_compare_unknown_run_is_404_and_diff_is_b_minus_a(client):
    a = _run(client, "SMA20>SMA50")
    b = _run(client, "CLOSE>SMA200")
    assert client.get("/api/bt/compare", params={"a": a, "b": "nope"}).status_code == 404
    r = client.get("/api/bt/compare", params={"a": a, "b": b}).json()
    assert r["a"]["equity"] and r["b"]["trades"]
    assert r["diff"]["trade_count"] == r["b"]["metrics"]["trade_count"] - r["a"]["metrics"]["trade_count"]
    assert "unfilled_plan_rejections" not in r["diff"] or isinstance(r["diff"]["unfilled_plan_rejections"], int | float)


def test_csv_cells_cannot_run_as_spreadsheet_formulas():
    """Audit D-3: a trade's symbol or exit reason that starts like a formula is exported as text."""
    from openterm.bt.export import neutralize, run_csv

    assert neutralize("=CMD|' /c calc'!A0") == "'=CMD|' /c calc'!A0"
    assert neutralize("@SUM(1)") == "'@SUM(1)"
    assert neutralize("-evil") == "'-evil" and neutralize("+evil") == "'+evil"
    assert neutralize("-1.5") == "-1.5" and neutralize(-1.5) == -1.5 and neutralize("sma cross") == "sma cross"
    run = {"trades": [{"symbol": "AAPL", "exit_reason": "=1+1", "pnl": -3.2}], "equity": [], "metrics": {}}
    text = run_csv(run, "trades")
    assert "'=1+1" in text and ",-3.2," in text
