from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from . import logbuf
from .providers import keyed_status
from .responses import Orjson
from .service import DataError, DataService
from .symbols import resolve

router = APIRouter(prefix="/api")

STATUS = {"bad_request": 400, "not_found": 404, "unavailable": 503}


def svc(request: Request) -> DataService:
    return request.app.state.service


def error(e: DataError) -> Response:
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
    }


@router.get("/log")
async def log(after: int = 0):
    return {"records": logbuf.since(after)}
