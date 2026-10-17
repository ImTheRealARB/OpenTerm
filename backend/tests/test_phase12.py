"""Phase 12: backtester `BT` (spec: docs/specs/PHASE_12.md).

Written before the code. Each group is strict-xfail until its build step lands; that step deletes the marker.
Modules (and pandas, a worker-only dependency added in step 3) are imported inside the tests, so a missing module
fails one test, not the whole collection.

Expected numbers come from two places:
- hand computation, written out next to the assertion;
- `fixtures/bt_vibe_expected.json`, produced by running Vibe-Trading's own engine at commit d0db2e3 on the same
  input (`scripts/vibe_crosscheck.py`, which also documents how the input frames are built).
"""

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

VALID = pytest.mark.xfail(strict=True, reason="Phase 12 step 6 (BT MC, BT WF) not built")
RUNS = pytest.mark.xfail(strict=True, reason="Phase 12 step 7 (BT RUNS compare, BT EXPORT) not built")
IMPORT = pytest.mark.xfail(strict=True, reason="Phase 12 step 8 (IMPORT) not built")

FIX = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIX / "bt_vibe_expected.json").read_bytes().decode("utf-8"))
CASES = EXPECTED["cases"]
REL = 1e-6


def mod(name: str):
    return importlib.import_module(name)


def body(name: str):
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))["body"]


def frames(case: dict):
    pd = mod("pandas")
    out = {}
    for sym, f in case["bars"].items():
        cols = {k: v for k, v in f.items() if k != "index"}
        out[sym] = pd.DataFrame(cols, index=pd.to_datetime(f["index"]), dtype=float)
    return out


def signals(case: dict, data_map: dict):
    pd = mod("pandas")
    return {s: pd.Series(v, index=data_map[s].index, dtype=float) for s, v in case["signals"].items()}


def assert_metrics(got: dict, want: dict):
    for k, v in want.items():
        if v is None:
            assert got.get(k) is None, k
        else:
            assert got[k] == pytest.approx(v, rel=REL, abs=1e-6), k


def assert_run(res, case: dict):
    """res: BacktestResult (equity: pd.Series, trades: list of TradeRecord, metrics: dict)."""
    assert len(res.equity) == case["equity_points"]
    for day, value in case["equity_at"]:
        assert float(res.equity.loc[day]) == pytest.approx(value, rel=REL)
    if case.get("equity"):
        assert [round(float(x), 6) for x in res.equity] == pytest.approx([v for _, v in case["equity"]], rel=REL)
    assert len(res.trades) == case["trade_count"]
    picked = res.trades if len(res.trades) <= 12 else res.trades[:3] + res.trades[-3:]
    for t, w in zip(picked, case["trades"], strict=True):
        assert (t.symbol, int(t.direction), t.exit_reason) == (w["symbol"], w["direction"], w["exit_reason"])
        assert t.entry_time.strftime("%Y-%m-%d") == w["entry_time"] and t.exit_time.strftime("%Y-%m-%d") == w["exit_time"]
        for k in ("entry_price", "exit_price", "size", "pnl", "commission"):
            assert getattr(t, k) == pytest.approx(w[k], rel=REL, abs=1e-6), k
    assert_metrics(res.metrics, case["metrics"])


def run_case(name: str, engine: str, bars_per_year: int = 252):
    case = CASES[name]
    data = frames(case)
    return mod("openterm.bt.engine").backtest(data, signals(case, data), case["config"], engine=engine,
                                              bars_per_year=bars_per_year), case


def _wait(client, job_id, timeout=90.0) -> dict:
    end = time.monotonic() + timeout  # first BT job also spawns a worker that imports pandas
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


def bt_run(client, **req) -> dict:
    r = client.post("/api/bt/run", json=req)
    assert r.status_code == 200, r.text
    return _wait(client, r.json()["id"])


# --- guard: the server process never imports numpy/pandas (decision B) -----------------------------------------

def test_server_never_imports_pandas(tmp_path):
    code = (
        "import sys\n"
        "from fastapi.testclient import TestClient\n"
        "from openterm.main import app\n"
        "with TestClient(app) as c:\n"
        "    assert c.get('/api/health').status_code == 200\n"
        "    c.get('/api/keys'); c.get('/api/sources'); c.get('/api/jobs')\n"
        "bad = [m for m in ('pandas', 'numpy') if m in sys.modules]\n"
        "print('LOADED', bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    env = {**os.environ, "OPENTERM_FIXTURES": "1", "OPENTERM_DB_PATH": str(tmp_path / "g.db"),
           "OPENTERM_KEYRING": "memory", "OPENTERM_DOTENV_PATH": str(tmp_path / "k.env")}
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=False,
                       cwd=Path(__file__).parents[1])
    assert r.returncode == 0, r.stdout + r.stderr


# --- 1. Frames from the recorded fixtures ------------------------------------------------------------------------

def test_yahoo_frame_matches_the_crosscheck_input():
    f = mod("openterm.bt.frames").from_yahoo_chart(body("yahoo_chart_aapl_10y_1d"))
    assert list(f.columns[:5]) == ["open", "high", "low", "close", "volume"] and "adj_close" in f.columns
    assert f.index.is_monotonic_increasing and not f.index.has_duplicates and f.index.tz is None
    case = CASES["aapl_sma20_gt_sma50"]
    assert len(f) == case["equity_points"]  # no warm-up: one equity point per bar
    assert f.index[0].strftime("%Y-%m-%d") == case["equity_at"][0][0]
    assert f.index[-1].strftime("%Y-%m-%d") == case["equity_at"][-1][0]


# --- 2. Engine core (global equity, US) --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["us_long_then_short", "us_two_symbols_hold", "us_two_symbols_rebalance",
                                  "us_warmup_3"])
def test_us_engine_matches_vibe_on_synthetic_bars(name):
    res, case = run_case(name, "us")
    assert_run(res, case)


def test_us_long_then_short_by_hand():
    # signals [0,1,1,1,0,-1,-1,0] act one bar later at the open; opens 100..107, closes open+0.5, slippage 0.1%.
    res, _ = run_case("us_long_then_short", "us")
    long_, short = res.trades
    assert long_.entry_price == pytest.approx(102 * 1.001)             # bar 2 open, paid up
    assert long_.size == pytest.approx(97.94)                          # 10,000 / 102.102 rounded to 0.01
    assert long_.exit_price == pytest.approx(105 * 0.999)              # bar 5 open, sold down
    assert long_.pnl == pytest.approx(97.94 * (105 * 0.999 - 102 * 1.001))
    assert short.direction == -1 and short.entry_price == pytest.approx(106 * 0.999)
    assert short.exit_reason == "end_of_backtest" and short.exit_price == pytest.approx(107.5 * 1.001)  # last close


def test_aapl_sma_cross_matches_vibe():
    case = CASES["aapl_sma20_gt_sma50"]
    data = {"AAPL": mod("openterm.bt.frames").from_yahoo_chart(body(case["fixture"]))}
    rules = mod("openterm.bt.rules")
    sig = rules.signals(rules.parse("SMA20>SMA50"), data)
    res = mod("openterm.bt.engine").backtest(data, sig, case["config"], engine="us")
    assert_run(res, case)


def test_metrics_on_a_fixed_curve():
    pd = mod("pandas")
    m = EXPECTED["metrics_fixed_curve"]
    curve = pd.Series(m["equity"], index=pd.bdate_range(m["start"], periods=len(m["equity"])))
    got = mod("openterm.bt.metrics").calc_metrics(curve, [], 100.0, 252, pd.Series(0.0, index=curve.index))
    assert got["total_return"] == pytest.approx(0.155)                  # 115.5 / 100 - 1
    assert got["max_drawdown"] == pytest.approx(99 / 110 - 1)           # 110 -> 99
    assert_metrics(got, m["metrics"])



def test_tail_risk_var_es_95():
    pd = mod("pandas")
    # 21 bars -> 20 returns: -5%, -3%, then eighteen +1%. 5th percentile (linear) of 20 values sits at
    # position 0.95: -5% + 0.95 * (-3% - -5%) = -3.1%; ES = mean of returns <= -3.1% = -5%.
    eq = [100.0, 95.0, 92.15]
    for _ in range(18):
        eq.append(eq[-1] * 1.01)
    got = mod("openterm.bt.job").tail_risk(pd.Series(eq))
    assert got["var_95"] == pytest.approx(-0.031)
    assert got["es_95"] == pytest.approx(-0.05)
    assert mod("openterm.bt.job").tail_risk(pd.Series(eq[:10])) == {"var_95": None, "es_95": None}


# --- 3. Rule syntax ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["SMA20>SMA50", "CLOSE>SMA200", "RSI14<30", "EMA12 CROSS> EMA26",
                                  "RSI14<30 AND CLOSE>SMA200", "RET20>0.05 OR HIGH20<=CLOSE", "sma20 > sma50"])
def test_rule_parser_accepts(text):
    mod("openterm.bt.rules").parse(text)


@pytest.mark.parametrize(("text", "col"), [
    ("SMA20>>SMA50", 6),     # second '>' (0-based column of the offending character)
    ("FOO>1", 0),            # unknown term
    ("SMA0>CLOSE", 0),       # period must be >= 1
    ("SMA20", 5),            # comparison missing at the end
    ("SMA20>SMA50 AND", 15),  # dangling AND
    ("RSI14<", 6),
])
def test_rule_parser_rejects_with_column(text, col):
    rules = mod("openterm.bt.rules")
    with pytest.raises(rules.RuleError) as e:
        rules.parse(text)
    assert e.value.col == col and str(e.value)


def test_bt_command_arguments():
    parse = mod("openterm.bt.rules").parse_command
    a = parse(["AAPL", "SMA20>SMA50", "1D", "5Y"])
    assert (a.symbols, a.rule, a.interval, a.range, a.short) == (["AAPL"], "SMA20>SMA50", "1D", "5Y", False)
    b = parse(["SPY,QQQ", "RSI14<30", "1D", "10Y", "SHORT", "FEES=5", "SLIP=5", "CASH=50000", "BENCH=SPY"])
    assert b.symbols == ["SPY", "QQQ"] and b.short and (b.fees_bps, b.slip_bps, b.cash, b.bench) == (5, 5, 50000, "SPY")
    with pytest.raises(mod("openterm.bt.rules").RuleError):
        parse(["AAPL", "SMA20>SMA50", "FEES=-1"])


def test_rule_signals_match_hand_written_indicators():
    pd = mod("pandas")
    np = mod("numpy")
    data = {"AAPL": mod("openterm.bt.frames").from_yahoo_chart(body("yahoo_chart_aapl_10y_1d"))}
    close = data["AAPL"]["close"]
    rules = mod("openterm.bt.rules")
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    lo = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + g / lo)  # Wilder
    want = pd.Series(np.where(rsi.isna(), 0.0, np.where(rsi < 30, 1.0, 0.0)), index=close.index)
    got = rules.signals(rules.parse("RSI14<30"), data)["AAPL"]
    assert (got.values == want.values).all()
    short = rules.signals(rules.parse("SMA20>SMA50"), data, short=True)["AAPL"]
    assert set(short.iloc[60:].unique()) <= {1.0, -1.0} and (short.iloc[:49] == 0).all()  # NaN warm-up stays flat


def test_cross_waits_for_an_actual_cross():
    pd = mod("pandas")
    idx = pd.bdate_range("2024-01-01", periods=8)
    close = [10, 11, 12, 9, 8, 12, 13, 9]  # starts above 9.5, dips below, crosses back up at bar 5, down at bar 7
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0}, index=idx, dtype=float)
    rules = mod("openterm.bt.rules")
    got = rules.signals(rules.parse("CLOSE CROSS> 9.5"), {"X": df})["X"]
    assert list(got) == [0, 0, 0, 0, 0, 1, 1, 0]  # latched from the up-cross until the down-cross


# --- 4. Sandbox --------------------------------------------------------------------------------------------------

GOOD = '''
import numpy as np
import pandas as pd

class SignalEngine:
    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            fast = df["close"].rolling(20).mean()
            slow = df["close"].rolling(50).mean()
            out[sym] = pd.Series(np.where(fast > slow, 1.0, 0.0), index=df.index)
        return out
'''


@pytest.mark.parametrize("snippet", [
    "import os", "import socket", "import subprocess", "from pathlib import Path", "import importlib",
    "x = open('C:/Windows/win.ini').read()", "__import__('os')", "eval('1')", "exec('x=1')",
    "compile('1', 'f', 'eval')", "y = ().__class__.__bases__", "getattr(object, '__subclasses__')",
    "import pandas as pd\nx = pd.read_csv('http://127.0.0.1:9/x.csv')", "import numpy as np\nnp.load('x.npy')",
    "import pandas as pd\npd.DataFrame().to_csv('x.csv')", "globals()", "@staticmethod\ndef f():\n    pass",
])
def test_sandbox_rejects(snippet):
    sb = mod("openterm.bt.sandbox")
    with pytest.raises(sb.SandboxError):
        sb.check(snippet + "\n" + GOOD)


def test_sandbox_accepts_a_plain_strategy():
    mod("openterm.bt.sandbox").check(GOOD)


# --- 5. API, jobs and storage ------------------------------------------------------------------------------------

def test_bt_run_rule_through_the_api_matches_vibe(client):
    case = CASES["aapl_sma20_gt_sma50"]
    job = bt_run(client, rule="SMA20>SMA50", symbols=["AAPL"], interval="1D", range="10Y",
                 options={"cash": 100_000, "adjusted": False})
    assert job["state"] == "done", job
    run = client.get(f"/api/bt/runs/{job['result']['run_id']}").json()
    assert_metrics(run["metrics"], case["metrics"])
    assert len(run["equity"]) == case["equity_points"] and len(run["trades"]) == case["trade_count"]
    labels = run["labels"]
    assert labels["headline"] == "HISTORICAL SIMULATION, NOT A FORECAST" and labels["prices"] == "RAW"
    assert labels["engine"] == "us" and labels["sources"][0]["name"].startswith("yahoo")
    assert {"fees_bps", "slip_bps", "warmup_bars"} <= set(labels)

    t0 = time.perf_counter()
    again = client.post("/api/bt/run", json={"rule": "SMA20>SMA50", "symbols": ["AAPL"], "interval": "1D",
                                             "range": "10Y", "options": {"cash": 100_000, "adjusted": False}}).json()
    assert again["cached"] is True and again["state"] == "done" and (time.perf_counter() - t0) < 0.5
    assert again["run_id"] == job["result"]["run_id"]  # the panel opens a cached run straight from the POST
    assert again["run"]["id"] == again["run_id"] and len(again["run"]["equity"]) > 2000


def test_bt_run_default_uses_adjusted_closes(client):
    job = bt_run(client, rule="SMA20>SMA50", symbols=["AAPL"], interval="1D", range="10Y")
    run = client.get(f"/api/bt/runs/{job['result']['run_id']}").json()
    assert run["labels"]["prices"] == "ADJ"
    assert run["metrics"]["final_value"] != pytest.approx(CASES["aapl_sma20_gt_sma50"]["metrics"]["final_value"])


def test_bt_run_bad_rule_is_a_400_with_the_column(client):
    r = client.post("/api/bt/run", json={"rule": "SMA20>>SMA50", "symbols": ["AAPL"], "interval": "1D", "range": "5Y"})
    assert r.status_code == 400 and r.json()["col"] == 6


def test_bt_run_unknown_symbol_fails_before_the_job(client):
    r = client.post("/api/bt/run", json={"rule": "SMA20>SMA50", "symbols": ["ZZZZNOPE"], "interval": "1D",
                                         "range": "5Y"})
    assert r.status_code == 404 and "ZZZZNOPE" in r.text and client.get("/api/jobs").json()["jobs"] == []


def test_python_strategy_save_run_delete(client):
    assert client.put("/api/bt/strategies/mysma", json={"code": GOOD}).status_code == 200
    assert "mysma" in [s["name"] for s in client.get("/api/bt/strategies").json()["strategies"]]
    bad = client.put("/api/bt/strategies/evil", json={"code": "import os\n" + GOOD})
    assert bad.status_code == 400 and "os" in bad.json()["detail"]
    job = bt_run(client, strategy="mysma", symbols=["AAPL"], interval="1D", range="10Y",
                 options={"cash": 100_000, "adjusted": False})
    assert job["state"] == "done", job
    # GOOD is the same rule as SMA20>SMA50 written by hand (rolling means, NaN compares False -> 0)
    run = client.get(f"/api/bt/runs/{job['result']['run_id']}").json()
    assert run["metrics"]["final_value"] == pytest.approx(CASES["aapl_sma20_gt_sma50"]["metrics"]["final_value"], rel=REL)
    assert client.delete("/api/bt/strategies/mysma").status_code == 200


@pytest.mark.parametrize(("code", "error"), [
    ("class SignalEngine:\n    def generate(self, data_map):\n        while True:\n            pass\n", "TIME LIMIT"),
    ("class SignalEngine:\n    def generate(self, data_map):\n        x = bytearray(600_000_000)\n        return {}\n",
     "MEMORY LIMIT"),
    (("import pandas as pd\nclass SignalEngine:\n    def generate(self, data_map):\n"
      "        return {k: pd.Series(1.0, index=v.index) for k, v in data_map.items() if k == 'NOPE'}\n"),
     "NO SIGNALS"),
])
def test_runtime_limits_fail_closed(client, code, error):
    limit = 3 if error == "TIME LIMIT" else 60  # the limit also covers the worker's pandas import (seconds under load)
    job = bt_run(client, code=code, symbols=["AAPL"], interval="1D", range="10Y",
                 options={"time_limit_s": limit, "memory_limit_mb": 300})
    assert job["state"] == "error" and error in job["error"]
    ok = bt_run(client, rule="SMA20>SMA50", symbols=["AAPL"], interval="1D", range="10Y")
    assert ok["state"] == "done"  # the pool recovered


def test_runs_are_listed_fetched_and_deleted(client):
    job = bt_run(client, rule="CLOSE>SMA200", symbols=["AAPL"], interval="1D", range="10Y")
    rid = job["result"]["run_id"]
    cards = client.get("/api/bt/runs").json()["runs"]
    card = next(c for c in cards if c["id"] == rid)
    assert card["symbols"] == ["AAPL"] and card["rule"] == "CLOSE>SMA200" and "total_return" in card["metrics"]
    assert "equity" not in card  # cards stay small
    assert client.delete(f"/api/bt/runs/{rid}").status_code == 200
    assert client.get(f"/api/bt/runs/{rid}").status_code == 404


def test_migration_9_tables(client):
    async def tables():
        async with client.app.state.userdata.db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            return {r[0] for r in await cur.fetchall()}

    assert {"strategies", "bt_runs"} <= client.portal.call(tables)


def test_keyring_is_installed():
    import importlib.util

    assert importlib.util.find_spec("keyring") is not None  # decision M: APIKEYS writes to the OS keyring


# --- 6. Other engines (step 5) -----------------------------------------------------------------------------------

def test_india_cost_stack_by_hand():
    e = mod("openterm.bt.engines.india_equity").IndiaEquityEngine({})
    # notional 100,000: exchange 2.97 + SEBI 0.10 + GST 18% of 3.07 = 0.5526 + STT 100; buy adds stamp 15
    assert e.calc_commission(40, 2500.0, 1, True) == pytest.approx(118.6226)
    assert e.calc_commission(40, 2500.0, 1, False) == pytest.approx(103.6226)
    assert e.round_size(10.7, 100.0) == 10.0


def test_uk_sdrt_rounds_half_up_on_purchases_only():
    e = mod("openterm.bt.engines.global_equity").GlobalEquityEngine({}, market="uk")
    assert e.calc_commission(333, 3.015, 1, True) == 5.02     # 1,003.995 x 0.5% = 5.019975 -> 5.02
    assert e.calc_commission(333, 3.015, 1, False) == 0.0     # selling a long: no SDRT
    assert e.calc_commission(333, 3.015, -1, False) == 5.02   # buying to cover a short pays it


def test_crypto_funding_on_a_daily_bar():
    pd = mod("pandas")
    hooks = mod("openterm.bt.engines.hooks")
    pos = mod("openterm.bt.models").Position(symbol="BTCUSDT", direction=1, entry_price=100.0,
                                              entry_time=pd.Timestamp("2024-01-01"), size=2.0)
    bar = pd.Series({"close": 100.0, "funding_rate": 0.0001})
    fee = hooks.calc_crypto_funding_fee("BTCUSDT", bar, pd.Timestamp("2024-01-02"), {"BTCUSDT": pos}, 0.0005,
                                        set(), set(), bar_span_hours=24)
    assert fee == pytest.approx(200 * 0.0001 * 3)  # notional x bar rate x three 8-hour settlements


@pytest.mark.parametrize(("name", "engine"), [("india_one_trade", "india"), ("forex_eurusd", "forex"),
                                              ("futures_es", "futures")])
def test_engines_match_vibe_on_synthetic_bars(name, engine):
    res, case = run_case(name, engine)
    assert_run(res, case)


def test_reliance_rsi_matches_vibe():
    case = CASES["reliance_rsi14_lt_30"]
    data = {"RELIANCE.NS": mod("openterm.bt.frames").from_yahoo_chart(body(case["fixture"]))}
    rules = mod("openterm.bt.rules")
    res = mod("openterm.bt.engine").backtest(data, rules.signals(rules.parse("RSI14<30"), data), case["config"],
                                             engine="india")
    assert_run(res, case)


def test_btc_perp_matches_vibe():
    case = CASES["btc_perp_sma_cross_short"]
    f = mod("openterm.bt.frames").from_binance_perp(body("binance_perp_klines_btcusdt_1d"),
                                                    body("binance_perp_funding_btcusdt"))
    assert "funding_rate" in f.columns and f["funding_rate"].notna().all()
    data = {"BTCUSDT": f}
    rules = mod("openterm.bt.rules")
    res = mod("openterm.bt.engine").backtest(data, rules.signals(rules.parse("SMA20>SMA50"), data, short=True),
                                             case["config"], engine="crypto", bars_per_year=365)
    assert_run(res, case)


def test_composite_rebalance_matches_vibe():
    pd = mod("pandas")
    case = CASES["composite_aapl_spy_rebalance"]
    fr = mod("openterm.bt.frames")
    data = {s: fr.from_yahoo_chart(body(f"yahoo_chart_{s.lower()}_10y_1d")) for s in ("AAPL", "SPY")}
    sig = {s: pd.Series(w, index=data[s].index) for s, w in case["weights"].items()}
    res = mod("openterm.bt.engine").backtest(data, sig, case["config"], engine="composite")
    assert_run(res, case)


def test_bt_run_crypto_perp_through_the_api(client):
    case = CASES["btc_perp_sma_cross_short"]
    job = bt_run(client, rule="SMA20>SMA50", symbols=["BTCUSDT.P"], interval="1D", range="MAX",
                 options={"cash": 100_000, "short": True})
    assert job["state"] == "done", job
    run = client.get(f"/api/bt/runs/{job['result']['run_id']}").json()
    assert run["labels"]["engine"] == "crypto" and run["labels"]["sources"][0]["name"].startswith("binance")
    assert_metrics(run["metrics"], case["metrics"])


# --- 7. Validation (step 6) --------------------------------------------------------------------------------------

def _aapl_run():
    case = CASES["aapl_sma20_gt_sma50"]
    data = {"AAPL": mod("openterm.bt.frames").from_yahoo_chart(body(case["fixture"]))}
    rules = mod("openterm.bt.rules")
    return mod("openterm.bt.engine").backtest(data, rules.signals(rules.parse("SMA20>SMA50"), data), case["config"],
                                              engine="us")


def _assert_dict(got: dict, want: dict):
    for k, v in want.items():
        if (isinstance(v, int | float) and not isinstance(v, bool)) or (
                isinstance(v, list) and v and isinstance(v[0], int | float)):
            assert got[k] == pytest.approx(v, rel=1e-4, abs=1e-4), k
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            for g, w in zip(got[k], v, strict=True):
                _assert_dict(g, w)
        elif isinstance(v, dict):
            _assert_dict(got[k], v)
        else:
            assert got[k] == v, k


@VALID
def test_monte_carlo_bootstrap_and_walk_forward_match_vibe():
    v = mod("openterm.bt.validation")
    res = _aapl_run()
    want = EXPECTED["validation_aapl"]
    _assert_dict(v.monte_carlo_test(res.trades, 100_000, n_simulations=1000, seed=42, bars_per_year=252),
                 want["monte_carlo"])
    _assert_dict(v.bootstrap_sharpe_ci(res.equity, n_bootstrap=1000, confidence=0.95, bars_per_year=252, seed=42,
                                       initial_capital=100_000), want["bootstrap"])
    _assert_dict(v.walk_forward_analysis(res.equity, res.trades, n_windows=5, bars_per_year=252),
                 want["walk_forward"])


@VALID
def test_bt_mc_and_wf_jobs(client):
    run = bt_run(client, rule="SMA20>SMA50", symbols=["AAPL"], interval="1D", range="10Y",
                 options={"cash": 100_000, "adjusted": False})
    rid = run["result"]["run_id"]
    mc = _wait(client, client.post(f"/api/bt/runs/{rid}/mc", json={}).json()["id"])
    wf = _wait(client, client.post(f"/api/bt/runs/{rid}/wf", json={}).json()["id"])
    assert mc["result"]["p_value_sharpe"] == pytest.approx(EXPECTED["validation_aapl"]["monte_carlo"]["p_value_sharpe"])
    assert wf["result"]["n_windows"] == 5


# --- 8. Runs compare and export (step 7) -------------------------------------------------------------------------

@RUNS
def test_export_csv_and_pine(client):
    run = bt_run(client, rule="SMA20>SMA50", symbols=["AAPL"], interval="1D", range="10Y")
    rid = run["result"]["run_id"]
    csv = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "csv", "part": "trades"})
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("symbol,direction,entry_time")
    pine = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "pine"})
    assert pine.status_code == 200 and "//@version=" in pine.text and "ta.sma(close, 20)" in pine.text
    assert "HISTORICAL SIMULATION, NOT A FORECAST" in pine.text


@RUNS
def test_pine_refused_for_python_strategies(client):
    client.put("/api/bt/strategies/mysma", json={"code": GOOD})
    run = bt_run(client, strategy="mysma", symbols=["AAPL"], interval="1D", range="10Y")
    r = client.get(f"/api/bt/runs/{run['result']['run_id']}/export", params={"fmt": "pine"})
    assert r.status_code == 400 and "RULE" in r.json()["detail"]


@RUNS
def test_compare_two_runs(client):
    a = bt_run(client, rule="SMA20>SMA50", symbols=["AAPL"], interval="1D", range="10Y")["result"]["run_id"]
    b = bt_run(client, rule="CLOSE>SMA200", symbols=["AAPL"], interval="1D", range="10Y")["result"]["run_id"]
    r = client.get("/api/bt/compare", params={"a": a, "b": b}).json()
    assert r["a"]["id"] == a and r["b"]["id"] == b
    assert r["diff"]["total_return"] == pytest.approx(r["b"]["metrics"]["total_return"] - r["a"]["metrics"]["total_return"])


def test_runs_trimmed_to_200(client):
    store = mod("openterm.bt.store")
    assert store.KEEP_RUNS == 200


# --- 9. IMPORT (step 8) ------------------------------------------------------------------------------------------

CSV = "date,open,high,low,close,volume\n2024-01-02,10,11,9,10.5,100\n2024-01-03,10.5,12,10,11.5,120\n" \
      "2024-01-04,11.5,12,11,11,90\n"


@IMPORT
def test_import_csv_round_trip(client):
    r = client.post("/api/bt/import", params={"symbol": "MYBARS"}, content=CSV.encode())
    assert r.status_code == 200 and r.json()["rows"] == 3 and r.json()["label"] == "LOCAL DATA"
    h = client.get("/api/history", params={"symbol": "MYBARS", "range": "MAX", "interval": "1d"}).json()
    assert h["source"] == "local" and len(h["data"]["bars"]) == 3


@IMPORT
@pytest.mark.parametrize(("text", "msg"), [
    ("date,close\n2024-01-02,10\n", "NEEDS"),                                    # missing columns
    ("date,open,high,low,close\n2024-13-02,1,1,1,1\n", "ROW 1"),               # bad date
    ("date,open,high,low,close\n2024-01-02,1,1,1,abc\n", "ROW 1"),             # bad number
])
def test_import_rejects_bad_csv(client, text, msg):
    r = client.post("/api/bt/import", params={"symbol": "BAD"}, content=text.encode())
    assert r.status_code == 400 and msg in r.json()["detail"]


@IMPORT
def test_bt_on_local_data_is_labelled(client):
    client.post("/api/bt/import", params={"symbol": "MYBARS"}, content=CSV.encode())
    job = bt_run(client, rule="CLOSE>10.6", symbols=["MYBARS"], interval="1D", range="MAX")
    run = client.get(f"/api/bt/runs/{job['result']['run_id']}").json()
    assert run["labels"]["sources"][0]["name"] == "local" and "LOCAL DATA" in run["labels"]["data_note"]
