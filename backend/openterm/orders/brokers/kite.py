"""Zerodha Kite Connect orders (live only). Shapes are from the Kite Connect v3 documentation (orders, trades, portfolio, margins); the
fixtures that replay them are labelled doc-shaped and NOT A RECORDING.

Kite has NO paper mode. `mode` is therefore always "live", and the adapter says so on screen (`note`). The host is the constant KITE_API
(api.kite.trade); the mode is asserted from it, not from anything a request carries. The login, the daily token and the rate limits are
the read-only client's (kite/client.py); this adapter only adds the order calls on top of `KiteClient.call`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ...errors import DataError
from ...kite import KITE_API
from ...kite.symbols import split_key, to_kite, to_yahoo
from ...redact import redact
from ..errors import OrderError
from ..model import Order
from .base import OPEN_STATES, Broker, fnum

KITE_HOST = "api.kite.trade"
OPEN_RAW = {"OPEN", "TRIGGER PENDING", "PUT ORDER REQ RECEIVED", "VALIDATION PENDING", "MODIFY VALIDATION PENDING", "MODIFY PENDING",
            "OPEN PENDING", "AMO REQ RECEIVED", "CANCEL PENDING", "UPDATE"}
TYPE_OUT = {"market": "MARKET", "limit": "LIMIT", "stop": "SL-M"}
TYPE_IN = {"MARKET": "market", "LIMIT": "limit", "SL": "stop", "SL-M": "stop"}
VALIDITY_OUT = {"day": "DAY", "ioc": "IOC"}
ID_OK = set("0123456789")


def detect_mode() -> str:
    """Kite has one trading host and no sandbox: always live. Refuses if the client's host constant ever stops being Kite's."""
    if urlparse(KITE_API).hostname != KITE_HOST:
        raise OrderError("mode_mismatch", "THE KITE HOST IS NOT api.kite.trade: ORDERS REFUSED")
    return "live"


def status_of(raw: str, filled: float) -> str:
    if raw == "COMPLETE":
        return "FILLED"
    if raw == "REJECTED":
        return "REJECTED"
    if raw == "CANCELLED":
        return "CANCELED"
    if raw in OPEN_RAW:
        return "PARTIAL" if filled > 0 else "PENDING" if raw in ("VALIDATION PENDING", "PUT ORDER REQ RECEIVED", "CANCEL PENDING") else "NEW"
    return raw or "OTHER"


def symbol_of(exchange: str, trading: str) -> str:
    return to_yahoo(f"{exchange}:{trading}") or f"{trading}.{exchange}"


def normalize_order(o: dict) -> dict:
    filled = fnum(o.get("filled_quantity")) or 0.0
    raw = str(o.get("status") or "")
    return {"id": o.get("order_id"), "client_id": o.get("tag"), "symbol": symbol_of(str(o.get("exchange") or ""), str(o.get("tradingsymbol") or "")),
            "side": str(o.get("transaction_type") or "").lower(), "qty": fnum(o.get("quantity")), "filled_qty": filled,
            "type": TYPE_IN.get(str(o.get("order_type")), str(o.get("order_type") or "").lower()), "tif": str(o.get("validity") or "").lower(),
            "limit_price": fnum(o.get("price")) or None, "stop_price": fnum(o.get("trigger_price")) or None,
            "status": status_of(raw, filled), "raw_status": raw, "avg_fill_price": fnum(o.get("average_price")) or None,
            "submitted_at": o.get("order_timestamp")}


def default_product(exchange: str) -> str:
    return "NRML" if exchange in ("NFO", "BFO", "MCX", "CDS") else "CNC"


class KiteTrading(Broker):
    id = "kite"
    label = "Zerodha Kite"
    note = "KITE HAS NO PAPER MODE: EVERY KITE ORDER IS REAL MONEY"

    def __init__(self, kite):
        self.kite = kite  # providers.kite.KiteProvider: .session, .client, .instruments

    def not_ready(self) -> OrderError | None:
        s = self.kite.session
        if s is None or s.state == "NO KEY":
            return OrderError("key_required", "KEY REQUIRED: set KITE_API_KEY in APIKEYS")
        if s.state == "LOGGED OUT":
            return OrderError("login_required", s.message() or "KITE LOGGED OUT: run KITE LOGIN")
        if s.state != "OK":
            return OrderError("login_expired", s.message() or "KITE LOGIN EXPIRED: run KITE LOGIN")
        return None

    async def _call(self, method: str, path: str, params: dict | None = None, data: dict | None = None) -> Any:
        err = self.not_ready()
        if err:
            raise err
        try:
            return await self.kite.client.call(method, path, params, data)
        except DataError as e:
            kind = e.kind if e.kind in ("key_required", "login_required", "login_expired", "not_found") else "unavailable"
            msg = redact(str(e))
            if kind == "unavailable" and method != "GET" and msg.startswith("KITE:"):
                kind = "broker_rejected"
            raise OrderError(kind, msg) from e

    async def account(self) -> dict:
        mode = detect_mode()
        m = await self._call("GET", "/user/margins")
        eq = (m or {}).get("equity") or {}
        av = eq.get("available") or {}
        return {"broker": self.id, "id": self.kite.session.status().get("user") or "KITE", "mode": mode, "currency": "INR",
                "equity": fnum(eq.get("net")), "cash": fnum(av.get("cash")), "buying_power": fnum(av.get("live_balance")),
                "status": "ACTIVE" if eq.get("enabled", True) else "DISABLED", "trading_blocked": not eq.get("enabled", True),
                "host": KITE_HOST, "note": self.note}

    async def positions(self) -> list[dict]:
        """Net positions plus delivered holdings (T1 included). A CNC buy made today can appear in both: exposure is then overstated, which is
        the safe side for a cap."""
        out = []
        pos = await self._call("GET", "/portfolio/positions")
        for p in (pos or {}).get("net") or []:
            q, px = fnum(p.get("quantity")), fnum(p.get("last_price"))
            if q:
                out.append({"symbol": symbol_of(p.get("exchange", ""), p.get("tradingsymbol", "")), "qty": q, "avg_cost": fnum(p.get("average_price")),
                            "price": px, "market_value": q * px if px is not None else None})
        for h in await self._call("GET", "/portfolio/holdings") or []:
            q = (fnum(h.get("quantity")) or 0.0) + (fnum(h.get("t1_quantity")) or 0.0)
            px = fnum(h.get("last_price"))
            if q:
                out.append({"symbol": symbol_of(h.get("exchange", ""), h.get("tradingsymbol", "")), "qty": q, "avg_cost": fnum(h.get("average_price")),
                            "price": px, "market_value": q * px if px is not None else None})
        return out

    async def open_orders(self) -> list[dict]:
        rows = await self._call("GET", "/orders") or []
        return [o for o in map(normalize_order, rows) if o["status"] in OPEN_STATES]

    async def fills_today(self) -> list[dict]:
        out = []
        for t in await self._call("GET", "/trades") or []:
            q, px = fnum(t.get("quantity")), fnum(t.get("average_price"))
            if q is None or px is None or not t.get("trade_id"):
                continue
            out.append({"fill_id": str(t["trade_id"]), "order_id": t.get("order_id"), "symbol": symbol_of(t.get("exchange", ""), t.get("tradingsymbol", "")),
                        "side": str(t.get("transaction_type") or "").lower(), "qty": q, "price": px, "at": t.get("fill_timestamp"), "currency": "INR"})
        return out

    async def _form(self, order: Order, client_id: str | None) -> dict[str, Any]:
        key = to_kite(order.symbol)
        if key is None:
            raise OrderError("bad_request", "NOT A KITE SYMBOL: USE RELIANCE.NS, TCS.BO, <X>.NFO OR <X>.MCX")
        inst = await self.kite.instruments.resolve(key)
        if inst is None:
            raise OrderError("not_found", f"{key} IS NOT IN THE KITE INSTRUMENT DUMP")
        exchange, trading = split_key(key)
        form: dict[str, Any] = {"exchange": exchange, "tradingsymbol": trading, "transaction_type": order.side.upper(),
                                "order_type": TYPE_OUT[order.type], "quantity": int(order.qty), "product": order.product or default_product(exchange),
                                "validity": VALIDITY_OUT[order.tif]}
        if order.limit_price is not None:
            form["price"] = f"{order.limit_price:g}"
        if order.stop_price is not None:
            form["trigger_price"] = f"{order.stop_price:g}"
        if client_id:
            form["tag"] = client_id[:20]
        return form

    async def submit(self, order: Order, client_id: str) -> dict:
        data = await self._call("POST", "/orders/regular", data=await self._form(order, client_id))
        oid = (data or {}).get("order_id")
        if not oid:
            raise OrderError("unavailable", "KITE ANSWERED WITHOUT AN ORDER ID: CHECK THE BLOTTER BEFORE SENDING AGAIN")
        return {"id": str(oid), "client_id": client_id, "symbol": order.symbol, "side": order.side, "qty": order.qty, "filled_qty": 0.0,
                "type": order.type, "tif": order.tif, "limit_price": order.limit_price, "stop_price": order.stop_price, "status": "PENDING",
                "raw_status": "SUBMITTED", "avg_fill_price": None, "submitted_at": None}

    @staticmethod
    def _check_id(order_id: str) -> str:
        if not isinstance(order_id, str) or not order_id or not set(order_id) <= ID_OK or len(order_id) > 32:
            raise OrderError("bad_request", "BAD ORDER ID")
        return order_id

    async def cancel(self, order_id: str) -> None:
        await self._call("DELETE", f"/orders/regular/{self._check_id(order_id)}")

    async def cancel_all(self) -> list[dict]:
        out = []
        for o in await self.open_orders():
            try:
                await self.cancel(o["id"])
                out.append({"id": o["id"], "ok": True, "detail": "CANCEL SENT"})
            except OrderError as e:
                out.append({"id": o["id"], "ok": False, "detail": str(e)})
        return out

    async def replace(self, order_id: str, order: Order) -> dict:
        form = await self._form(order, None)
        form = {k: v for k, v in form.items() if k in ("quantity", "price", "trigger_price", "order_type", "validity")}
        data = await self._call("PUT", f"/orders/regular/{self._check_id(order_id)}", data=form)
        return {"id": str((data or {}).get("order_id") or order_id), "status": "PENDING"}
