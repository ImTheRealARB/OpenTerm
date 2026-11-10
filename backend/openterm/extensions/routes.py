"""REST for extensions: list, enable, disable, and the read-only data routes an enabled extension added.

GET  /api/ext                     the list (name, version, author, licence, what it adds, ON / OFF / ERR) and the permissions notice
POST /api/ext/{name}/enable       the user switches an extension on (this machine only; the Origin guard covers browsers)
POST /api/ext/{name}/disable
GET  /api/ext/{name}[/{route}]    ?q=a b c  ->  {data: table | series payload, source: "ext:<name>", ...}; route defaults to main
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from .. import http_util
from ..responses import OrjsonRoute
from .manager import ExtensionManager, ExtError, split_args
from .manifest import NAME_RE, SHORT_RE

router = APIRouter(prefix="/api/ext", route_class=OrjsonRoute)

STATUS = {"bad_request": 400, "not_found": 404, "forbidden": 403, "extension_error": 502}


def _mgr(request: Request) -> ExtensionManager | None:
    return getattr(request.app.state, "ext", None)


def _err(e: ExtError):
    return http_util.error_response(STATUS.get(e.kind, 500), e.kind, str(e))


def _off():
    return http_util.error_response(503, "unavailable", "EXTENSIONS ARE NOT AVAILABLE")


@router.get("")
async def ext_list(request: Request):
    m = _mgr(request)
    if m is None:
        return _off()
    m.refresh()
    return m.summary()


@router.post("/{name}/enable")
async def ext_enable(name: str, request: Request):
    m = _mgr(request)
    if m is None:
        return _off()
    if not http_util.loopback(request):
        return http_util.error_response(403, "forbidden", "FORBIDDEN: ENABLING AN EXTENSION IS DONE FROM THIS MACHINE ONLY")
    if not NAME_RE.match(name):
        return http_util.error_response(400, "bad_request", "BAD EXTENSION NAME")
    try:
        return {"extension": m.enable(name), "notice": m.summary()["notice"]}
    except ExtError as e:
        return _err(e)


@router.post("/{name}/disable")
async def ext_disable(name: str, request: Request):
    m = _mgr(request)
    if m is None:
        return _off()
    if not http_util.loopback(request):
        return http_util.error_response(403, "forbidden", "FORBIDDEN: DISABLING AN EXTENSION IS DONE FROM THIS MACHINE ONLY")
    if not NAME_RE.match(name):
        return http_util.error_response(400, "bad_request", "BAD EXTENSION NAME")
    try:
        return {"extension": m.disable(name)}
    except ExtError as e:
        return _err(e)


async def _data(request: Request, name: str, route: str, q: str | None):
    m = _mgr(request)
    if m is None:
        return _off()
    if not NAME_RE.match(name) or not SHORT_RE.match(route):
        return http_util.error_response(400, "bad_request", "BAD EXTENSION OR ROUTE NAME")
    try:
        payload = await m.call_route(name, route, split_args(q))
    except ExtError as e:
        return _err(e)
    return {"data": payload, "source": f"ext:{name}", "as_of": time.time(), "age_s": 0.0, "stale": False, "fallback_from": []}


@router.get("/{name}")
async def ext_main(name: str, request: Request, q: str | None = None):
    return await _data(request, name, "main", q)


@router.get("/{name}/{route}")
async def ext_route(name: str, route: str, request: Request, q: str | None = None):
    return await _data(request, name, route, q)
