"""What every broker adapter offers, and the normalised shapes the rest of the order code works with.

Normalised order: {id, client_id, symbol, side, qty, filled_qty, type, tif, limit_price, stop_price, status, raw_status, avg_fill_price,
submitted_at}. `status` is one of NEW PARTIAL PENDING FILLED CANCELED REJECTED EXPIRED REPLACED OTHER; OPEN_STATES are the ones a cancel can still act on.
Normalised position: {symbol, qty (signed), avg_cost, price, market_value}. Normalised fill: {fill_id, order_id, symbol, side, qty, price, at, currency}.
Normalised account: {broker, id, mode ("paper" | "live"), currency, equity, cash, buying_power, status, host, note}.
"""

from __future__ import annotations

from typing import Any

from ..errors import OrderError
from ..model import Order

OPEN_STATES = ("NEW", "PARTIAL", "PENDING")


def fnum(x: Any) -> float | None:
    """A broker number (Alpaca sends strings) as a float, or None when it is missing or not a number."""
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


class Broker:
    id = ""
    label = ""
    #: shown on screen when the broker has no paper mode
    note = ""

    def not_ready(self) -> OrderError | None:
        """None when keys (and login) are in place, else the OrderError that says what to set. No network."""
        raise NotImplementedError

    async def account(self) -> dict:
        """The account with its `mode`, derived from the host this adapter talks to and checked against the broker's own answer."""
        raise NotImplementedError

    async def positions(self) -> list[dict]:
        raise NotImplementedError

    async def open_orders(self) -> list[dict]:
        raise NotImplementedError

    async def fills_today(self) -> list[dict]:
        raise NotImplementedError

    async def submit(self, order: Order, client_id: str) -> dict:
        raise NotImplementedError

    async def cancel(self, order_id: str) -> None:
        raise NotImplementedError

    async def cancel_all(self) -> list[dict]:
        """Cancel every open order. Returns [{id, ok, detail}]."""
        raise NotImplementedError

    async def replace(self, order_id: str, order: Order) -> dict:
        raise NotImplementedError
