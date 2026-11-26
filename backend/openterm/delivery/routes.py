"""Routes for alert delivery: settings, log and a test button (Phase 17 B)."""

from __future__ import annotations

import base64
import binascii
import re

from fastapi import APIRouter, Query, Request

from ..http_util import error, json_object, loopback, user
from ..responses import Orjson, OrjsonRoute
from ..userdata import UserDataError
from . import NEEDS, dispatch, pairing
from . import format as fmt
from . import log as dlog
from . import settings as dsettings

router = APIRouter(prefix="/api/delivery", route_class=OrjsonRoute)


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


# Phase 22 GRAB: a panel picture to the channels the user names (TG = telegram, EMAIL = email). Same pipeline as alerts:
# keys, fixture-mode skip, daily cap, delivery log and retry; the senders attach `extra["picture"]`.
PICTURE_CHANNELS = {"TG": "telegram", "TELEGRAM": "telegram", "EMAIL": "email", "MAIL": "email"}
PICTURE_MAX = 8 * 1024 * 1024  # bytes of PNG; a 9-panel 4K screen is well under this
_PICTURE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,120}\.png$")


def parse_picture(body: dict) -> tuple[list[str], str, bytes]:
    """Checks a picture request: known channels, a plain file name, base64 PNG under the size cap. Pure (tested)."""
    raw = body.get("channels")
    if not isinstance(raw, list) or not raw or not all(isinstance(c, str) and c.upper() in PICTURE_CHANNELS for c in raw):
        raise UserDataError("bad_request", "channels MUST BE A LIST OF TG / EMAIL")
    name = body.get("name")
    if not isinstance(name, str) or not _PICTURE_NAME.match(name):
        raise UserDataError("bad_request", "name MUST BE A PLAIN .png FILE NAME")
    try:
        png = base64.b64decode(body.get("png_base64") or "", validate=True)
    except (binascii.Error, ValueError, TypeError) as e:
        raise UserDataError("bad_request", "png_base64 IS NOT BASE64") from e
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UserDataError("bad_request", "NOT A PNG")
    if len(png) > PICTURE_MAX:
        raise UserDataError("too_large", f"PICTURE OVER {PICTURE_MAX // (1024 * 1024)} MB")
    return sorted({PICTURE_CHANNELS[c.upper()] for c in raw}), name, png


@router.post("/picture")
async def post_picture(request: Request):
    if not loopback(request):
        return _forbidden()
    try:
        channels, name, png = parse_picture(await json_object(request))
    except UserDataError as e:
        return error(e)
    subject = f"OpenTerm picture {name}"
    return {"results": await dispatch(request.app, "picture", name, subject, subject, {"picture": (name, png)}, channels)}


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
