"""Kite order flow for Indian symbols (Phase 23 gap): the DOM depth ladder and the tick-rule TAS tape. Read-only.

What Kite gives: in `full` mode a packet carries the best FIVE bid and ask levels (quantity, price, orders); in any mode it carries the
last price and the day's cumulative volume. It does NOT carry individual trades or who started them. So:

  * DOM shows five levels a side (not a deep book like crypto's 100): the venue label says "BEST 5 LEVELS".
  * TAS shows one row per packet that gained volume: price = the last price, quantity = the volume gained since the previous packet
    (several trades can share a row), side = the TICK RULE guess (`orderflow.tick_rule`: price up = buy, down = sell, same = as before).
    Always labelled ESTIMATED (TICK RULE). Prints before the first price move have no side and are counted in `unsided`, not drawn.

The data lives in `kite.ws.KiteTicker` (`books`, `tape`); this file only shapes it, and turns "no login / no packet yet" into plain
errors. Pure apart from `time.time()`; the ticker is passed in.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from .. import errkinds as K
from ..errors import DataError
from ..providers.base import ProviderError
from . import cryptodepth as cd
from . import orderflow as of

STALE_S = 30.0  # a book or tape older than this is marked stale (the market may be closed)
VENUE_DEPTH = "KITE · BEST 5 LEVELS A SIDE (REAL TIME)"
VENUE_TAPE = "KITE (REAL TIME)"
TAPE_NOTE = ("ONE ROW PER KITE PACKET THAT GAINED VOLUME: PRICE = LAST PRICE, QTY = VOLUME GAINED SINCE THE PREVIOUS PACKET "
             "(SEVERAL TRADES CAN SHARE A ROW). SIDE = TICK RULE GUESS, NOT REPORTED BY THE EXCHANGE.")
# A print as the ticker keeps it: (sequence number, epoch ms, price, quantity gained).
Print = tuple[int, int, float, int]


def need_ticker(ticker: Any) -> None:
    """Raises the right DataError unless the Kite ticker exists and the login is valid."""
    if ticker is None:
        raise DataError(K.UNSUPPORTED, "KITE TICKER IS NOT RUNNING (FIXTURE MODE)")
    if not ticker.session.logged_in:
        kind = {"NO KEY": K.KEY_REQUIRED, "KITE LOGIN EXPIRED": K.LOGIN_EXPIRED}.get(ticker.session.state, K.LOGIN_REQUIRED)
        raise DataError(kind, ticker.session.message() or "KITE LOGIN NEEDED")


def _envelope(data: dict[str, Any], newest_ms: int | None) -> dict[str, Any]:
    now = time.time()
    age = max(0.0, now - newest_ms / 1000.0) if newest_ms else 0.0
    return {"data": data, "source": "kite", "as_of": now, "age_s": age, "stale": age > STALE_S, "fallback_from": []}


# --- depth (DOM) --------------------------------------------------------------------------------------------------------------------

def depth_payload(symbol: str, book: dict[str, Any], quote: str = "INR") -> dict[str, Any]:
    """The CDEP / DOM payload shape for one Kite book: `book` = {t (ms), buy, sell} with (qty, price, orders) per level. Levels with no
    quantity are empty slots and are dropped; a book empty on one side is an error (never a made-up ladder)."""
    bids = [(price, float(qty)) for qty, price, _orders in book["buy"] if qty > 0]
    asks = [(price, float(qty)) for qty, price, _orders in book["sell"] if qty > 0]
    try:
        summary = cd.depth_summary(bids, asks, quote)
    except ProviderError as e:
        raise DataError(K.UNAVAILABLE, "KITE SENT AN EMPTY BOOK FOR " + symbol + ": NO BIDS OR NO ASKS (MARKET CLOSED OR NO ORDERS)") from e
    return {"base": symbol, "symbol": symbol, "venue": VENUE_DEPTH, "ts_ms": book["t"], **summary,
            "orders": {"bid": sum(o for _q, _p, o in book["buy"]), "ask": sum(o for _q, _p, o in book["sell"])}}


def depth(ticker: Any, symbol: str) -> dict[str, Any]:
    """DOM for an Indian symbol: asks Kite to stream the symbol in full mode (the first answer can take a few seconds) and returns its book."""
    need_ticker(ticker)
    sym = symbol.strip().upper()
    try:
        ticker.pin(sym, depth=True)
    except ValueError as e:
        raise DataError(K.BAD_REQUEST, str(e)) from e
    book = ticker.books.get(sym)
    if book is None:
        raise DataError(K.UNAVAILABLE, f"WAITING FOR KITE'S FIRST DEPTH PACKET FOR {sym} (A FEW SECONDS; THE PANEL ASKS AGAIN BY ITSELF)")
    return _envelope(depth_payload(sym, book), book["t"])


# --- tape (TAS) ---------------------------------------------------------------------------------------------------------------------

def sided_rows(prints: Sequence[Print]) -> tuple[list[dict[str, Any]], int]:
    """Oldest-first prints -> TAS rows with the tick-rule side, plus how many prints could not be given a side (the ones before the
    first price move)."""
    sides = of.tick_rule([p[2] for p in prints])
    rows: list[dict[str, Any]] = []
    unsided = 0
    for (seq, t, price, qty), s in zip(prints, sides, strict=True):
        if qty == 0:  # a reference print (the first packet of the day): it only gave the next price something to compare with
            continue
        if s is None:
            unsided += 1
            continue
        rows.append({"id": seq, "t": t, "p": price, "q": float(qty), "value": price * qty, "side": "BUY" if s == "B" else "SELL"})
    return rows, unsided


def tas_head(symbol: str, rows: list[dict[str, Any]], unsided: int, venue: str = VENUE_TAPE) -> dict[str, Any]:
    """The fields every TAS answer carries (the crypto `_head` shape), for an Indian symbol quoted in rupees."""
    span = (rows[-1]["t"] - rows[0]["t"]) / 1000.0 if rows else 0.0
    return {"symbol": symbol, "pair": symbol, "base": "SHARES", "quote": "INR", "quote_is_usd": False, "venue": venue, "basis": of.LABEL_TICK_RULE,
            "n": len(rows), "span_s": span, "newest_t": rows[-1]["t"] if rows else None, "unsided": unsided, "note": TAPE_NOTE}


def tas_payload(symbol: str, prints: Sequence[Print], limit: int, venue: str = VENUE_TAPE) -> dict[str, Any]:
    rows, unsided = sided_rows(prints)
    return {**tas_head(symbol, rows, unsided, venue), "rows": rows[::-1][:limit]}  # newest first, like the crypto TAS


def tas(ticker: Any, symbol: str, limit: int) -> dict[str, Any]:
    """TAS for an Indian symbol: subscribes it (even with no chart open) and answers with what the ticker has seen since."""
    need_ticker(ticker)
    sym = symbol.strip().upper()
    try:
        ticker.pin(sym)
    except ValueError as e:
        raise DataError(K.BAD_REQUEST, str(e)) from e
    prints = list(ticker.tape.get(sym, ()))
    if not prints:
        raise DataError(K.UNAVAILABLE, f"NO KITE PRINTS FOR {sym} YET: THE TAPE FILLS WHILE THE MARKET TRADES (THE PANEL ASKS AGAIN BY ITSELF)")
    return _envelope(tas_payload(sym, prints, limit), prints[-1][1])
