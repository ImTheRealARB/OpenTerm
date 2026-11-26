"""STOP= / TARGET= exits for BT and BT OPT, with the intrabar fill rule (Phase 26 item 5).

The ported engine files stay verbatim (CLAUDE.md), so the exits are installed on one engine INSTANCE through its hooks:
- after each bar's fills the engine calls `on_bar(symbol, bar, ts)`; there an open position whose bar reached its stop or
  target is closed at that level (at the bar's open when it opened beyond the level: a gap gets no better price);
- after a stop or target exit the symbol stays flat until its target weight turns off (or flips) and on again, otherwise a
  rule that is still true would buy straight back the next bar. `_record_dropped_target_adjustments` sees every bar's target
  weights (it is our observation point) and `_plan_open_order` is where a blocked re-entry is refused.

A daily bar that reached BOTH levels is ambiguous: its open, high, low and close do not say which came first. `decide` then
looks at that day's intraday bars (FILL=INTRABAR: 60-minute bars fetched by the server) and takes whichever level an intraday
bar reached first. If no intraday bar covers the day, or one intraday bar reached both levels too, the stop is taken first
(the conservative rule). `stats` counts which rule decided, and the run's labels show it.
"""

from __future__ import annotations

from collections.abc import Sequence


def levels(entry: float, direction: int, stop_pct: float | None, target_pct: float | None) -> tuple[float | None, float | None]:
    """Stop and target prices for a position (percentages of the entry price; a short's stop is ABOVE its entry)."""
    stop = entry * (1 - direction * stop_pct / 100) if stop_pct else None
    target = entry * (1 + direction * target_pct / 100) if target_pct else None
    return stop, target


def _reached(direction: int, high: float, low: float, stop: float | None, target: float | None) -> tuple[bool, bool]:
    if direction > 0:
        return (stop is not None and low <= stop), (target is not None and high >= target)
    return (stop is not None and high >= stop), (target is not None and low <= target)


def decide(direction: int, o: float, h: float, low: float, stop: float | None, target: float | None,
           intraday: Sequence[tuple[float, float]] | None) -> tuple[str, float, str] | None:
    """Did this bar exit the position? -> (reason "stop" | "target", exit price, how it was decided) or None.

    `how`: "gap" (the bar opened beyond a level: exit at the open), "single" (only one level was reached), "intrabar" (both,
    settled by intraday bars), "stop_first" (both, no intraday answer: the conservative rule). `intraday` = that day's
    (high, low) bars in time order, or None.
    """
    hit_stop, hit_target = _reached(direction, h, low, stop, target)
    if not hit_stop and not hit_target:
        return None
    gap_stop, gap_target = _reached(direction, o, o, stop, target)
    if gap_stop:
        return "stop", o, "gap"
    if gap_target:
        return "target", o, "gap"
    if hit_stop and not hit_target:
        return "stop", stop, "single"
    if hit_target and not hit_stop:
        return "target", target, "single"
    for ih, il in intraday or ():
        s, t = _reached(direction, ih, il, stop, target)
        if s and t:
            break  # one intraday bar holds both: still ambiguous at this resolution
        if s:
            return "stop", stop, "intrabar"
        if t:
            return "target", target, "intrabar"
    return "stop", stop, "stop_first"


def install(eng, stop_pct: float | None, target_pct: float | None, intraday: dict | None = None) -> dict:
    """Adds the exits to an engine instance; returns the live `stats` dict the caller copies into the run's labels.
    `intraday` = {symbol: {day Timestamp: [(high, low), ...]}} (FILL=INTRABAR), or None."""
    if getattr(eng, "position_adjustment", "hold") == "rebalance":
        raise ValueError("STOP= AND TARGET= NEED THE HOLD POSITION MODE (NOT REBALANCE)")
    stats = {"stop": 0, "target": 0, "gap": 0, "intrabar": 0, "stop_first": 0}
    blocked: dict[str, int] = {}  # symbol -> the direction it may not re-enter until its target weight changes

    orig_on_bar = eng.on_bar

    def on_bar(symbol, bar, ts):
        orig_on_bar(symbol, bar, ts)
        pos = eng.positions.get(symbol)
        if pos is None:
            return
        stop, target = levels(float(pos.entry_price), int(pos.direction), stop_pct, target_pct)
        day = (intraday or {}).get(symbol, {}).get(ts.normalize()) if intraday else None
        hit = decide(int(pos.direction), float(bar["open"]), float(bar["high"]), float(bar["low"]), stop, target, day)
        if hit is None:
            return
        reason, price, how = hit
        # The engine sets `_active_symbol` only inside its own order paths; a multi-pair forex run would slip this exit with
        # whichever pair traded last (a JPY pip on EUR/USD is 100 times too large).
        eng._active_symbol = symbol
        eng._close_position(symbol, eng.apply_slippage(price, -pos.direction), ts, reason)
        blocked[symbol] = int(pos.direction)
        stats[reason] += 1
        if how in ("gap", "intrabar", "stop_first"):
            stats[how] += 1

    orig_record = eng._record_dropped_target_adjustments

    def record(target_weights, ts):
        for sym, w in target_weights.items():
            if sym in blocked and w is not None:
                d = 1 if w > 1e-9 else (-1 if w < -1e-9 else 0)
                if d != blocked[sym]:
                    del blocked[sym]  # the signal turned off or flipped: re-entry allowed again
        return orig_record(target_weights, ts)

    orig_plan = eng._plan_open_order

    def plan(symbol, target_weight, df, ts, equity, **kw):
        d = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        if d and blocked.get(symbol) == d:
            return None
        return orig_plan(symbol, target_weight, df, ts, equity, **kw)

    eng.on_bar = on_bar
    eng._record_dropped_target_adjustments = record
    eng._plan_open_order = plan
    return stats


def label(stop_pct: float | None, target_pct: float | None, intrabar: bool, stats: dict, intraday_note: str) -> str:
    """One line for the run's labels: the settings and which rule settled each exit."""
    parts = [f"STOP {stop_pct:g}%" if stop_pct else "", f"TARGET {target_pct:g}%" if target_pct else ""]
    head = " ".join(p for p in parts if p)
    both = stats["intrabar"] + stats["stop_first"]
    tail = (f"{stats['stop']} STOP AND {stats['target']} TARGET EXITS ({stats['gap']} AT A GAP OPEN); "
            f"{both} BARS REACHED BOTH: {stats['intrabar']} SETTLED BY 60-MINUTE BARS, {stats['stop_first']} BY THE STOP-FIRST RULE")
    mode = "FILL=INTRABAR" if intrabar else "STOP FIRST WHEN A BAR REACHES BOTH"
    return f"{head} · {mode} · {tail}" + (f" · {intraday_note}" if intraday_note else "")
