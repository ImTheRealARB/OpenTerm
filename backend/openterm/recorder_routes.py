"""Phase 24 recorder routes (`/api/recorder`): start / stop a local recording, list recordings, read or delete a stored session.

Starting, stopping and deleting change files on this computer, so they are loopback-only (`http_util.loopback`), like the key
and settings writes. Reading is open to the app's own panels. See `recorder.py` for what is recorded and where.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from .http_util import data_errors, error_response, loopback
from .recorder import RecorderError
from .responses import Orjson, OrjsonRoute

router = APIRouter(prefix="/api/recorder", route_class=OrjsonRoute)

# Our own error kinds -> HTTP status (RecorderError is not a DataError, so `http_util.STATUS` does not know it).
_STATUS = {"bad_request": 400, "not_found": 404, "conflict": 409, "forbidden": 403}


class SymbolBody(BaseModel):
    symbol: str = Field(..., max_length=40)


def _fail(e: RecorderError):
    return error_response(_STATUS.get(e.kind, 500), e.kind, str(e))


def _local_only(request: Request):
    """None when the request may change recordings, else the 403 answer."""
    if loopback(request):
        return None
    return error_response(403, "forbidden", "RECORDINGS CAN ONLY BE CHANGED FROM THIS MACHINE")


@router.get("")
async def listing(request: Request):
    return Orjson(await request.app.state.recorder.listing())


@router.post("/start")
@data_errors
async def start(request: Request, body: SymbolBody):
    if (denied := _local_only(request)) is not None:
        return denied
    try:
        return Orjson(await request.app.state.recorder.start(body.symbol))
    except RecorderError as e:
        return _fail(e)


@router.post("/stop")
async def stop(request: Request, body: SymbolBody):
    if (denied := _local_only(request)) is not None:
        return denied
    try:
        return Orjson(await request.app.state.recorder.stop(body.symbol))
    except RecorderError as e:
        return _fail(e)


# --- replay: the recorded session in the same shapes the live panels read (TAS / FOOT / DOM with `REC=<id>`) ---
@router.get("/tas")
async def replay_tas(request: Request, id: str = Query(..., max_length=60), limit: int = Query(200, ge=1, le=1000)):
    try:
        return Orjson(request.app.state.recorder.replay_tas(id, limit))
    except RecorderError as e:
        return _fail(e)


@router.get("/footprint")
async def replay_footprint(request: Request, id: str = Query(..., max_length=60), interval: str = Query("1m", max_length=4),
                           bars: int = Query(30, ge=1, le=120), step: float | None = Query(None, gt=0)):
    try:
        return Orjson(request.app.state.recorder.replay_footprint(id, interval, bars, step))
    except RecorderError as e:
        return _fail(e)


@router.get("/depth")
async def replay_depth(request: Request, id: str = Query(..., max_length=60), i: int = Query(-1, ge=-100000, le=100000)):
    try:
        return Orjson(request.app.state.recorder.replay_depth(id, i))
    except RecorderError as e:
        return _fail(e)


@router.get("/session/{sid:path}")
async def session(request: Request, sid: str):
    try:
        return Orjson(request.app.state.recorder.read_session(sid))
    except RecorderError as e:
        return _fail(e)


@router.delete("/session/{sid:path}")
async def delete(request: Request, sid: str):
    if (denied := _local_only(request)) is not None:
        return denied
    try:
        request.app.state.recorder.delete_session(sid)
    except RecorderError as e:
        return _fail(e)
    return Orjson({"deleted": sid})
