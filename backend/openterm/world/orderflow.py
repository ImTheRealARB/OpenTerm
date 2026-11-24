"""Order flow (Phase 23 items 4 and 6): pure parsers and maths. No network, no pandas.

What an "aggregated trade" is: Binance merges every fill of one taker order at one price into ONE row (`aggTrades`).
Each row says who started the trade. Field `m` means "the BUYER is the MAKER", i.e. the buyer was the resting limit order,
so the one who crossed the spread (the AGGRESSOR) was the SELLER. So:

    m == true   -> aggressor SOLD  -> the trade happened at the BID    -> "SELL"
    m == false  -> aggressor BOUGHT -> the trade happened at the ASK   -> "BUY"

That is exact, not estimated, because the exchange tells us. (Stocks have no such flag in free data; there the best we can do
is the TICK RULE below, which is a guess and is always labelled ESTIMATED.)

Footprint vocabulary used by the functions below:
  bid volume  = coins sold into the bid (aggressor sells) at a price level in one bar
  ask volume  = coins bought from the ask (aggressor buys) at a price level in one bar
  delta       = ask volume - bid volume (positive = buyers were more aggressive)
  cumulative delta = running sum of the bars' deltas across the window
  imbalance   = one side at least IMBALANCE_RATIO times the opposite side one level away (diagonal, see `footprint`)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, NamedTuple

from ..providers.base import ProviderError

LABEL_EXACT = "EXACT (EXCHANGE TRADES)"
LABEL_TICK_RULE = "ESTIMATED (TICK RULE)"

IMBALANCE_RATIO = 3.0  # "3:1": the bigger side must be at least 3x the opposite side
MIN_SHARE = 0.02  # ...and (when the opposite side is empty) at least 2% of the bar's volume, so dust at a bar's edge is not flagged
TARGET_LEVELS = 40  # the automatic price step aims at about this many rows for the whole window
INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}

# Flag bits on a footprint cell (`cell[3]`): which side of the cell shows an imbalance.
FLAG_ASK = 1  # buyers dominate (ask volume vs the bid volume one level BELOW)
FLAG_BID = 2  # sellers dominate (bid volume vs the ask volume one level ABOVE)


class Trade(NamedTuple):
    """One aggregated trade. `buy` is the aggressor side (True = bought at the ask)."""

    id: int
    t: int  # ms since the epoch (the exchange's clock)
    p: float
    q: float  # base coins
    buy: bool


def parse_agg_trades(body: Any) -> list[Trade]:
    """Binance `GET /api/v3/aggTrades` -> trades, oldest first. A malformed answer fails loudly (never a silent empty list)."""
    if not isinstance(body, list):
        raise ProviderError("unavailable", "BINANCE AGGTRADES: UNEXPECTED ANSWER")
    out: list[Trade] = []
    for r in body:
        try:
            out.append(Trade(int(r["a"]), int(r["T"]), float(r["p"]), float(r["q"]), not bool(r["m"])))
        except (KeyError, TypeError, ValueError) as e:
            raise ProviderError("unavailable", "BINANCE AGGTRADES: UNEXPECTED ROW") from e
    out.sort(key=lambda x: x.id)
    return out


def merge_pages(pages: Sequence[Sequence[Trade]]) -> list[Trade]:
    """Joins pages fetched newest-first, dropping repeated ids (a page boundary can overlap), oldest first."""
    seen: dict[int, Trade] = {}
    for page in pages:
        for tr in page:
            seen.setdefault(tr.id, tr)
    return sorted(seen.values(), key=lambda x: x.id)


# --- time and sales / big trades -------------------------------------------------------------------------------------------------------


def trade_row(tr: Trade) -> dict[str, Any]:
    """One TAS / BIGT row. `value` = price x coins in the QUOTE currency (USD only for USDT / USDC / USD pairs)."""
    return {"id": tr.id, "t": tr.t, "p": tr.p, "q": tr.q, "value": tr.p * tr.q, "side": "BUY" if tr.buy else "SELL"}


def recent(trades: Sequence[Trade], limit: int) -> list[dict[str, Any]]:
    """The newest `limit` trades, newest first (TAS)."""
    return [trade_row(tr) for tr in reversed(trades[-limit:])]


def big_trades(trades: Sequence[Trade], min_qty: float | None = None, min_value: float | None = None) -> list[Trade]:
    """Trades at least `min_qty` coins OR (when given instead) at least `min_value` in the quote currency; newest first.
    Both given = both must hold. Neither given is a caller bug, so it raises instead of returning everything."""
    if min_qty is None and min_value is None:
        raise ValueError("BIGT NEEDS MIN=<COINS> OR USD=<AMOUNT>")
    return [tr for tr in reversed(trades) if (min_qty is None or tr.q >= min_qty) and (min_value is None or tr.p * tr.q >= min_value)]


# --- footprint -------------------------------------------------------------------------------------------------------------------------


def bar_start(t_ms: int, interval_ms: int) -> int:
    """Start (ms) of the bar a trade at `t_ms` belongs to. Bars are aligned to the epoch, like the exchange's own candles."""
    return t_ms - t_ms % interval_ms


def nice_step(raw: float) -> float:
    """Rounds `raw` UP to 1, 2 or 5 times a power of ten: a price step that reads well (0.5, 1, 2, 5, 10 ...)."""
    if not raw > 0 or math.isinf(raw):
        raise ValueError("PRICE STEP MUST BE POSITIVE")
    exp = math.floor(math.log10(raw))
    frac = raw / 10**exp
    for nice in (1.0, 2.0, 5.0, 10.0):
        if frac <= nice + 1e-12:
            return round(nice * 10**exp, 12)
    return round(10.0 * 10**exp, 12)  # unreachable (frac < 10); kept so the function always returns


def _level_index(price: float, step: float) -> int:
    """Row number of a price: floor(price / step). The tiny epsilon stops 100.3 / 0.1 landing one row low from float rounding."""
    return math.floor(price / step + 1e-9)


def footprint(
    trades: Sequence[Trade],
    interval_ms: int,
    bars: int,
    step: float | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """Footprint of the newest `bars` bars: per bar and price level, the bid (sell aggressor) and ask (buy aggressor) volume.

    Imbalance is DIAGONAL, the usual footprint convention: a buyers' imbalance at level L compares the ASK volume at L with the
    BID volume one level below (L - 1), because a buyer lifting the ask at L is "paid up" past the last bid; a sellers'
    imbalance compares the BID volume at L with the ASK volume one level above (L + 1). A side is flagged when it is at least
    IMBALANCE_RATIO times the opposite one. When the opposite side is empty the ratio is infinite, so the flagged side must
    also hold at least MIN_SHARE of the whole bar's volume (otherwise every thin edge cell would light up).

    `truncated` = the caller could not fetch trades back over the whole window: the oldest bar is marked `partial`.
    Returns {"interval_ms", "step", "levels" (ascending prices), "bars" [...], "cum_delta" [...]}; a bar's `cells` are sparse
    `[level_index, bid, ask, flag]` lists (index into `levels`), highest-volume info in `poc` (the price with the most volume).
    """
    if interval_ms <= 0 or bars <= 0:
        raise ValueError("INTERVAL AND BAR COUNT MUST BE POSITIVE")
    if not trades:
        return {"interval_ms": interval_ms, "step": step, "levels": [], "bars": [], "cum_delta": []}

    newest_start = bar_start(trades[-1].t, interval_ms)
    first_start = newest_start - (bars - 1) * interval_ms
    window = [tr for tr in trades if tr.t >= first_start]  # trades are oldest first (parse_agg_trades sorts)
    if not window:  # cannot happen (the newest trade is always inside), kept as a guard against a caller passing unsorted trades
        raise ValueError("TRADES MUST BE SORTED OLDEST FIRST")

    lo = min(tr.p for tr in window)
    hi = max(tr.p for tr in window)
    if step is None:
        step = nice_step((hi - lo) / TARGET_LEVELS if hi > lo else lo * 1e-4)
    elif not step > 0:
        raise ValueError("PRICE STEP MUST BE POSITIVE")
    lo_idx = _level_index(lo, step)
    hi_idx = _level_index(hi, step)
    levels = [round((lo_idx + i) * step, 10) for i in range(hi_idx - lo_idx + 1)]

    # One accumulator per bar: {level index: [bid, ask]} plus the bar's open / high / low / close.
    acc: dict[int, dict[str, Any]] = {}
    for tr in window:
        b = acc.setdefault(bar_start(tr.t, interval_ms), {"cells": {}, "o": tr.p, "h": tr.p, "l": tr.p, "c": tr.p})
        b["h"] = max(b["h"], tr.p)
        b["l"] = min(b["l"], tr.p)
        b["c"] = tr.p
        cell = b["cells"].setdefault(_level_index(tr.p, step) - lo_idx, [0.0, 0.0])
        cell[1 if tr.buy else 0] += tr.q  # buy aggressor = ask volume (index 1); sell aggressor = bid volume (index 0)

    out_bars: list[dict[str, Any]] = []
    cum: list[float] = []
    running = 0.0
    for start in sorted(acc):
        b = acc[start]
        cells: dict[int, list[float]] = b["cells"]
        bid_total = sum(c[0] for c in cells.values())
        ask_total = sum(c[1] for c in cells.values())
        vol = bid_total + ask_total
        floor_vol = MIN_SHARE * vol
        rows: list[list[float]] = []
        for lvl in sorted(cells):
            bid, ask = cells[lvl]
            below_bid = cells.get(lvl - 1, (0.0, 0.0))[0]
            above_ask = cells.get(lvl + 1, (0.0, 0.0))[1]
            flag = 0
            if ask > 0 and ask >= IMBALANCE_RATIO * below_bid and (below_bid > 0 or ask >= floor_vol):
                flag |= FLAG_ASK
            if bid > 0 and bid >= IMBALANCE_RATIO * above_ask and (above_ask > 0 or bid >= floor_vol):
                flag |= FLAG_BID
            rows.append([lvl, bid, ask, flag])
        poc_lvl = max(cells, key=lambda k: cells[k][0] + cells[k][1])
        delta = ask_total - bid_total
        running += delta
        cum.append(running)
        out_bars.append({"t": start, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "bid": bid_total, "ask": ask_total, "vol": vol,
                         "delta": delta, "cum_delta": running, "poc": levels[poc_lvl], "cells": rows, "partial": False})
    if truncated and out_bars:
        out_bars[0]["partial"] = True  # the oldest bar we hold is the one the missing older trades would have filled
    return {"interval_ms": interval_ms, "step": step, "levels": levels, "bars": out_bars, "cum_delta": cum}


# --- tick rule (item 6) ----------------------------------------------------------------------------------------------------------------


def tick_rule(prices: Sequence[float], prev_price: float | None = None, prev_side: str | None = None) -> list[str | None]:
    """The TICK RULE: classes each trade price as "B" (buy) when it rose, "S" (sell) when it fell, and the SAME side as the previous
    trade when it did not change. The first trade has no previous one, so it is None (unknown) unless the caller passes the price
    and side that came before it (to continue a stream). This is an ESTIMATE (the feed does not say who the aggressor was): panels
    that use it must label it ESTIMATED (TICK RULE), never EXACT."""
    out: list[str | None] = []
    last_p, last_side = prev_price, prev_side
    for p in prices:
        if last_p is None:
            side = None
        elif p > last_p:
            side = "B"
        elif p < last_p:
            side = "S"
        else:
            side = last_side
        out.append(side)
        last_p, last_side = p, side
    return out
