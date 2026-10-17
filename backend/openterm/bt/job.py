"""The `bt.run` job, run inside a job worker: data file -> frames -> signals -> engine -> a JSON-ready run.

The server already fetched the bars (router, cache, fixtures) and wrote them to a content-addressed data file; the
job params carry its path and hash. Nothing here touches the network.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import msgpack

HEADLINE = "HISTORICAL SIMULATION, NOT A FORECAST"


def _num(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int | float):
        f = float(v)
        return None if not math.isfinite(f) else (int(v) if isinstance(v, int) else f)
    try:  # numpy scalars
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def scalar_metrics(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        if isinstance(v, str):
            out[k] = v
        elif not isinstance(v, dict | list | tuple):
            n = _num(v)
            if n is not None or v is None or (isinstance(v, float) and not math.isfinite(v)):
                out[k] = n
    return out


def _epoch(ts) -> int:
    return int(ts.value // 1_000_000_000)


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    import pandas as pd

    from . import frames, limits, rules, sandbox
    from .engine import backtest

    progress(0.05, "LOADING DATA")
    payload = msgpack.unpackb(Path(params["data_path"]).read_bytes(), raw=False)
    raw = {s: frames.from_bars(b) for s, b in payload["bars"].items()}
    adjusted = bool(params.get("adjusted", True)) and all(
        "adj_close" in f.columns and f["adj_close"].notna().any() for f in raw.values())
    data_map = {s: frames.adjusted(f) if adjusted else f for s, f in raw.items()}
    empty = [s for s, f in data_map.items() if len(f) < 2]
    if empty:
        raise ValueError(f"NOT ENOUGH BARS FOR {', '.join(empty)}")

    progress(0.15, "SIGNALS")
    with limits.memory_cap(int(params.get("memory_limit_mb", 1024))):
        if params.get("rule"):
            signal_map = rules.signals(rules.parse(params["rule"]), data_map, short=bool(params.get("short")))
        else:
            engine_obj = sandbox.load(params["code"])
            signal_map = engine_obj.generate({s: f.copy() for s, f in data_map.items()})
            if not isinstance(signal_map, dict):
                raise ValueError(f"generate() MUST RETURN A DICT OF SERIES, GOT {type(signal_map).__name__}")
            signal_map = {s: v for s, v in signal_map.items() if s in data_map and isinstance(v, pd.Series)}
        if not signal_map:
            raise ValueError("NO SIGNALS: generate() returned no Series for the loaded symbols")

        progress(0.35, "SIMULATING")
        bench_ret, bench_meta = None, None
        if payload.get("bench"):
            b = frames.from_bars(payload["bench"])
            b = frames.adjusted(b) if adjusted else b
            close = b["close"]
            bench_ret = close.pct_change(fill_method=None).fillna(0.0)
            lo = min(f.index.min() for f in data_map.values())
            hi = max(f.index.max() for f in data_map.values())
            window = close.loc[(close.index >= lo) & (close.index <= hi)]
            if len(window) >= 2:
                bench_meta = {"benchmark_ticker": payload.get("bench_symbol"),
                              "benchmark_return": float(window.iloc[-1] / window.iloc[0] - 1)}
        res = backtest(data_map, signal_map, params["config"], engine=params["engine"],
                       bars_per_year=params.get("bars_per_year"), bench_ret=bench_ret, benchmark_metadata=bench_meta)

    progress(0.9, "WRITING RESULT")
    cash = float(params["config"].get("initial_cash", 100_000))
    bench_eq = cash * (1 + res.benchmark).cumprod()
    trades = [{
        "symbol": t.symbol, "direction": int(t.direction), "entry_time": t.entry_time.strftime("%Y-%m-%d"),
        "exit_time": t.exit_time.strftime("%Y-%m-%d"), "entry_price": _num(t.entry_price),
        "exit_price": _num(t.exit_price), "size": _num(t.size), "pnl": _num(t.pnl), "pnl_pct": _num(t.pnl_pct),
        "commission": _num(t.commission), "holding_bars": _num(t.holding_bars), "exit_reason": t.exit_reason,
    } for t in res.trades]
    labels = dict(params["labels"])
    labels["prices"] = "ADJ" if adjusted else "RAW"
    if params.get("adjusted", True) and not adjusted:
        labels["data_note"] = (labels.get("data_note", "") + " RAW CLOSES: NO ADJUSTED CLOSES FROM THE SOURCE").strip()
    return {
        "run_id": params["run_id"],
        "metrics": scalar_metrics(res.metrics),
        "equity": [[_epoch(ts), round(float(v), 4)] for ts, v in res.equity.items()],
        "benchmark": [[_epoch(ts), round(float(v), 4)] for ts, v in bench_eq.items()],
        "trades": trades,
        "labels": labels,
    }
