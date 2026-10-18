"""Generates backend/tests/fixtures/bt_vibe_expected.json by running Vibe-Trading's own engine (commit d0db2e3).

Not part of the app or the tests. Run it in a throwaway venv that has pandas, numpy, pydantic, requests, pyyaml and
defusedxml, with Vibe-Trading's `agent/` folder on PYTHONPATH:
    $env:PYTHONPATH = "<Vibe-Trading-d0db2e3>\\agent"; <venv>\\Scripts\\python.exe scripts\\vibe_crosscheck.py

Inputs are the Phase 12 fixtures (Yahoo 10y daily, Binance BTCUSDT perp klines + funding) and a few small synthetic
frames. The frame-building rules below are the contract the OpenTerm test uses to rebuild the identical input:
- Yahoo: bar date = UTC timestamp + meta.gmtoffset, floored to the day (tz-naive); OHLCV from indicators.quote[0];
  rows with any missing open/high/low/close dropped. Raw (not dividend-adjusted) prices.
- Binance perp: bar date = kline open time (UTC day); `funding_rate` = mean of that UTC day's funding settlements;
  only days that have funding data are kept.
- Indicators: SMA = rolling mean (min_periods = n); RSI = Wilder (ewm alpha = 1/n, adjust=False, min_periods = n).
  A rule is 0 while any indicator is NaN.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.engines.composite import CompositeEngine
from backtest.engines.crypto import CryptoEngine
from backtest.engines.forex import ForexEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.global_futures import GlobalFuturesEngine
from backtest.engines.india_equity import IndiaEquityEngine
from backtest.metrics import calc_metrics
from backtest.validation import bootstrap_sharpe_ci, monte_carlo_test, walk_forward_analysis

FIX = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
OUT = FIX / "bt_vibe_expected.json"
METRIC_KEYS = ["final_value", "total_return", "annual_return", "max_drawdown", "sharpe", "sortino", "calmar",
               "win_rate", "profit_loss_ratio", "profit_factor", "max_consecutive_loss", "avg_holding_days",
               "trade_count", "benchmark_return", "excess_return", "information_ratio", "tracking_error",
               "benchmark_beta", "avg_turnover", "total_turnover"]


def load(name):
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))["body"]


def yahoo_frame(name):
    res = load(name)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(np.array(res["timestamp"]) + off, unit="s").floor("D")
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")}, index=idx, dtype=float)
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[~df.index.duplicated(keep="last")]


def perp_frame():
    k = load("binance_perp_klines_btcusdt_1d")
    df = pd.DataFrame([[float(x) for x in r[1:6]] for r in k], columns=["open", "high", "low", "close", "volume"],
                      index=pd.to_datetime([r[0] for r in k], unit="ms").floor("D"))
    f = load("binance_perp_funding_btcusdt")
    fr = pd.Series([float(x["fundingRate"]) for x in f], index=pd.to_datetime([x["fundingTime"] for x in f], unit="ms"))
    daily = fr.groupby(fr.index.floor("D")).mean()
    df = df.loc[(df.index >= daily.index.min()) & (df.index <= daily.index.max())].copy()
    df["funding_rate"] = daily.reindex(df.index)
    return df.dropna(subset=["funding_rate"])


def sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def rsi(s, n):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    lo = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + g / lo)


class Rule:
    def __init__(self, fn):
        self.fn = fn

    def generate(self, data_map):
        return {k: self.fn(v).astype(float) for k, v in data_map.items()}


def sma_cross(short_ok):
    def fn(df):
        a, b = sma(df["close"], 20), sma(df["close"], 50)
        out = np.where(a > b, 1.0, -1.0 if short_ok else 0.0)
        return pd.Series(np.where(a.isna() | b.isna(), 0.0, out), index=df.index)
    return fn


def rsi_below(df):
    r = rsi(df["close"], 14)
    return pd.Series(np.where(r.isna(), 0.0, np.where(r < 30, 1.0, 0.0)), index=df.index)


class Fixed:
    def __init__(self, weights):
        self.weights = weights

    def generate(self, data_map):
        return {k: pd.Series(self.weights[k], index=v.index, dtype=float) for k, v in data_map.items()}


class Loader:
    def __init__(self, data):
        self.data = data

    def fetch(self, codes, start, end, fields=None, interval="1D"):
        return {c: self.data[c].copy() for c in codes}


def ts(t):
    return pd.Timestamp(t).strftime("%Y-%m-%d")


def run(engine, data, signal, config, bars_per_year=252):
    config = {"codes": list(data), "interval": "1D", "start_date": "", "end_date": "", **config}
    with tempfile.TemporaryDirectory() as d:
        m = engine.run_backtest(config, Loader(data), signal, Path(d), bars_per_year=bars_per_year)
    eq = [(ts(s.timestamp), round(float(s.equity), 6)) for s in engine.equity_snapshots]
    trades = [{"symbol": t.symbol, "direction": int(t.direction), "entry_time": ts(t.entry_time),
               "exit_time": ts(t.exit_time), "entry_price": round(float(t.entry_price), 8),
               "exit_price": round(float(t.exit_price), 8), "size": round(float(t.size), 8),
               "pnl": round(float(t.pnl), 6), "commission": round(float(t.commission), 6),
               "exit_reason": t.exit_reason} for t in engine.trades]
    metrics = {k: (None if m.get(k) is None or (isinstance(m.get(k), float) and not np.isfinite(m[k]))
                   else round(float(m[k]), 8)) for k in METRIC_KEYS if k in m}
    pick = sorted({0, 1, len(eq) // 2, len(eq) - 1}) if eq else []
    return {"config": config, "metrics": metrics, "equity_points": len(eq), "equity_at": [eq[i] for i in pick],
            "equity": eq if len(eq) <= 40 else None, "trade_count": len(trades),
            "trades": trades if len(trades) <= 12 else trades[:3] + trades[-3:]}


def synthetic(n, start=100.0, step=1.0, day0="2024-01-01"):
    idx = pd.bdate_range(day0, periods=n)
    o = start + step * np.arange(n)
    return pd.DataFrame({"open": o, "high": o + 1.0, "low": o - 1.0, "close": o + 0.5, "volume": 1000.0}, index=idx)


def frame_json(df):
    return {"index": [ts(i) for i in df.index], **{c: [float(x) for x in df[c]] for c in df.columns}}


def main():
    out = {"source": "HKUDS/Vibe-Trading @ d0db2e3, agent/backtest (MIT)", "cases": {}}
    cases = out["cases"]

    # Small synthetic cases (the bars are stored so the test rebuilds them exactly).
    s1 = synthetic(8)
    sig1 = [0, 1, 1, 1, 0, -1, -1, 0]
    cases["us_long_then_short"] = {
        "bars": {"SYN": frame_json(s1)}, "signals": {"SYN": sig1},
        **run(GlobalEquityEngine({"initial_cash": 10_000, "slippage_us": 0.001}, market="us"), {"SYN": s1},
              Fixed({"SYN": sig1}), {"initial_cash": 10_000, "slippage_us": 0.001})}
    a, b = synthetic(10, 50.0, 1.0), synthetic(10, 80.0, -1.5)
    for mode in ("hold", "rebalance"):
        cfg = {"initial_cash": 10_000, "slippage_us": 0.0, "position_adjustment": mode}
        cases[f"us_two_symbols_{mode}"] = {
            "bars": {"A": frame_json(a), "B": frame_json(b)}, "signals": {"A": [0.5] * 10, "B": [0.5] * 10},
            **run(GlobalEquityEngine(cfg, market="us"), {"A": a, "B": b}, Fixed({"A": 0.5, "B": 0.5}), cfg)}
    cfg = {"initial_cash": 10_000, "slippage_us": 0.0, "warmup_bars": 3}
    cases["us_warmup_3"] = {"bars": {"SYN": frame_json(s1)}, "signals": {"SYN": [1] * 8},
                            **run(GlobalEquityEngine(cfg, market="us"), {"SYN": s1}, Fixed({"SYN": 1.0}), cfg)}
    s2 = synthetic(8, 2500.0, 10.0)
    sig2 = [0, 1, 1, 1, 0, 0, 0, 0]
    cfg = {"initial_cash": 100_000}
    cases["india_one_trade"] = {"bars": {"SYN.NS": frame_json(s2)}, "signals": {"SYN.NS": sig2},
                                **run(IndiaEquityEngine(cfg), {"SYN.NS": s2}, Fixed({"SYN.NS": sig2}), cfg)}

    # Fixture runs.
    aapl = yahoo_frame("yahoo_chart_aapl_10y_1d")
    cfg = {"initial_cash": 100_000}
    cases["aapl_sma20_gt_sma50"] = {"fixture": "yahoo_chart_aapl_10y_1d", "symbol": "AAPL", "rule": "SMA20>SMA50",
                                    **run(GlobalEquityEngine(cfg, market="us"), {"AAPL": aapl}, Rule(sma_cross(False)),
                                          cfg)}
    # Validation (BT MC / BT WF) on the AAPL run, Vibe's default seeds and sizes.
    eng = GlobalEquityEngine(cfg, market="us")
    run(eng, {"AAPL": aapl}, Rule(sma_cross(False)), cfg)
    curve = pd.Series([s.equity for s in eng.equity_snapshots], index=[s.timestamp for s in eng.equity_snapshots])
    out["validation_aapl"] = {
        "case": "aapl_sma20_gt_sma50",
        "monte_carlo": monte_carlo_test(eng.trades, 100_000, n_simulations=1000, seed=42, bars_per_year=252),
        "bootstrap": bootstrap_sharpe_ci(curve, n_bootstrap=1000, confidence=0.95, bars_per_year=252, seed=42,
                                         initial_capital=100_000),
        "walk_forward": walk_forward_analysis(curve, eng.trades, n_windows=5, bars_per_year=252),
    }
    rel = yahoo_frame("yahoo_chart_reliance_10y_1d")
    cases["reliance_rsi14_lt_30"] = {"fixture": "yahoo_chart_reliance_10y_1d", "symbol": "RELIANCE.NS",
                                     "rule": "RSI14<30",
                                     **run(IndiaEquityEngine(cfg), {"RELIANCE.NS": rel}, Rule(rsi_below), cfg)}
    btc = perp_frame()
    cfg = {"initial_cash": 100_000, "interval": "1D"}
    cases["btc_perp_sma_cross_short"] = {"fixture": "binance_perp_klines_btcusdt_1d + binance_perp_funding_btcusdt",
                                         "symbol": "BTCUSDT", "rule": "SMA20>SMA50 SHORT",
                                         **run(CryptoEngine(cfg), {"BTCUSDT": btc}, Rule(sma_cross(True)), cfg, 365)}
    # Step 5 engines on synthetic bars (forex, futures) and a composite of two US fixtures.
    fx = synthetic(12, 1.10, 0.002)
    sigfx = [0, 1, 1, 1, 1, 0, -1, -1, -1, 0, 0, 0]
    cfg = {"initial_cash": 10_000}
    cases["forex_eurusd"] = {"bars": {"EURUSD=X": frame_json(fx)}, "signals": {"EURUSD=X": sigfx},
                             **run(ForexEngine(cfg), {"EURUSD=X": fx}, Fixed({"EURUSD=X": sigfx}), cfg)}
    fut = synthetic(12, 5000.0, 10.0)
    sigfut = [0, 1, 1, 1, 0, 0, -1, -1, 0, 0, 0, 0]
    cfg = {"initial_cash": 100_000}
    cases["futures_es"] = {"bars": {"ES=F": frame_json(fut)}, "signals": {"ES=F": sigfut},
                           **run(GlobalFuturesEngine(cfg), {"ES=F": fut}, Fixed({"ES=F": sigfut}), cfg)}
    spy = yahoo_frame("yahoo_chart_spy_10y_1d")
    cfg = {"initial_cash": 100_000, "position_adjustment": "rebalance", "rebalance_tolerance": 0.05}
    cases["composite_aapl_spy_rebalance"] = {
        "fixture": "yahoo_chart_aapl_10y_1d + yahoo_chart_spy_10y_1d", "weights": {"AAPL": 0.5, "SPY": 0.5},
        **run(CompositeEngine({**cfg, "codes": ["AAPL", "SPY"]}, ["AAPL", "SPY"]), {"AAPL": aapl, "SPY": spy},
              Fixed({"AAPL": 0.5, "SPY": 0.5}), cfg)}

    # Metrics on a fixed equity curve, no trades, zero benchmark.
    curve = pd.Series([100.0, 110.0, 99.0, 121.0, 110.0, 115.5], index=pd.bdate_range("2024-01-01", periods=6))
    m = calc_metrics(curve, [], 100.0, 252, pd.Series(0.0, index=curve.index))
    out["metrics_fixed_curve"] = {"equity": [float(x) for x in curve], "start": "2024-01-01", "bars_per_year": 252,
                                  "metrics": {k: (round(float(m[k]), 8) if m.get(k) is not None else None)
                                              for k in METRIC_KEYS if k in m}}
    OUT.write_bytes(json.dumps(out, indent=1, default=str).encode("utf-8"))
    for k, v in cases.items():
        print(k, v["trade_count"], v["metrics"].get("final_value"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
