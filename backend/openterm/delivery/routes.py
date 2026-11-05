"""Routes for alert delivery: settings, log and a test button (Phase 17 B)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..api import error, json_object, loopback, user
from ..responses import Orjson
from ..userdata import UserDataError
from . import NEEDS, dispatch, pairing
from . import format as fmt
from . import log as dlog
from . import settings as dsettings

router = APIRouter(prefix="/api/delivery")


def _forbidden() -> Orjson:
    return Orjson({"error": "DELIVERY SETTINGS CAN ONLY BE CHANGED FROM THIS MACHINE", "kind": "forbidden"},
                  status_code=403)


def _status(request: Request, cfg: dict) -> dict:
    """Per push channel: off | ready | the KEY REQUIRED text, so the panel can say why a channel is quiet."""
    out = {}
    for ch, (key_name, label, _needed) in NEEDS.items():
        if not cfg["channels"].get(ch):
            out[ch] = "off"
        elif request.app.state.keys.get(key_name) is None:
            out[ch] = f"KEY REQUIRED: set {label} in APIKEYS"
        else:
            out[ch] = "ready"
    return out


@router.get("")
async def get_delivery(request: Request):
    cfg = await dsettings.get(user(request).db)
    return {"settings": dsettings.public(cfg), "status": _status(request, cfg)}


@router.put("")
async def put_delivery(request: Request):
    if not loopback(request):
        return _forbidden()
    try:
        body = await json_object(request)
        # The browser never sees the stored recipient, so it cannot send it back: an empty value means "keep what
        # is stored" (a non-empty one replaces it). To stop sending, switch the channel off instead.
        for field in ("email_to", "telegram_chat_id"):
            if isinstance(body.get(field), str) and not body[field].strip():
                del body[field]
        cfg = await dsettings.put(user(request).db, body)
    except UserDataError as e:
        return error(e)
    # Reschedule the daily brief from the new settings (the scheduler is absent in some test apps).
    sched = getattr(request.app.state, "scheduler", None)
    if sched is not None:
        from .. import scheduler

        scheduler.schedule_brief(sched, request.app, cfg["brief"])
    return {"settings": dsettings.public(cfg), "status": _status(request, cfg)}


@router.get("/log")
async def get_log(request: Request, limit: int = Query(100, ge=1, le=500)):
    return {"deliveries": await dlog.recent(user(request).db, limit)}


@router.post("/test")
async def post_test(request: Request):
    if not loopback(request):
        return _forbidden()
    try:
        channel = (await json_object(request)).get("channel")
        if channel not in dsettings.PUSH:
            raise UserDataError("bad_request", "channel MUST BE email, telegram OR webhook")
    except UserDataError as e:
        return error(e)
    subject, text = fmt.test_message()
    # A test ignores the on/off switch: the point is to check a channel before turning it on.
    return {"results": await dispatch(request.app, "test", "test", subject, text, {"kind": "test"}, [channel])}


# --- Telegram pairing (Phase 20): see delivery/pairing.py. Both routes change settings, so loopback only. ---------


@router.post("/telegram/pair/start")
async def pair_start(request: Request):
    if not loopback(request):
        return _forbidden()
    try:
        return await pairing.start(request.app)
    except UserDataError as e:
        return error(e)


@router.post("/telegram/pair/check")
async def pair_check(request: Request):
    if not loopback(request):
        return _forbidden()
    try:
        return await pairing.check(request.app)
    except UserDataError as e:
        return error(e)
