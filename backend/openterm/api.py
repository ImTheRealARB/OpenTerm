import orjson
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from . import logbuf
from .providers import keyed_status
from .responses import Orjson
from .service import DataError, DataService
from .symbols import resolve
from .userdata import UserData, UserDataError

router = APIRouter(prefix="/api")

STATUS = {"bad_request": 400, "not_found": 404, "too_large": 413, "unavailable": 503}


def svc(request: Request) -> DataService:
    return request.app.state.service


def user(request: Request) -> UserData:
    return request.app.state.userdata


async def json_body(request: Request, key: str):
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        raise UserDataError("bad_request", "BODY IS NOT JSON") from None
    if not isinstance(body, dict) or key not in body:
        raise UserDataError("bad_request", f"BODY NEEDS {key}")
    return body[key]


def error(e: DataError | UserDataError) -> Response:
    return Orjson({"error": str(e), "kind": e.kind}, status_code=STATUS.get(e.kind, 500))


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


@router.get("/resolve")
async def resolve_symbol(symbol: str):
    return {"input": symbol, "symbol": resolve(symbol)}


@router.get("/sources")
async def sources(request: Request):
    s = svc(request)
    return {
        "providers": s.router.summary(),
        "keyed": keyed_status(request.app.state.settings),
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
