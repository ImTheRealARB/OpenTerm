"""Kite Connect holdings and net positions -> OpenTerm lots. Pure: no network, no database.

Kite answers `GET /portfolio/holdings` (a list) and `GET /portfolio/positions` (`{"net": [...], "day": [...]}`). Every Kite exchange
quotes in rupees, so every lot is INR. A lot is `{symbol, qty, cost, currency}` with the Yahoo-style symbol the rest of OpenTerm uses
(`INFY` on NSE is `INFY.NS`). Rows that cannot be mapped are returned in `skipped` with the reason, never dropped silently.
"""

from __future__ import annotations

from ..kite.symbols import to_yahoo
from ..portfolio import check_position
from ..userdata import UserDataError

CURRENCY = "INR"
#: product codes whose net positions are intraday / derivative positions that holdings do not already show (CNC delivery is in holdings)
POSITION_PRODUCTS = ("MIS", "NRML", "MTF")
ZERO = "ZERO QUANTITY"


def _num(x) -> float | None:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else None


def _lot(exchange: str, trading: str, qty: float | None, price: float | None) -> tuple[dict | None, str | None]:
    if qty is None or qty == 0:
        return None, ZERO
    sym = to_yahoo(f"{exchange}:{trading}") if exchange and trading else None
    if sym is None:
        return None, f"UNMAPPED KITE INSTRUMENT {exchange}:{trading}"
    try:
        lot = check_position({"symbol": sym, "qty": qty, "cost": price if price is not None and price >= 0 else None,
                              "currency": CURRENCY})
    except UserDataError as e:
        return None, str(e)
    return lot, None


def map_holdings(rows) -> tuple[list[dict], list[dict], list[str]]:
    """(lots, skipped, warnings) for the holdings list. Quantity is Kite's `quantity` (settled plus T+1); collateral is not added."""
    lots: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        exchange, trading = str(r.get("exchange") or "").upper(), str(r.get("tradingsymbol") or "").upper()
        qty = _num(r.get("quantity"))
        if qty is None:
            qty = (_num(r.get("realised_quantity")) or 0) + (_num(r.get("t1_quantity")) or 0)
        lot, why = _lot(exchange, trading, qty, _num(r.get("average_price")))
        if lot is None:
            if why != ZERO:  # a sold-out or fully pledged holding row is not worth a line
                skipped.append({"symbol": f"{exchange}:{trading}", "reason": why})
            continue
        if (_num(r.get("collateral_quantity")) or 0) > 0:
            warnings.append(f"{lot['symbol']}: {int(r['collateral_quantity'])} SHARES ARE COLLATERAL AND NOT ADDED. CHECK AGAINST KITE")
        lots.append(lot)
    return lots, skipped, warnings


def map_positions(body) -> tuple[list[dict], list[dict]]:
    """Net MIS / NRML / MTF positions (signed quantity, average price). CNC rows are skipped: they are the holdings."""
    lots: list[dict] = []
    skipped: list[dict] = []
    net = body.get("net") if isinstance(body, dict) else None
    for r in net if isinstance(net, list) else []:
        if not isinstance(r, dict) or str(r.get("product") or "").upper() not in POSITION_PRODUCTS:
            continue
        exchange, trading = str(r.get("exchange") or "").upper(), str(r.get("tradingsymbol") or "").upper()
        lot, why = _lot(exchange, trading, _num(r.get("quantity")), _num(r.get("average_price")))
        if lot is None:
            if why != ZERO:
                skipped.append({"symbol": f"{exchange}:{trading}", "reason": why})
            continue
        lots.append(lot)
    return lots, skipped
