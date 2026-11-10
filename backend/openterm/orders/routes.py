"""Order routes, all under /api/orders and ALL loopback-only (account data and money). Not in the AI tool registry or the MCP server;
tests scan both for these paths.

No route takes a `mode`, `live` or `paper` field: the order body is parsed by `Order.from_body`, which refuses those words.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..http_util import json_object, loopback
from ..redact import redact
from ..responses import Orjson, OrjsonRoute
from ..userdata import UserDataError
from .errors import STATUS, OrderError

router = APIRouter(prefix="/api/orders", route_class=OrjsonRoute)


def service_of(request: Request):
    """Built on first use. A new database (tests reuse the app object) gets a new service."""
    from ..ai.audit import audit_of
    from ..http_util import svc, user
    from .brokers.alpaca import AlpacaTrading
    from .brokers.kite import KiteTrading
    from .ledger import OrderLedger
    from .service import OrderService

    app = request.app
    db = user(request).db
    cur = getattr(app.state, "orders", None)
    if cur is None or cur.db is not db:
        store, http, service = app.state.keys, app.state.keys_http, svc(request)

        async def price_of(symbol: str):
            """Last price from the quote service. A stale or missing quote gives None, which the mandate treats as a refusal."""
            try:
                env = (await service.quotes([symbol])).get(symbol) or {}
            except Exception:  # noqa: BLE001 - any quote failure is "no price"
                return None, "QUOTE FAILED"
            data = env.get("data") if isinstance(env, dict) else None
            price = data.get("price") if isinstance(data, dict) else None
            if not isinstance(price, int | float) or env.get("stale"):
                return None, "NO FRESH QUOTE"
            return float(price), f"{env.get('source') or 'quote'} {env.get('age_s', 0):g}s OLD"

        brokers = {b.id: b for b in (AlpacaTrading("paper", store, http), AlpacaTrading("live", store, http), KiteTrading(app.state.kite))}
        app.state.orders = OrderService(db, OrderLedger(audit_of(app, db)), brokers, price_of)
    return app.state.orders


def fail(e: OrderError) -> Orjson:
    body = {"error": redact(str(e)), "kind": e.kind}
    if e.detail:
        body["detail"] = e.detail
    if e.kind == "key_required":
        body["key"] = redact(str(e)).split("set ", 1)[-1].split(" in ")[0]
    return Orjson(body, status_code=STATUS.get(e.kind, 500))


def forbidden() -> Orjson:
    return Orjson({"error": "ORDERS CAN ONLY BE USED FROM THIS MACHINE", "kind": "forbidden"}, status_code=403)


async def body_of(request: Request) -> dict:
    try:
        return await json_object(request)
    except UserDataError as e:
        raise OrderError("bad_request", str(e)) from e


def guarded(fn):
    """Loopback check, OrderError -> error answer."""
    import functools

    @functools.wraps(fn)
    async def wrapper(request: Request, *a, **kw):
        if not loopback(request):
            return forbidden()
        try:
            return await fn(request, *a, **kw)
        except OrderError as e:
            return fail(e)

    return wrapper


@router.get("/status")
@guarded
async def status(request: Request):
    return await service_of(request).status()


@router.get("/blotter")
@guarded
async def blotter(request: Request, broker: str = ""):
    return await service_of(request).blotter(broker)


@router.get("/ledger")
@guarded
async def ledger(request: Request):
    return await service_of(request).ledger_view()


@router.post("/preview")
@guarded
async def preview(request: Request):
    body = await body_of(request)
    if set(body) - {"order", "replace"}:
        raise OrderError("bad_request", "BODY NEEDS order (AND OPTIONALLY replace)")
    return await service_of(request).preview(body.get("order"), body.get("replace"))


@router.post("/submit")
@guarded
async def submit(request: Request):
    body = await body_of(request)
    if set(body) - {"order", "token", "replace"}:
        raise OrderError("bad_request", "BODY NEEDS order, token (AND OPTIONALLY replace)")
    return await service_of(request).submit(body.get("order"), body.get("token"), body.get("replace"))


@router.post("/cancel")
@guarded
async def cancel(request: Request):
    body = await body_of(request)
    return await service_of(request).cancel(body.get("broker"), body.get("order_id"))


@router.post("/kill")
@guarded
async def kill(request: Request):
    return await service_of(request).kill()


@router.post("/unkill")
@guarded
async def unkill(request: Request):
    return await service_of(request).unkill()


@router.put("/mandate")
@guarded
async def put_mandate(request: Request):
    return await service_of(request).set_mandate(await body_of(request))


@router.put("/live")
@guarded
async def put_live(request: Request):
    body = await body_of(request)
    if not isinstance(body.get("on"), bool):
        raise OrderError("bad_request", "BODY NEEDS on (true OR false)")
    return await service_of(request).set_live(body["on"], body.get("phrase"))


@router.post("/import")
@guarded
async def import_fills(request: Request):
    body = await body_of(request)
    if not isinstance(body.get("portfolio"), str) or not body["portfolio"].strip():
        raise OrderError("bad_request", "BODY NEEDS portfolio (A NAME)")
    return await service_of(request).import_fills(body.get("broker"), body["portfolio"].strip())
