"""OrderService: the only way an order reaches a broker.

submit() order of checks (each one a refusal that is written to the ledger):
  1. kill switch off            2. keys / login present        3. account read from the broker: mode from its host and account
  4. live switched on by the user (live only)                   5. mandate passes (allowlist, size, notional, gross exposure, daily cap)
  6. a fresh one-time confirm token issued for exactly this order, mode and account
then `submitted` is written to the ledger BEFORE the broker is called, and `accepted` or `failed` after.
A lock serialises preview-to-send, so two orders cannot both pass the daily cap, and the kill switch is read again inside it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from ..portfolio import Portfolios
from ..redact import redact
from ..userdata import UserDataError
from . import mandate as mandate_mod
from .brokers.base import Broker
from .confirm import ConfirmTokens
from .errors import OrderError
from .ledger import OrderLedger
from .model import Order, fingerprint
from .store import OrdersStore

log = logging.getLogger("openterm.orders")
LIVE_PHRASE = "I UNDERSTAND LIVE ORDERS USE REAL MONEY"
EXPECTED_MODE = {"alpaca-paper": "paper", "alpaca-live": "live", "kite": "live"}
# `source` written on a lot that comes from an order fill. Never "kite" or "ibkr": those are the read-only SYNC's own tags (brokers/sync.py), and a SYNC
# replaces every lot carrying its tag, so an order fill with it would be deleted by the next sync. Lots with these tags are left alone by SYNC.
FILL_SOURCE = {"alpaca-paper": "paper", "alpaca-live": "alpaca", "kite": "kite-orders"}


class OrderService:
    def __init__(self, db, ledger: OrderLedger, brokers: dict[str, Broker], price_fn, tokens: ConfirmTokens | None = None):
        self.store = OrdersStore(db)
        self.db = db
        self.ledger = ledger
        self.brokers = brokers
        self.price_fn = price_fn  # async (symbol) -> (price | None, note)
        self.tokens = tokens or ConfirmTokens()
        self.lock = asyncio.Lock()

    # --- lookups ---
    def broker(self, broker_id: str) -> Broker:
        b = self.brokers.get(broker_id)
        if b is None:
            raise OrderError("bad_request", f"UNKNOWN BROKER {str(broker_id)[:24]}")
        return b

    async def _ready_account(self, b: Broker) -> dict:
        """The broker's account, with `mode` verified against what this broker id must be."""
        err = b.not_ready()
        if err:
            raise err
        acct = await b.account()
        if acct["mode"] != EXPECTED_MODE.get(b.id):
            raise OrderError("mode_mismatch", f"{b.id} REPORTED A {acct['mode'].upper()} ACCOUNT: ORDERS REFUSED")
        return acct

    # --- the ledger as the blotter's history ---
    async def ledger_view(self, limit: int = 100) -> dict:
        """The order events of the hash-chained ledger, newest first, with the result of walking the whole chain."""
        rows = [e for e in await self.ledger.audit.entries(500) if e["kind"] == "order"][: max(1, min(limit, 200))]
        view = [{"seq": e["seq"], "at": e["at"], "event": e["manifest"].get("event"), "broker": e["manifest"].get("broker"), "mode": e["manifest"].get("mode"),
                 "ref": e["ref"], "order": (e["meta"].get("order") or {}), "reason": e["meta"].get("reason"), "status": e["meta"].get("status")} for e in rows]
        return {"entries": view, "verify": await self.ledger.audit.verify()}

    # --- status ---
    async def status(self) -> dict:
        kill = await self.store.kill()
        return {"kill": {"on": bool(kill.get("on")), "at": kill.get("at")}, "live_enabled": await self.store.live_enabled(),
                "mandate": (await self.store.mandate()).public(), "trades_today": await self.store.trades_today(),
                "brokers": [self._broker_row(b) for b in self.brokers.values()]}

    @staticmethod
    def _broker_row(b: Broker) -> dict:
        err = b.not_ready()
        return {"id": b.id, "label": b.label, "slot_mode": EXPECTED_MODE.get(b.id), "ready": err is None,
                "message": str(err) if err else None, "kind": err.kind if err else None, "note": b.note}

    async def blotter(self, broker_id: str) -> dict:
        """Account, open orders, today's fills and positions. A part that fails is named in `errors`; the others still show."""
        b = self.broker(broker_id)
        acct = await self._ready_account(b)
        parts = await asyncio.gather(b.open_orders(), b.fills_today(), b.positions(), return_exceptions=True)
        out: dict = {"broker": b.id, "account": acct, "as_of": time.time(), "errors": {}}
        for name, got in zip(("open_orders", "fills", "positions"), parts, strict=True):
            if isinstance(got, OrderError):
                out["errors"][name] = str(got)
                out[name] = None
            elif isinstance(got, BaseException):
                out["errors"][name] = f"{b.label.upper()} {name.upper()} FAILED ({type(got).__name__})"
                out[name] = None
            else:
                out[name] = got
        return out

    # --- the gate shared by preview and submit ---
    async def _gate(self, order: Order, replace: str | None) -> dict:
        kill = await self.store.kill()
        if kill.get("on"):
            raise OrderError("kill_switch", "KILL SWITCH IS ON: NO NEW ORDERS UNTIL YOU RELEASE IT IN ORD (U)")
        b = self.broker(order.broker)
        acct = await self._ready_account(b)
        mode = acct["mode"]
        if mode == "live" and not await self.store.live_enabled():
            raise OrderError("live_off", "LIVE ORDERS ARE OFF. SWITCH THEM ON IN ORD (L) BY TYPING THE PHRASE (REAL MONEY)")
        if acct.get("trading_blocked"):
            raise OrderError("broker_rejected", f"{b.label.upper()} SAYS TRADING IS BLOCKED FOR THIS ACCOUNT")
        if replace is not None:
            current = next((o for o in await b.open_orders() if o["id"] == replace), None)
            if current is None:
                raise OrderError("not_found", "THE ORDER TO REPLACE IS NOT OPEN")
            if current["symbol"] != order.symbol or current["side"] != order.side:
                raise OrderError("bad_request", "A REPLACE CANNOT CHANGE THE SYMBOL OR THE SIDE: CANCEL AND ENTER A NEW ORDER")
        price = order.ref_price()
        price_note = "ORDER PRICE" if price is not None else None
        if price is None:
            price, price_note = await self.price_fn(order.symbol)
        try:
            positions = await b.positions()
            gross = sum(abs(p["market_value"]) for p in positions if p.get("market_value") is not None)
            gross_ok = all(p.get("market_value") is not None for p in positions)
            held = sum(p["qty"] for p in positions if p["symbol"] == order.symbol)
        except OrderError:
            gross, gross_ok, held = None, False, None
        m = await self.store.mandate()
        check = mandate_mod.check(order, m, price, gross if gross_ok else None, held, await self.store.trades_today())
        fp = fingerprint(order, mode, acct["id"] + (f"|replace:{replace}" if replace else ""))
        return {"broker": b, "account": acct, "mode": mode, "check": check, "price": price, "price_note": price_note, "fp": fp,
                "mandate": m.public(), "kill": False}

    @staticmethod
    def _facts(order: Order, ctx: dict | None = None, **extra) -> dict:
        d = {"order": order.public(), **extra}
        if ctx:
            d.update(acct_tail=ctx["account"]["id"][-4:], price=ctx["price"], mandate_ok=ctx["check"]["ok"])
        return d

    async def preview(self, body, replace: str | None = None) -> dict:
        """Everything the confirm step shows: the order, mode, account, the mandate check, and (only if all of it passes) a one-time token."""
        order = Order.from_body(body)
        try:
            ctx = await self._gate(order, replace)
        except OrderError as e:
            await self.ledger.event("refused", order.broker, EXPECTED_MODE.get(order.broker, "-"), **self._facts(order), reason=str(e), kind=e.kind, step="preview")
            raise
        out = {"order": order.public(), "line": order.line(), "replace": replace, "broker": order.broker, "mode": ctx["mode"], "account": ctx["account"],
               "price": ctx["price"], "price_note": ctx["price_note"], "check": ctx["check"], "mandate": ctx["mandate"],
               "note": ctx["broker"].note or None, "token": None, "token_ttl_s": None}
        if ctx["check"]["ok"]:
            out["token"], out["token_ttl_s"] = self.tokens.issue(ctx["fp"])
            await self.ledger.event("confirm_issued", order.broker, ctx["mode"], account=ctx["account"]["id"], **self._facts(order, ctx), replace=replace)
        else:
            await self.ledger.event("refused", order.broker, ctx["mode"], account=ctx["account"]["id"], **self._facts(order, ctx), step="mandate",
                                    reason="; ".join(c["detail"] for c in ctx["check"]["checks"] if not c["ok"]), kind="mandate")
        return out

    async def submit(self, body, token, replace: str | None = None) -> dict:
        order = Order.from_body(body)
        async with self.lock:
            try:
                ctx = await self._gate(order, replace)
                if not ctx["check"]["ok"]:
                    raise OrderError("mandate", "MANDATE REFUSES THIS ORDER: " + "; ".join(c["detail"] for c in ctx["check"]["checks"] if not c["ok"]),
                                     {"check": ctx["check"]})
                self.tokens.consume(token, ctx["fp"])
                if (await self.store.kill()).get("on"):  # read again right before sending
                    raise OrderError("kill_switch", "KILL SWITCH IS ON: NO NEW ORDERS UNTIL YOU RELEASE IT IN ORD (U)")
            except OrderError as e:
                await self.ledger.event("refused", order.broker, EXPECTED_MODE.get(order.broker, "-"), **self._facts(order), reason=str(e), kind=e.kind, step="submit")
                raise
            b, mode, acct = ctx["broker"], ctx["mode"], ctx["account"]["id"]
            client_id = "OT" + uuid.uuid4().hex[:14]
            # Written first: if the process dies during the call, the ledger still shows an order may be at the broker.
            await self.ledger.event("submitted", b.id, mode, client_id, acct, **self._facts(order, ctx), replace=replace)
            try:
                res = await (b.replace(replace, order) if replace else b.submit(order, client_id))
            except OrderError as e:
                await self.ledger.event("failed", b.id, mode, client_id, acct, **self._facts(order, ctx), reason=str(e), kind=e.kind)
                # A refusal by the broker counts toward the daily cap like any sent order; "unavailable" may have reached it, so it counts too.
                if not replace:
                    await self.store.log_order(b.id, mode, client_id, None, order.symbol, order.side, order.qty, "FAILED" if e.kind == "broker_rejected" else "UNKNOWN")
                raise
            if not replace:
                await self.store.log_order(b.id, mode, client_id, res.get("id"), order.symbol, order.side, order.qty, res.get("status") or "NEW")
            await self.ledger.event("replace" if replace else "accepted", b.id, mode, client_id, acct, **self._facts(order, ctx), broker_order_id=res.get("id"),
                                    status=res.get("status"))
            return {"order": res, "client_id": client_id, "mode": mode, "broker": b.id}

    # --- cancel and kill ---
    async def cancel(self, broker_id: str, order_id: str) -> dict:
        b = self.broker(broker_id)
        acct = await self._ready_account(b)
        try:
            await b.cancel(order_id)
        except OrderError as e:
            await self.ledger.event("cancel_failed", b.id, acct["mode"], order_id, acct["id"], reason=str(e), kind=e.kind)
            raise
        await self.ledger.event("cancel", b.id, acct["mode"], order_id, acct["id"])
        return {"cancelled": order_id, "broker": b.id}

    async def kill(self) -> dict:
        """Block new orders first (persisted), void every confirm token, then cancel everything at every connected broker."""
        st = await self.store.set_kill(True)
        self.tokens.clear()
        await self.ledger.event("kill_on", at=st["at"])
        results: dict[str, dict] = {}

        async def one(b: Broker) -> None:
            if b.not_ready() is not None:
                results[b.id] = {"ok": None, "detail": "NOT CONNECTED: NOTHING TO CANCEL", "cancelled": 0, "failed": 0}
                return
            try:
                async with self.lock:  # an order that was already past the gate finishes first, then it is cancelled with the rest
                    rows = await b.cancel_all()
                ok = [r for r in rows if r["ok"]]
                results[b.id] = {"ok": len(ok) == len(rows), "detail": f"{len(ok)} OF {len(rows)} OPEN ORDERS CANCELLED", "cancelled": len(ok),
                                 "failed": len(rows) - len(ok)}
            except Exception as e:  # noqa: BLE001 - one broker failing must not stop the others
                results[b.id] = {"ok": False, "detail": redact(str(e))[:200] or type(e).__name__, "cancelled": 0, "failed": -1}
            await self.ledger.event("kill_cancel_all", b.id, EXPECTED_MODE.get(b.id, "-"), **results[b.id])

        await asyncio.gather(*(one(b) for b in self.brokers.values()))
        return {"kill": {"on": True, "at": st["at"]}, "brokers": results}

    async def unkill(self) -> dict:
        st = await self.store.set_kill(False)
        await self.ledger.event("kill_off", at=st["at"])
        return {"kill": {"on": False, "at": st["at"]}}

    # --- settings ---
    async def set_live(self, on: bool, phrase: str | None) -> dict:
        if on and phrase != LIVE_PHRASE:
            raise OrderError("bad_request", f"TO TURN LIVE ORDERS ON TYPE: {LIVE_PHRASE}")
        await self.store.set_live(on)
        if not on:
            self.tokens.clear()
        await self.ledger.event("live_on" if on else "live_off")
        return {"live_enabled": on}

    async def set_mandate(self, raw) -> dict:
        m = await self.store.set_mandate(raw)
        self.tokens.clear()  # a token was checked against the old mandate
        await self.ledger.event("mandate_changed", mandate=m.public())
        return m.public()

    # --- fills into a portfolio ---
    async def import_fills(self, broker_id: str, portfolio: str) -> dict:
        b = self.broker(broker_id)
        acct = await self._ready_account(b)
        done = await self.store.imported_ids(b.id)
        fills = [f for f in await b.fills_today() if f["fill_id"] not in done]
        if not fills:
            return {"added": 0, "portfolio": portfolio, "detail": "NO NEW FILLS TODAY"}
        lots = [{"symbol": f["symbol"], "qty": f["qty"] if f["side"] == "buy" else -f["qty"], "cost": f["price"], "currency": f["currency"],
                 "notes": f"{b.label} {acct['mode']} order {f['order_id']}"[:200], "source": FILL_SOURCE.get(b.id, "orders"), "synced_at": time.time()} for f in fills]
        try:
            res = await Portfolios(self.db).edit(portfolio, add=lots)
        except UserDataError as e:
            raise OrderError("bad_request", f"PORTFOLIO: {e}") from e
        await self.store.mark_imported(b.id, fills, res["name"])
        await self.ledger.event("import_fills", b.id, acct["mode"], account=acct["id"], portfolio=res["name"], fills=len(fills),
                                orders=sorted({str(f.get("order_id")) for f in fills}))
        return {"added": len(fills), "portfolio": res["name"], "detail": f"{len(fills)} FILLS ADDED AS LOTS TO {res['name']}"}
