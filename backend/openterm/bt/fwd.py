"""Paper forward test (Phase 26 item 6): run a saved strategy on NEW bars with play money, and compare it with what a backtest
of the same period says today.

Nothing here talks to a broker or to ORD (NO LIVE ORDERS): the paper book is a few numbers in OpenTerm's own database.

How a forward test advances (`step`):
- The server fetches the symbol's bars. The newest bar may still be forming, so only the bars before it count as complete.
- A job computes the strategy's signal on the complete bars only (the forming bar is never shown to the strategy).
- Every complete bar not decided before gets a decision (long / flat / short). A change fills at the NEXT bar's open, a price
  that exists by then (the forming bar's open is final once the bar has started).
- When one step decides several bars at once (the server was off for a while), every decision except the newest is marked
  CATCH-UP: it was made late, with hindsight of the bars after it, so it is not a true forward decision.

The comparison (`simulate`) replays the same book over the same period with the signal computed on TODAY's data. On a rule
strategy the two agree unless the data changed; a different decision (DIVERGED) points at look-ahead in a Python strategy,
an indicator that repaints, or revised data. Prices are RAW (as seen live), with no fees or slippage, in both.

This module is pure Python (the server imports it); `signals_job` imports pandas inside the function (worker side).
"""

from __future__ import annotations

import math
from collections.abc import Callable

BAR_SECONDS = {"1D": 86_400, "1W": 7 * 86_400}
HISTORY_RANGE = {"1D": "2Y", "1W": "10Y"}  # enough bars for the slowest built-in indicator (200 bars) to warm up
MAX_DECISIONS = 2000  # a forward test keeps at most this many decisions (about 8 years of daily bars)
MAX_FILLS = 2000  # and at most this many fills (the book is stored whole in one kv row, so it must stay bounded)


def new_state(fwd_id: str, symbol: str, strategy: str, interval: str, cash: float, now: float) -> dict:
    return {"id": fwd_id, "symbol": symbol, "strategy": strategy, "interval": interval, "cash0": cash, "started": now,
            "status": "active", "cash": cash, "qty": 0.0, "pos": 0, "last_t": None, "decisions": [], "fills": [],
            "checked": None, "error": None, "backtest": None}


def _sign(v) -> int:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0
    return 1 if v > 1e-9 else (-1 if v < -1e-9 else 0)


def _trade(book: dict, d: int, price: float, t: int) -> None:
    """Move the whole book to direction `d` at `price` (all-in long, all-in short, or flat).

    A book whose equity is zero or below (a short that the price ran away from) is WIPED OUT: sizing a new position from a
    negative equity would give a short the opposite sign (equity -5,000 "long" = -20 shares) while `pos` said long. It is
    closed flat at `price`, the debt is not carried (play money cannot owe), and `busted` stops every later trade."""
    equity = book["cash"] + book["qty"] * price
    if equity <= 0:
        if book["qty"]:
            book["fills"].append([t, "BUY" if book["qty"] < 0 else "SELL", round(abs(book["qty"]), 6), price])
        book["cash"], book["qty"], book["pos"], book["busted"] = 0.0, 0.0, 0, True
    else:
        qty = d * equity / price if d else 0.0
        side = "BUY" if qty > book["qty"] else "SELL"
        book["fills"].append([t, side, round(abs(qty - book["qty"]), 6), price])
        book["cash"], book["qty"], book["pos"] = equity - qty * price, qty, d
    del book["fills"][:-MAX_FILLS]


def _fill_open(t: list[int], o: list[float], i: int) -> int | None:
    """Index of the first usable open after bar i (the bar a decision on bar i fills at), or None while there is none yet."""
    return next((j for j in range(i + 1, len(o)) if o[j] is not None and o[j] > 0), None)


def _advance(book: dict, t: list[int], o: list[float], sig: list, start: float, bar_s: int, late_before: int) -> None:
    """Decide every complete bar after `book["last_t"]` (bars 0..len(sig)-1 are complete; `o` has one more bar).
    A bar counts from the forward test's start once it was still forming at the start (t + bar length > start)."""
    for i in range(len(sig)):
        if t[i] + bar_s <= start or (book["last_t"] is not None and t[i] <= book["last_t"]):
            continue
        d = _sign(sig[i])
        j = _fill_open(t, o, i) if d != book["pos"] and not book.get("busted") else None
        if d != book["pos"] and not book.get("busted") and j is None:
            break  # the fill price does not exist yet: leave this bar undecided so the next step makes the same trade
        book["decisions"].append([t[i], d, i < late_before])
        if j is not None:
            _trade(book, d, float(o[j]), t[j])
        book["last_t"] = t[i]
    del book["decisions"][:-MAX_DECISIONS]


def step(state: dict, t: list[int], o: list[float], sig: list, now: float) -> dict:
    """Advance a forward test with a fresh signal list (one value per complete bar; `t` / `o` cover the forming bar too)."""
    bar_s = BAR_SECONDS[state["interval"]]
    _advance(state, t, o, sig, state["started"], bar_s, late_before=len(sig) - 1)
    state["checked"] = now
    state["error"] = None
    if state.get("busted"):  # the scheduler and the signal job skip a stopped book
        state["status"] = "stopped"
        state["error"] = "PAPER BOOK WIPED OUT (EQUITY <= 0): CLOSED FLAT AND STOPPED"
    return state


def simulate(t: list[int], o: list[float], sig: list, start: float, interval: str, cash: float) -> dict:
    """The same book replayed over the forward test's period with `sig` computed today (the backtest of that period)."""
    book = {"cash": cash, "qty": 0.0, "pos": 0, "last_t": None, "decisions": [], "fills": []}
    _advance(book, t, o, sig, start, BAR_SECONDS[interval], late_before=0)
    return book


def equity(book: dict, price: float | None) -> float | None:
    return None if price is None else book["cash"] + book["qty"] * price


def compare(state: dict, t: list[int], o: list[float], c: list[float], sig: list) -> dict:
    """Backtest of the forward period on today's data + where its decisions differ from the recorded ones."""
    bt = simulate(t, o, sig, state["started"], state["interval"], state["cash0"])
    last_close = next((float(x) for x in reversed(c[:len(sig)]) if x is not None), None)
    then = {row[0]: row[1] for row in bt["decisions"]}
    diverged = [[row[0], row[1], then[row[0]]] for row in state["decisions"] if row[0] in then and then[row[0]] != row[1]]
    live_eq, bt_eq = equity(state, last_close), equity(bt, last_close)
    return {"equity": bt_eq, "return": None if bt_eq is None else bt_eq / state["cash0"] - 1, "fills": len(bt["fills"]),
            "decisions": len(bt["decisions"]), "diverged": diverged[-50:], "n_diverged": len(diverged),
            "live_equity": live_eq, "live_return": None if live_eq is None else live_eq / state["cash0"] - 1,
            "price": last_close}


def summary(state: dict) -> dict:
    """The list row of a forward test (no per-bar arrays)."""
    bt = state.get("backtest") or {}
    return {k: state.get(k) for k in ("id", "symbol", "strategy", "interval", "cash0", "started", "status", "pos", "checked",
                                       "error")} | {
        "decisions": len(state["decisions"]), "late": sum(1 for d in state["decisions"] if d[2]), "fills": len(state["fills"]),
        "live_return": bt.get("live_return"), "bt_return": bt.get("return"), "n_diverged": bt.get("n_diverged", 0)}


# --- the job: signals on the complete bars ---------------------------------------------------------------------------

FWD_KEYS = {"fwd_id", "data_path", "data_sha", "rule", "code", "short"}


def validate(params: dict) -> dict:
    from ..jobs.kinds import BadParams

    if not isinstance(params, dict) or set(params) - FWD_KEYS or not {"fwd_id", "data_path", "data_sha"} <= set(params) \
            or bool(params.get("rule")) == bool(params.get("code")):
        raise BadParams("BT.FWDSIG PARAMS ARE BUILT BY /api/bt/fwd")
    return params


def signals_job(params: dict, progress: Callable[[float, str], None]) -> dict:
    """{fwd_id, t, o, c (all bars), signal (complete bars only)}; RAW prices; the forming bar never reaches the strategy."""
    from .job import _num, load_data, signals_for

    progress(0.1, "LOADING DATA")
    _, data_map, _ = load_data({**params, "adjusted": False})
    (sym, frame), = data_map.items()
    n = len(frame) - 1  # the newest bar may still be forming: never shown to the strategy (it is decided on a later step)
    progress(0.4, "SIGNALS")
    sig = signals_for(params.get("rule"), params.get("code"), {sym: frame.iloc[:n].copy()}, bool(params.get("short")))[sym]
    epoch = [int(ts.value // 1_000_000_000) for ts in frame.index]
    return {"fwd_id": params["fwd_id"], "t": epoch, "o": [_num(x) for x in frame["open"]], "c": [_num(x) for x in frame["close"]],
            "signal": [_num(x) for x in sig.reindex(frame.index[:n]).astype(float)]}
