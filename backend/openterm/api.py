import asyncio

import orjson
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from . import keys as keystore
from . import logbuf
from .providers import keyed_status
from .redact import redact
from .responses import Orjson
from .service import DataError, DataService
from .symbols import resolve
from .userdata import UserData, UserDataError

router = APIRouter(prefix="/api")

STATUS = {"bad_request": 400, "not_found": 404, "too_large": 413, "unavailable": 503, "key_required": 424}


def svc(request: Request) -> DataService:
    return request.app.state.service


def user(request: Request) -> UserData:
    return request.app.state.userdata


async def json_object(request: Request) -> dict:
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        raise UserDataError("bad_request", "BODY IS NOT JSON") from None
    if not isinstance(body, dict):
        raise UserDataError("bad_request", "BODY MUST BE A JSON OBJECT")
    return body


async def json_body(request: Request, key: str):
    body = await json_object(request)
    if key not in body:
        raise UserDataError("bad_request", f"BODY NEEDS {key}")
    return body[key]


def error(e: DataError | UserDataError) -> Response:
    body = {"error": redact(str(e)), "kind": e.kind}
    if e.kind == "key_required" and getattr(e, "key", None):
        body["key"] = e.key
        body["detail"] = f"KEY REQUIRED: set {e.key} in APIKEYS"
    elif getattr(e, "detail", None):
        body["detail"] = redact(e.detail)
    return Orjson(body, status_code=STATUS.get(e.kind, 500))


@router.get("/quote")
async def quote(request: Request, symbols: str = Query(..., max_length=2000)):
    wanted = [s for s in (x.strip() for x in symbols.split(",")) if s][:200]
    if not wanted:
        return error(DataError("bad_request", "NO SYMBOLS"))
    return {"results": await svc(request).quotes(wanted)}


@router.get("/history")
async def history(request: Request, symbol: str, range: str | None = None, interval: str | None = None):
    try:
        return await svc(request).history(symbol, range, interval)
    except DataError as e:
        return error(e)


@router.get("/profile")
async def profile(request: Request, symbol: str):
    try:
        return await svc(request).profile(symbol)
    except DataError as e:
        return error(e)


@router.get("/search")
async def search(request: Request, q: str = Query(..., max_length=64)):
    try:
        return await svc(request).search(q)
    except DataError as e:
        return error(e)


@router.get("/news")
async def news(
    request: Request, symbol: str | None = Query(None, max_length=24), q: str | None = Query(None, max_length=100)
):
    try:
        return await svc(request).news(symbol, q)
    except DataError as e:
        return error(e)


@router.get("/movers")
async def movers(request: Request):
    try:
        return await svc(request).movers()
    except DataError as e:
        return error(e)


@router.get("/crypto")
async def crypto(request: Request, vs: str = Query("USD", max_length=5)):
    try:
        return await svc(request).crypto(vs)
    except DataError as e:
        return error(e)


@router.get("/resolve")
async def resolve_symbol(symbol: str):
    return {"input": symbol, "symbol": resolve(symbol)}


@router.get("/sources")
async def sources(request: Request):
    s = svc(request)
    return {
        "providers": [{**p, "last_error": redact(p["last_error"])} if p.get("last_error") else p
                      for p in s.router.summary()],
        "keyed": await asyncio.to_thread(keyed_status, request.app.state.settings, request.app.state.keys),
        "order": s.router.order,
        "cache": s.stats(),
        "fixtures": request.app.state.settings.openterm_fixtures,
        "synthetic": request.app.state.settings.openterm_synthetic,
        "stream": request.app.state.hub.stats(),
    }


@router.get("/log")
async def log(after: int = 0):
    return {"records": logbuf.since(after)}


@router.get("/layouts")
async def layouts(request: Request):
    return {"layouts": await user(request).layouts()}


@router.get("/layouts/{name}")
async def layout(request: Request, name: str):
    try:
        return await user(request).layout(name)
    except UserDataError as e:
        return error(e)


@router.put("/layouts/{name}")
async def save_layout(request: Request, name: str):
    try:
        return await user(request).save_layout(name, await json_body(request, "state"))
    except UserDataError as e:
        return error(e)


@router.delete("/layouts/{name}")
async def delete_layout(request: Request, name: str):
    try:
        return {"deleted": await user(request).delete_layout(name)}
    except UserDataError as e:
        return error(e)


@router.get("/cmdhistory")
async def cmd_history(request: Request, limit: int = Query(500, ge=1, le=10_000)):
    return {"items": await user(request).history(limit)}


@router.post("/cmdhistory")
async def push_history(request: Request):
    try:
        cmds = await json_body(request, "cmds")
        if not isinstance(cmds, list) or not all(isinstance(c, str) for c in cmds):
            raise UserDataError("bad_request", "cmds MUST BE A LIST OF STRINGS")
        return {"added": await user(request).push_history(cmds[:1000])}
    except UserDataError as e:
        return error(e)


@router.get("/watchlists")
async def watchlists(request: Request):
    return {"watchlists": await user(request).watchlists()}


@router.get("/watchlists/{name}")
async def watchlist(request: Request, name: str):
    try:
        return await user(request).watchlist(name)
    except UserDataError as e:
        return error(e)


@router.put("/watchlists/{name}")
async def save_watchlist(request: Request, name: str):
    try:
        return await user(request).save_watchlist(name, await json_body(request, "symbols"))
    except UserDataError as e:
        return error(e)


@router.patch("/watchlists/{name}")
async def edit_watchlist(request: Request, name: str):
    try:
        body = await json_object(request)
        return await user(request).edit_watchlist(name, body.get("add"), body.get("remove"))
    except UserDataError as e:
        return error(e)


@router.delete("/watchlists/{name}")
async def delete_watchlist(request: Request, name: str):
    try:
        return {"deleted": await user(request).delete_watchlist(name)}
    except UserDataError as e:
        return error(e)


# --- Phase 6: SEC fundamentals / filings / insiders, Yahoo holders ---
@router.get("/fa")
async def fa(request: Request, symbol: str = Query(..., max_length=24), period: str = Query("A", max_length=1)):
    try:
        return await svc(request).fundamentals(symbol, period)
    except DataError as e:
        return error(e)


# --- Phase 9: screener (EQS) and peers (COMP) ---
@router.get("/screener")
async def screener(request: Request):
    try:
        return await svc(request).screener()
    except DataError as e:
        return error(e)


# --- Phase 7: macro ---
@router.get("/fred")
async def fred(request: Request, id: str = Query(..., max_length=40), range: str | None = Query(None, max_length=4)):
    try:
        return await svc(request).fred_series(id, range)
    except DataError as e:
        return error(e)


@router.get("/filings")
async def filings(
    request: Request, symbol: str = Query(..., max_length=24), form: str | None = Query(None, max_length=20)
):
    try:
        return await svc(request).filings(symbol, form)
    except DataError as e:
        return error(e)


@router.get("/macro")
async def macro(request: Request, q: str | None = Query(None, max_length=80)):
    try:
        return await svc(request).macro(q)
    except DataError as e:
        return error(e)


@router.get("/insiders")
async def insiders(request: Request, symbol: str = Query(..., max_length=24)):
    try:
        return await svc(request).insiders(symbol)
    except DataError as e:
        return error(e)


@router.get("/rates")
async def rates(request: Request):
    try:
        return await svc(request).rates()
    except DataError as e:
        return error(e)


@router.get("/holders")
async def holders(request: Request, symbol: str = Query(..., max_length=24)):
    try:
        return await svc(request).holders(symbol)
    except DataError as e:
        return error(e)


@router.get("/earnings")
async def earnings(request: Request, date: str | None = Query(None, max_length=10)):
    try:
        return await svc(request).earnings(date)
    except DataError as e:
        return error(e)


@router.get("/eco")
async def eco(request: Request, start: str | None = Query(None, max_length=10), days: int = Query(14, ge=1, le=62)):
    try:
        return await svc(request).eco(start, days)
    except DataError as e:
        return error(e)


# --- Phase 8: portfolios and alerts -----------------------------------------------------------
def portfolios(request: Request):
    from .portfolio import Portfolios

    return Portfolios(user(request).db)


def alerts_store(request: Request):
    from .portfolio import Alerts

    return Alerts(user(request).db)


@router.get("/portfolios")
async def list_portfolios(request: Request):
    return {"portfolios": await portfolios(request).all()}


@router.get("/portfolios/{name}")
async def get_portfolio(request: Request, name: str):
    try:
        return await portfolios(request).get(name)
    except UserDataError as e:
        return error(e)


@router.put("/portfolios/{name}")
async def put_portfolio(request: Request, name: str):
    try:
        body = await json_object(request)
        if "positions" not in body:
            raise UserDataError("bad_request", "BODY NEEDS positions")
        return await portfolios(request).put(name, body["positions"], body.get("base"))
    except UserDataError as e:
        return error(e)


@router.patch("/portfolios/{name}")
async def edit_portfolio(request: Request, name: str):
    try:
        b = await json_object(request)
        return await portfolios(request).edit(name, b.get("add"), b.get("set"), b.get("remove"), b.get("base"))
    except UserDataError as e:
        return error(e)


@router.delete("/portfolios/{name}")
async def delete_portfolio(request: Request, name: str):
    try:
        return {"deleted": await portfolios(request).delete(name)}
    except UserDataError as e:
        return error(e)


@router.get("/alerts")
async def list_alerts(request: Request):
    return {"alerts": await alerts_store(request).all()}


@router.post("/alerts")
async def create_alert(request: Request):
    try:
        return await alerts_store(request).create(await json_object(request))
    except UserDataError as e:
        return error(e)


@router.delete("/alerts")
async def clear_alerts(request: Request, status: str = Query(...)):
    if status != "triggered":
        return error(UserDataError("bad_request", "ONLY status=triggered CAN BE CLEARED"))
    return {"deleted": await alerts_store(request).clear_triggered()}


@router.delete("/alerts/{alert_id}")
async def delete_alert(request: Request, alert_id: int):
    try:
        return {"deleted": await alerts_store(request).delete(alert_id)}
    except UserDataError as e:
        return error(e)


@router.post("/alerts/{alert_id}/trigger")
async def trigger_alert(request: Request, alert_id: int):
    try:
        body = await json_object(request)
        return await alerts_store(request).trigger(alert_id, body.get("price"), body.get("at"))
    except UserDataError as e:
        return error(e)


@router.post("/alerts/{alert_id}/rearm")
async def rearm_alert(request: Request, alert_id: int):
    try:
        return await alerts_store(request).rearm(alert_id)
    except UserDataError as e:
        return error(e)


@router.get("/peers")
async def peers(request: Request, symbol: str = Query(..., max_length=24)):
    try:
        return await svc(request).peers(symbol)
    except DataError as e:
        return error(e)


# --- Phase 10: settings ---
@router.get("/settings")
async def get_settings_doc(request: Request):
    from .settings_store import SettingsStore

    return await SettingsStore(user(request).db).get()


@router.put("/settings")
async def put_settings_doc(request: Request):
    from .settings_store import VERSION, SettingsStore

    try:
        body = await json_object(request)
        if "settings" not in body:
            raise UserDataError("bad_request", "BODY NEEDS settings")
        return await SettingsStore(user(request).db).put(body["settings"], body.get("version", VERSION))
    except UserDataError as e:
        return error(e)


# --- Phase 11: key store (APIKEYS). Values go in, never out. ---
KEY_STATUS = {"unknown_provider": 404, "bad_request": 400, "env_locked": 409, "forbidden": 403}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def key_error(kind: str, message: str) -> Response:
    return Orjson({"error": message, "kind": kind}, status_code=KEY_STATUS.get(kind, 500))


def key_row(st: dict) -> dict:
    spec = keystore.KEY_SPECS[st["name"]]
    return {**st, "fields": list(spec.fields), "purpose": spec.purpose, "phase": spec.phase, "signup": spec.signup}


def keys_of(request: Request) -> keystore.KeyStore:
    return request.app.state.keys


def loopback(request: Request) -> bool:
    return bool(request.client) and request.client.host in LOOPBACK


@router.get("/keys")
async def keys_list(request: Request):
    rows = await asyncio.to_thread(keys_of(request).statuses)
    return {"keys": [key_row(r) for r in rows], "spend": {"today": 0.0, "cap": 1.0}}


async def _test(request: Request, name: str) -> dict:
    st = await keystore.run_test(keys_of(request), name, request.app.state.keys_http,
                                 fixtures=request.app.state.settings.openterm_fixtures)
    request.app.state.on_key_change(name)
    return key_row(st)


@router.put("/keys/{name}")
async def keys_put(request: Request, name: str):
    if not loopback(request):
        return key_error("forbidden", "KEYS CAN ONLY BE CHANGED FROM THIS MACHINE")
    if name not in keystore.KEY_SPECS:
        return key_error("unknown_provider", f"UNKNOWN PROVIDER {name.upper()}")
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("fields"), dict):
        return key_error("bad_request", "BODY MUST BE {fields: {ENV_NAME: value}}")
    try:
        await asyncio.to_thread(keys_of(request).set, name, body["fields"])
    except keystore.KeyStoreError as e:
        return key_error(e.kind, str(e))
    return await _test(request, name)


@router.post("/keys/{name}/test")
async def keys_test(request: Request, name: str):
    if name not in keystore.KEY_SPECS:
        return key_error("unknown_provider", f"UNKNOWN PROVIDER {name.upper()}")
    return await _test(request, name)


@router.delete("/keys/{name}")
async def keys_delete(request: Request, name: str):
    if not loopback(request):
        return key_error("forbidden", "KEYS CAN ONLY BE CHANGED FROM THIS MACHINE")
    try:
        await asyncio.to_thread(keys_of(request).delete, name)
    except keystore.KeyStoreError as e:
        return key_error(e.kind, str(e))
    request.app.state.on_key_change(name)
    return key_row(await asyncio.to_thread(keys_of(request).status, name))
