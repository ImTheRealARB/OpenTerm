"""Alpaca trading API v2 (paper and live). Shapes are from the Alpaca Trading API documentation; the fixtures that replay them are
labelled doc-shaped and NOT A RECORDING.

PAPER OR LIVE IS STRUCTURAL. Each adapter instance is built for one key slot (`alpaca_paper` or `alpaca_live`, keys.py) and talks to one
host from `HOSTS`. `detect_mode(host, account_number)` derives the mode from that host and refuses a live host that answers with a
paper-looking account number (Alpaca paper account numbers start with PA; checked against the docs, not against a live account). Nothing
in a request, the settings or the AI can change the host. Keys travel in the APCA-API-* headers only.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from ...redact import redact
from ..errors import OrderError
from ..model import Order, qty_text
from .base import OPEN_STATES, Broker, fnum

HOSTS = {"paper": "https://paper-api.alpaca.markets", "live": "https://api.alpaca.markets"}
HOST_MODE = {"paper-api.alpaca.markets": "paper", "api.alpaca.markets": "live"}
ID_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}\Z")
NY = ZoneInfo("America/New_York")
STATUS = {"new": "NEW", "accepted": "NEW", "accepted_for_bidding": "NEW", "held": "NEW", "calculated": "NEW", "partially_filled": "PARTIAL",
          "pending_new": "PENDING", "pending_cancel": "PENDING", "pending_replace": "PENDING", "filled": "FILLED", "canceled": "CANCELED",
          "done_for_day": "CANCELED", "expired": "EXPIRED", "rejected": "REJECTED", "replaced": "REPLACED", "stopped": "CANCELED",
          "suspended": "REJECTED"}


def detect_mode(host: str, account_number: str | None) -> str:
    """paper | live from the host the adapter talks to; OrderError if the host is unknown or the account contradicts it."""
    mode = HOST_MODE.get(urlparse(host).hostname or "")
    if mode is None:
        raise OrderError("mode_mismatch", "UNKNOWN ALPACA HOST: ORDERS REFUSED")
    acct = (account_number or "").upper()
    if mode == "live" and acct.startswith("PA"):
        raise OrderError("mode_mismatch", "THE LIVE HOST ANSWERED WITH A PAPER ACCOUNT NUMBER: ORDERS REFUSED, CHECK THE LIVE KEY")
    return mode


def normalize_order(o: dict) -> dict:
    raw = str(o.get("status") or "")
    return {"id": o.get("id"), "client_id": o.get("client_order_id"), "symbol": o.get("symbol"), "side": o.get("side"),
            "qty": fnum(o.get("qty")), "filled_qty": fnum(o.get("filled_qty")) or 0.0, "type": o.get("type") or o.get("order_type"),
            "tif": o.get("time_in_force"), "limit_price": fnum(o.get("limit_price")), "stop_price": fnum(o.get("stop_price")),
            "status": STATUS.get(raw, raw.upper() or "OTHER"), "raw_status": raw, "avg_fill_price": fnum(o.get("filled_avg_price")),
            "submitted_at": o.get("submitted_at") or o.get("created_at")}


class AlpacaTrading(Broker):
    def __init__(self, slot: str, store, http: httpx.AsyncClient, host: str | None = None):
        if slot not in HOSTS:
            raise ValueError(slot)
        self.slot = slot
        self.id = f"alpaca-{slot}"
        self.label = f"Alpaca {slot}"
        self.key_name = f"alpaca_{slot}"
        self.host = host or HOSTS[slot]  # a test may point at a fake host name; the mode check still runs on it
        self.store = store
        self.http = http
        self.id_field, self.secret_field = (f"ALPACA_{slot.upper()}_KEY_ID", f"ALPACA_{slot.upper()}_SECRET_KEY")

    def not_ready(self) -> OrderError | None:
        if self.store.get(self.key_name) is None:
            return OrderError("key_required", f"KEY REQUIRED: set {self.id_field} and {self.secret_field} in APIKEYS")
        return None

    async def _req(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> Any:
        err = self.not_ready()
        if err:
            raise err
        keys = self.store.get(self.key_name)
        headers = {"APCA-API-KEY-ID": keys[self.id_field], "APCA-API-SECRET-KEY": keys[self.secret_field], "User-Agent": "OpenTerm/0.1",
                   "Accept": "application/json"}
        try:
            r = await self.http.request(method, f"{self.host}{path}", params=params, json=body, headers=headers, timeout=15.0)
        except httpx.TimeoutException as e:
            raise OrderError("unavailable", "ALPACA TIMEOUT") from e
        except httpx.HTTPError as e:
            raise OrderError("unavailable", f"ALPACA UNREACHABLE ({type(e).__name__})") from e
        if r.status_code == 204:
            return None
        try:
            data = r.json()
        except ValueError:
            data = None
        said = str(data.get("message") or "").strip().lower() if isinstance(data, dict) else ""
        if r.status_code == 401 or (r.status_code == 403 and said in ("", "forbidden", "forbidden.")):  # other 403s are order refusals (buying power ...)
            raise OrderError("forbidden", f"ALPACA REFUSED THE {self.slot.upper()} KEY (HTTP {r.status_code}): CHECK IT IN APIKEYS")
        if r.status_code == 429:
            raise OrderError("unavailable", "ALPACA RATE LIMITED (429)")
        if r.status_code == 404:
            raise OrderError("not_found", "ALPACA: NOT FOUND")
        if r.status_code >= 400:
            msg = redact(str(data.get("message") if isinstance(data, dict) and data.get("message") else f"HTTP {r.status_code}"))
            kind = "broker_rejected" if r.status_code in (403, 422) else "unavailable"
            raise OrderError(kind, f"ALPACA: {msg}")
        return data

    async def account(self) -> dict:
        a = await self._req("GET", "/v2/account")
        if not isinstance(a, dict):
            raise OrderError("unavailable", "ALPACA ANSWERED WITH AN UNEXPECTED ACCOUNT BODY")
        mode = detect_mode(self.host, a.get("account_number"))
        return {"broker": self.id, "id": a.get("account_number") or "", "mode": mode, "currency": a.get("currency") or "USD",
                "equity": fnum(a.get("equity")), "cash": fnum(a.get("cash")), "buying_power": fnum(a.get("buying_power")),
                "status": a.get("status"), "trading_blocked": bool(a.get("trading_blocked")), "host": urlparse(self.host).hostname,
                "note": "PAPER ACCOUNT: PLAY MONEY" if mode == "paper" else "LIVE ACCOUNT: REAL MONEY"}

    async def positions(self) -> list[dict]:
        out = []
        for p in await self._req("GET", "/v2/positions") or []:
            qty = fnum(p.get("qty"))
            if qty is None:
                continue
            if p.get("side") == "short" and qty > 0:
                qty = -qty
            out.append({"symbol": p.get("symbol"), "qty": qty, "avg_cost": fnum(p.get("avg_entry_price")),
                        "price": fnum(p.get("current_price")), "market_value": fnum(p.get("market_value"))})
        return out

    async def open_orders(self) -> list[dict]:
        rows = await self._req("GET", "/v2/orders", {"status": "open", "limit": 100, "direction": "desc"}) or []
        return [o for o in map(normalize_order, rows) if o["status"] in OPEN_STATES]

    async def fills_today(self) -> list[dict]:
        day = datetime.now(NY).strftime("%Y-%m-%d")  # the US market date, not the machine's
        rows = await self._req("GET", "/v2/account/activities/FILL", {"date": day}) or []
        acct = (await self._req("GET", "/v2/account") or {}).get("currency") or "USD"
        out = []
        for a in rows:
            q, px = fnum(a.get("qty")), fnum(a.get("price"))
            if q is None or px is None or not a.get("id"):
                continue
            out.append({"fill_id": a["id"], "order_id": a.get("order_id"), "symbol": a.get("symbol"), "side": a.get("side"), "qty": q,
                        "price": px, "at": a.get("transaction_time"), "currency": acct})
        return out

    @staticmethod
    def body(order: Order) -> dict:
        b: dict[str, Any] = {"symbol": order.symbol, "qty": qty_text(order.qty), "side": order.side, "type": order.type, "time_in_force": order.tif}
        if order.limit_price is not None:
            b["limit_price"] = f"{order.limit_price:g}"
        if order.stop_price is not None:
            b["stop_price"] = f"{order.stop_price:g}"
        return b

    async def submit(self, order: Order, client_id: str) -> dict:
        o = await self._req("POST", "/v2/orders", body={**self.body(order), "client_order_id": client_id})
        if not isinstance(o, dict) or not o.get("id"):
            raise OrderError("unavailable", "ALPACA ANSWERED WITHOUT AN ORDER ID: CHECK THE BLOTTER BEFORE SENDING AGAIN")
        return normalize_order(o)

    @staticmethod
    def _check_id(order_id: str) -> str:
        if not isinstance(order_id, str) or not ID_RE.match(order_id):
            raise OrderError("bad_request", "BAD ORDER ID")
        return order_id

    async def cancel(self, order_id: str) -> None:
        await self._req("DELETE", f"/v2/orders/{self._check_id(order_id)}")

    async def cancel_all(self) -> list[dict]:
        rows = await self._req("DELETE", "/v2/orders") or []
        return [{"id": r.get("id"), "ok": 200 <= int(r.get("status") or 0) < 300, "detail": f"HTTP {r.get('status')}"} for r in rows if isinstance(r, dict)]

    async def replace(self, order_id: str, order: Order) -> dict:
        patch: dict[str, Any] = {"qty": qty_text(order.qty), "time_in_force": order.tif}
        if order.limit_price is not None:
            patch["limit_price"] = f"{order.limit_price:g}"
        if order.stop_price is not None:
            patch["stop_price"] = f"{order.stop_price:g}"
        o = await self._req("PATCH", f"/v2/orders/{self._check_id(order_id)}", body=patch)
        return normalize_order(o or {})
