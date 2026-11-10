"""The `journal.shadow` job, run inside a job worker (pandas and numpy load here only).

Question it answers: "had I kept the same ENTRIES but used one fixed exit rule, how would I have done, compared with how I really exited?"
Both sides are replayed through the same backtester on the same daily bars with the same costs, so the only difference between the two
equity curves is the exit:

- YOU: every round trip held from its real entry day to its real exit day.
- RULE: the same entries, left on a fixed holding period, or on a fixed stop and target checked on daily closes.

Simplifications, all printed in the result's labels: positions are equal-weight (your real sizes are not replayed), a trade is entered
at the open of its entry day, intraday round trips become one daily bar, and a stop or target is only seen at a daily close.
The result is a HISTORICAL SIMULATION, NOT A FORECAST.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import msgpack

from ..bt.job import HEADLINE, _epoch, scalar_metrics, tail_risk

SHOW_METRICS = ("total_return", "annual_return", "max_drawdown", "sharpe", "trade_count", "win_rate", "profit_loss_ratio")


def _bars(df, day: str, side: str) -> int:
    return int(df.index.searchsorted(day, side=side))


def _sets(df, trips: list[dict], rule: dict | None):
    """(you signal, rule signal, used, skipped) for one symbol's trips on its daily frame."""
    import numpy as np

    n = len(df)
    opens, closes = df["open"].to_numpy(float), df["close"].to_numpy(float)
    you = np.zeros(n + 1)
    alt = np.zeros(n + 1)
    used = skipped = 0
    why: dict[str, int] = {}
    for t in trips:
        if t["entry"] < str(df.index[0].date()):
            why["ENTRY BEFORE THE FIRST BAR"] = why.get("ENTRY BEFORE THE FIRST BAR", 0) + 1
            continue
        e = _bars(df, t["entry"], "left")
        if e >= n:
            why["ENTRY AFTER THE LAST BAR"] = why.get("ENTRY AFTER THE LAST BAR", 0) + 1
            continue
        lo = max(e - 1, 0)  # a signal acts on the next bar, so it starts the bar before the entry day
        x = min(max(_bars(df, t["exit"], "left"), e, lo + 1), n - 1)
        d = t["dir"]
        you[lo] += d
        you[x] -= d
        used += 1
        if rule["kind"] == "hold":
            xr = min(e + rule["hold_days"], n - 1)
        else:
            end = min(e + rule["max_days"], n - 1)
            ref = opens[e] if opens[e] > 0 else closes[e]
            move = (closes[e:end + 1] / ref - 1.0) * d * 100.0
            hit = (move <= -rule["stop_pct"]) | (move >= rule["target_pct"])
            xr = e + int(np.argmax(hit)) if hit.any() else end
        alt[lo] += d
        alt[max(xr, lo + 1)] -= d
    skipped = len(trips) - used
    return np.clip(np.cumsum(you[:n]), -1, 1), np.clip(np.cumsum(alt[:n]), -1, 1), used, skipped, why


def run(params: dict, progress: Callable[[float, str], None]) -> dict:
    import pandas as pd

    from ..bt import frames
    from ..bt.engine import backtest

    progress(0.05, "LOADING DATA")
    payload = msgpack.unpackb(Path(params["data_path"]).read_bytes(), raw=False)
    raw = {s: frames.from_bars(b) for s, b in payload["bars"].items()}
    adjusted = all("adj_close" in f.columns and f["adj_close"].notna().any() for f in raw.values())
    data = {s: frames.adjusted(f) if adjusted else f for s, f in raw.items()}
    rule = params["rule"]
    by_sym: dict[str, list[dict]] = {}
    for t in params["trips"]:
        by_sym.setdefault(t["symbol"], []).append(t)

    progress(0.2, "BUILDING SIGNALS")
    you, alt, used, skipped, why = {}, {}, 0, 0, {}
    for s, df in data.items():
        if len(df) < 2:
            skipped += len(by_sym.get(s, []))
            why["NOT ENOUGH BARS"] = why.get("NOT ENOUGH BARS", 0) + len(by_sym.get(s, []))
            continue
        a, b, u, k, w = _sets(df, by_sym.get(s, []), rule)
        if u:
            you[s], alt[s] = pd.Series(a, index=df.index), pd.Series(b, index=df.index)
        used, skipped = used + u, skipped + k
        for r, c in w.items():
            why[r] = why.get(r, 0) + c
    if not you:
        raise ValueError("NO TRADE COULD BE REPLAYED: " + ", ".join(f"{k} x{v}" for k, v in why.items()))
    dm = {s: data[s] for s in you}
    cfg = dict(params["config"])
    progress(0.4, "REPLAYING YOUR EXITS")
    r_you = backtest(dm, you, cfg, engine=params["engine"], bars_per_year=params["bars_per_year"])
    progress(0.7, "REPLAYING THE RULE")
    r_alt = backtest(dm, alt, cfg, engine=params["engine"], bars_per_year=params["bars_per_year"])
    progress(0.95, "WRITING RESULT")

    def curve(res) -> list[list[float]]:
        return [[_epoch(ts), round(float(v), 4)] for ts, v in res.equity.items()]

    def mets(res) -> dict:
        m = {**scalar_metrics(res.metrics), **tail_risk(res.equity)}
        return {k: m.get(k) for k in (*SHOW_METRICS, "var_95", "es_95")}

    cum, real = 0.0, []
    for t in sorted((t for t in params["trips"] if t["symbol"] in dm), key=lambda t: t["exit"]):
        cum += t["pnl"]
        real.append([int(pd.Timestamp(t["exit"]).timestamp()), round(cum, 2)])
    labels = {**params["labels"], "prices": "ADJ" if adjusted else "RAW", "rule": rule["text"],
              "notes": ["EQUAL-WEIGHT POSITIONS: YOUR REAL SIZES ARE NOT REPLAYED",
                        "ENTRIES AT THE OPEN OF YOUR ENTRY DAY; INTRADAY ROUND TRIPS BECOME ONE DAILY BAR",
                        "A STOP OR TARGET IS ONLY SEEN AT A DAILY CLOSE",
                        "BOTH CURVES USE THE SAME BARS AND THE SAME COSTS"]}
    return {
        "labels": labels, "currency": params["currency"], "rule": rule, "engine": params["engine"],
        "you": {"equity": curve(r_you), "metrics": mets(r_you)}, "alt": {"equity": curve(r_alt), "metrics": mets(r_alt)},
        "journal_pnl": {"curve": real, "total": cum, "currency": params["currency"]},
        "replayed": used, "skipped_trips": skipped, "skipped_reasons": why, "skipped_symbols": params.get("skipped", []),
        "symbols": sorted(dm), "headline": HEADLINE,
    }
