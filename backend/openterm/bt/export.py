"""BT EXPORT: CSV of a stored run's equity, trades or metrics, and a TradingView Pine Script v5 translation of a
RULE strategy. Pure Python (no pandas), so the server builds both. Python strategies are never translated: code
cannot be turned into Pine faithfully, and a guess would be a fake result (spec decision J).
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from .job import HEADLINE
from .rules import BoolOp, Cmp, Term, parse

PARTS = ("trades", "equity", "metrics")
TRADE_FIELDS = ("symbol", "direction", "entry_time", "exit_time", "entry_price", "exit_price", "size", "pnl", "pnl_pct",
                "commission", "holding_bars", "exit_reason")


def neutralize(v):
    """Spreadsheet formula guard (audit D-3; the same rule as frontend/src/csvText.ts): a text cell that starts with
    = @ TAB CR, or with + / - not followed by a number, gets a leading apostrophe so Excel shows it instead of running it.
    Numbers (floats, ints) are never touched."""
    if isinstance(v, str) and (v[:1] in ("=", "@", "\t", "\r") or (v[:1] in ("+", "-") and not v[1:2].isdigit() and v[1:2] != ".")):
        return "'" + v
    return v


def _csv(header: list[str], rows: list[list]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows([["" if v is None else neutralize(v) for v in r] for r in rows])
    return out.getvalue()


def run_csv(run: dict, part: str) -> str:
    if part == "trades":
        return _csv(list(TRADE_FIELDS), [[t.get(k) for k in TRADE_FIELDS] for t in run["trades"]])
    if part == "equity":
        bench = {t: v for t, v in run.get("benchmark") or []}
        day = lambda t: dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%d")
        return _csv(["date", "equity", "benchmark"], [[day(t), v, bench.get(t)] for t, v in run["equity"]])
    if part == "metrics":
        return _csv(["metric", "value"], [[k, v] for k, v in run["metrics"].items() if not isinstance(v, dict | list)])
    raise ValueError(f"PART MUST BE {', '.join(PARTS).upper()}")


# --- Pine Script ---------------------------------------------------------------------------------------------------

_FIELD = {"CLOSE": "close", "OPEN": "open", "HIGH": "high", "LOW": "low", "VOLUME": "volume"}


def _term(t: Term) -> str:
    n = int(t.n)
    if t.kind == "NUM":
        return f"{t.n:g}"
    if t.kind == "FIELD":
        return _FIELD[t.name]
    return {
        "SMA": f"ta.sma(close, {n})", "EMA": f"ta.ema(close, {n})", "RSI": f"ta.rsi(close, {n})",
        "HIGH": f"ta.highest(high, {n})", "LOW": f"ta.lowest(low, {n})", "RET": f"(close / close[{n}] - 1)",
    }[t.kind]


def _expr(node, state: list[str]) -> str:
    """Pine boolean expression; a CROSS> / CROSS< becomes a persistent flag (true from the cross until the opposite one)."""
    if isinstance(node, BoolOp):
        return "(" + f" {node.op.lower()} ".join(_expr(x, state) for x in node.items) + ")"
    assert isinstance(node, Cmp)
    a, b = _term(node.left), _term(node.right)
    if node.op in ("CROSS>", "CROSS<"):
        up, down = ("ta.crossover", "ta.crossunder") if node.op == "CROSS>" else ("ta.crossunder", "ta.crossover")
        name = f"cross{len(state)}"
        state.append(f"var bool {name} = false\n{name} := {up}({a}, {b}) ? true : {down}({a}, {b}) ? false : {name}")
        return name
    return f"({a} {node.op} {b})"


def pine_script(rule: str, *, short: bool, cash: float, fees_bps: float, symbols: list[str], interval: str) -> str:
    state: list[str] = []
    cond = _expr(parse(rule), state)
    title = rule.replace('"', "'")[:60]
    lines = [
        f"// {HEADLINE}",
        "// Translated by OpenTerm from the rule below. Pine fills at the next bar's open, like OpenTerm, but results",
        "// will still differ: EMA / RSI seeding, share rounding, OpenTerm's per-market cost stack and slippage are not",
        "// reproduced (fees are the FEES= option only; set slippage in the strategy properties).",
        f"// RULE: {rule}",
        f"// RUN: {', '.join(symbols)} {interval}" + ("  (Pine runs on the chart symbol: apply it to each one)" if len(symbols) > 1 else ""),
        "//@version=5",
        (f'strategy("OpenTerm BT: {title}", overlay=true, initial_capital={cash:g}, default_qty_type=strategy.percent_of_equity,'
         f" default_qty_value=100, commission_type=strategy.commission.percent, commission_value={fees_bps / 100:g})"),
        "",
        *state,
        f"signal = {cond}",
        "if signal",
        '    strategy.entry("Long", strategy.long)',
        "else",
        '    strategy.entry("Short", strategy.short)' if short else '    strategy.close("Long")',
    ]
    return "\n".join(lines) + "\n"
