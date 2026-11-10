"""Phase 18 step 2 routes: READ-ONLY broker sync into PORT (`SYNC` panel, `PORT SYNC KITE|IBKR`).

GET  /api/sync/status          last sync, counts, difference against the previous sync and the last error, per broker (no network)
POST /api/sync/kite            {portfolio?, positions?}  reads Kite holdings (and net positions) and replaces the KITE-sourced lots
POST /api/sync/ibkr            {portfolio?, account?}    reads the local Client Portal gateway and replaces the IBKR-sourced lots
GET  /api/sync/ibkr/check      is the gateway up and logged in (one GET to the loopback gateway)
GET/PUT /api/sync/ibkr/settings  {gateway_url}: loopback hosts only, anything else is refused with 400

Every route that reads a broker or changes anything answers loopback clients only. No route sends an order to any broker.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .brokers import sync as bs
from .brokers.ibkr import IbkrGateway
from .errors import DataError
from .http_util import error, json_object, loopback
from .portfolio import portfolio_name
from .responses import Orjson, OrjsonRoute
from .userdata import UserDataError

router = APIRouter(prefix="/api/sync", route_class=OrjsonRoute)


def store(request: Request) -> bs.BrokerSync:
    db = request.app.state.userdata.db
    s = getattr(request.app.state, "broker_sync", None)
    if s is None or s.db is not db:  # the app (and its database) is rebuilt on every start
        s = request.app.state.broker_sync = bs.BrokerSync(db)
    return s


def forbidden() -> Orjson:
    return Orjson({"error": "BROKER SYNC CAN ONLY BE RUN FROM THIS MACHINE", "kind": "forbidden"}, status_code=403)


def gateway_of(request: Request, url: str) -> IbkrGateway:
    """The gateway client. Tests replace `app.state.ibkr_http` with a client on a mock transport."""
    return IbkrGateway(url, getattr(request.app.state, "ibkr_http", None))


def target(body: dict, broker: str) -> str:
    raw = body.get("portfolio") or bs.DEFAULT_PORTFOLIO[broker]
    if not isinstance(raw, str):
        raise UserDataError("bad_request", "portfolio MUST BE A NAME")
    return portfolio_name(raw)


@router.get("/status")
async def status(request: Request):
    s = store(request)
    kite = request.app.state.kite
    out = {"kite": await s.status("kite"), "ibkr": await s.status("ibkr")}
    out["kite"]["login"] = kite.session.status() if kite.session is not None else None
    out["ibkr"]["gateway_url"] = await s.gateway_url()
    out["default_portfolio"] = bs.DEFAULT_PORTFOLIO
    return out


@router.post("/kite")
async def sync_kite(request: Request):
    if not loopback(request):
        return forbidden()
    s = store(request)
    try:
        body = await json_object(request)
        name = target(body, "kite")
    except (UserDataError, DataError) as e:
        return error(e)
    include = body.get("positions") is True
    try:
        lots, skipped, warnings, meta = await bs.fetch_kite(request.app.state.kite, include)
        rec = await s.apply("kite", name, lots, skipped=skipped, warnings=warnings, meta=meta, label="kite")
    except (DataError, UserDataError) as e:
        await s.fail("kite", name, e)
        return error(e)
    return rec


@router.post("/ibkr")
async def sync_ibkr(request: Request):
    if not loopback(request):
        return forbidden()
    s = store(request)
    try:
        body = await json_object(request)
        name = target(body, "ibkr")
        account = body.get("account")
        if account is not None and not isinstance(account, str):
            raise UserDataError("bad_request", "account MUST BE AN ACCOUNT ID")
    except (UserDataError, DataError) as e:
        return error(e)
    gw = gateway_of(request, await s.gateway_url())
    try:
        lots, skipped, warnings, meta = await bs.fetch_ibkr(gw, account.strip() if account else None)
        rec = await s.apply("ibkr", name, lots, skipped=skipped, warnings=warnings, meta=meta, label="ibkr")
    except (DataError, UserDataError) as e:
        await s.fail("ibkr", name, e)
        return error(e)
    finally:
        await gw.aclose()
    return rec


@router.get("/ibkr/check")
async def check_ibkr(request: Request):
    if not loopback(request):
        return forbidden()
    s = store(request)
    url = await s.gateway_url()
    gw = gateway_of(request, url)
    try:
        return {**await gw.check(), "gateway_url": url}
    except DataError as e:
        return error(e)
    finally:
        await gw.aclose()


@router.get("/ibkr/settings")
async def get_settings(request: Request):
    return {"gateway_url": await store(request).gateway_url()}


@router.put("/ibkr/settings")
async def put_settings(request: Request):
    if not loopback(request):
        return forbidden()
    try:
        body = await json_object(request)
        return {"gateway_url": await store(request).set_gateway_url(body.get("gateway_url"))}
    except (UserDataError, DataError) as e:
        return error(e)
