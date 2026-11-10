"""FIFO matching of fills into round trips, and the statistics over them. Pure Python.

A fill is a dict {id, ts, time, symbol, side, qty, price, fee, currency, mult}. Fills are matched per (symbol, currency), oldest lot first,
so two currencies never cross-match and no money is ever converted. A sell with no long lot opens a short; a buy first covers shorts.
Every closing fill makes ONE round trip (against one or several opening lots); the part of a fill that is not matched opens a new lot and
carries its own share of the fee. Fees are split by quantity, so each fee is counted exactly once. Lots still open at the end are
returned as open positions, never marked to a price.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict, deque
from datetime import datetime

EPS = 1e-9


def match(fills: list[dict]) -> tuple[list[dict], list[dict]]:
    """(round trips in exit order, open positions)."""
    lots: dict[tuple[str, str], deque] = defaultdict(deque)  # each lot: [signed qty left, price, fee per unit, ts, id, mult]
    trips: list[dict] = []
    order = sorted(fills, key=lambda f: (f["ts"], f["id"]))
    for f in order:
        key = (f["symbol"], f["currency"])
        book = lots[key]
        s = 1 if f["side"] == "buy" else -1
        q = float(f["qty"])
        fee_unit = float(f["fee"]) / q if q else 0.0
        mult = float(f.get("mult") or 1.0)
        rem = q
        m_qty = 0.0
        cost = proceeds = 0.0  # price * qty sums of the opening and closing sides
        gross = fees = 0.0
        w_ts = 0.0
        first_ts: float | None = None
        first_time = ""
        open_ids: list[int] = []
        long_lot = False
        while rem > EPS and book and (book[0][0] > 0) != (s > 0):
            lot = book[0]
            take = min(rem, abs(lot[0]))
            long_lot = lot[0] > 0
            gross += ((f["price"] - lot[1]) if long_lot else (lot[1] - f["price"])) * take * mult
            fees += lot[2] * take + fee_unit * take
            cost += lot[1] * take
            proceeds += f["price"] * take
            w_ts += lot[3] * take
            if first_ts is None:
                first_ts, first_time = lot[3], lot[6]
            if lot[4] not in open_ids:
                open_ids.append(lot[4])
            m_qty += take
            rem -= take
            lot[0] += -take if long_lot else take
            if abs(lot[0]) <= EPS:
                book.popleft()
        if m_qty > EPS:
            entry_px, exit_px = cost / m_qty, proceeds / m_qty
            basis = entry_px * m_qty * mult
            net = gross - fees
            trips.append({
                "id": f"{f['symbol']}:{f['id']}", "symbol": f["symbol"], "currency": f["currency"], "side": "long" if long_lot else "short",
                "qty": round(m_qty, 8), "entry_time": first_time, "exit_time": f["time"], "entry_ts": first_ts, "exit_ts": f["ts"],
                "entry_price": entry_px, "exit_price": exit_px, "fees": fees, "pnl_gross": gross, "pnl": net,
                "pnl_pct": net / basis if basis else 0.0, "hold_s": max(0.0, f["ts"] - w_ts / m_qty), "notional": basis,
                "open_ids": open_ids, "close_id": f["id"], "mult": mult,
            })
        if rem > EPS:
            book.append([s * rem, f["price"], fee_unit, f["ts"], f["id"], mult, f["time"]])
    positions = []
    for (sym, ccy), book in lots.items():
        net = sum(lot[0] for lot in book)
        if abs(net) <= EPS:
            continue
        qty = sum(abs(lot[0]) for lot in book)
        positions.append({"symbol": sym, "currency": ccy, "side": "long" if net > 0 else "short", "qty": round(qty, 8),
                          "avg_price": sum(abs(lot[0]) * lot[1] for lot in book) / qty, "since": book[0][6]})
    trips.sort(key=lambda t: (t["exit_ts"], t["close_id"]))
    positions.sort(key=lambda p: (p["symbol"], p["currency"]))
    return trips, positions


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def _streak(flags: list[bool]) -> int:
    best = run = 0
    for x in flags:
        run = run + 1 if x else 0
        best = max(best, run)
    return best


def drawdown(trips: list[dict]) -> dict:
    """Cumulative realised P&L in exit order (one currency), and its largest peak-to-trough fall (in money, from a zero start)."""
    cum = 0.0
    peak = 0.0
    worst = 0.0
    worst_end = None
    curve = []
    for t in trips:
        cum += t["pnl"]
        curve.append([t["exit_ts"], cum])
        peak = max(peak, cum)
        if peak - cum > worst:
            worst, worst_end = peak - cum, t["exit_time"]
    return {"curve": curve, "max_drawdown": worst, "max_drawdown_end": worst_end, "total": cum}


def _group(trips: list[dict], key) -> list[dict]:
    g: dict = defaultdict(list)
    for t in trips:
        g[key(t)].append(t["pnl"])
    return [{"key": k, "n": len(v), "pnl": sum(v), "win_rate": sum(1 for x in v if x > 0) / len(v)}
            for k, v in sorted(g.items())]


WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def stats(trips: list[dict]) -> dict:
    """Statistics of one currency's round trips (already in exit order). Empty input gives n = 0 and no invented numbers."""
    n = len(trips)
    if not n:
        return {"n": 0}
    pnl = [t["pnl"] for t in trips]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    gw, gl = sum(wins), -sum(losses)
    avg_win = _div(gw, len(wins))
    avg_loss = _div(sum(losses), len(losses))
    holds = [t["hold_s"] for t in trips]
    dd = drawdown(trips)
    flags = [x < 0 for x in pnl]
    wk = _group(trips, lambda t: datetime.fromisoformat(t["entry_time"]).weekday())
    hr = _group(trips, lambda t: datetime.fromisoformat(t["entry_time"]).hour)
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "flat": n - len(wins) - len(losses),
        "win_rate": len(wins) / n, "avg_win": avg_win, "avg_loss": avg_loss,
        "payoff": _div(avg_win or 0.0, -(avg_loss or 0.0)) if avg_win is not None and avg_loss else None,
        "expectancy": sum(pnl) / n, "profit_factor": _div(gw, gl), "total_pnl": sum(pnl), "gross_pnl": sum(t["pnl_gross"] for t in trips),
        "fees": sum(t["fees"] for t in trips), "best": max(pnl), "worst": min(pnl),
        "avg_hold_s": statistics.fmean(holds), "median_hold_s": statistics.median(holds),
        "avg_hold_win_s": statistics.fmean([t["hold_s"] for t in trips if t["pnl"] > 0]) if wins else None,
        "avg_hold_loss_s": statistics.fmean([t["hold_s"] for t in trips if t["pnl"] < 0]) if losses else None,
        "max_consec_losses": _streak(flags), "max_consec_wins": _streak([x > 0 for x in pnl]),
        "max_drawdown": dd["max_drawdown"], "max_drawdown_end": dd["max_drawdown_end"],
        "by_symbol": sorted(_group(trips, lambda t: t["symbol"]), key=lambda g: g["pnl"]),
        "by_weekday": [{**g, "key": WEEKDAYS[g["key"]]} for g in wk],
        "by_hour": [{**g, "key": f"{g['key']:02d}:00"} for g in hr],
        "equity": dd["curve"],
        "first": trips[0]["entry_time"] if n else None, "last": trips[-1]["exit_time"] if n else None,
    }


def clean(obj):
    """JSON-safe: non-finite floats become None."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
