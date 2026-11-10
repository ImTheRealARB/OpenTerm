"""Remote mode's own routes: the login page, `POST /api/remote/login`, `POST /api/remote/logout`, `GET /api/remote/session`.
They exist (and answer 404) when remote mode is off, so the route table never changes shape."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from . import http_util, remote
from .responses import Orjson, OrjsonRoute
from .userdata import UserDataError

router = APIRouter(route_class=OrjsonRoute)

LOGIN_CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'"


def _auth(request: Request):
    return getattr(request.app.state, "remote", None) if remote.enabled() else None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _auth(request) is None:
        return Response(status_code=404)
    return HTMLResponse(remote.LOGIN_PAGE, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY", "Content-Security-Policy": LOGIN_CSP})


@router.post("/api/remote/login")
async def login(request: Request):
    auth = _auth(request)
    if auth is None:
        return Response(status_code=404)
    if (wait := auth.locked()) > 0:
        return Orjson({"error": f"TOO MANY FAILED LOGINS, TRY AGAIN IN {wait} S", "kind": "rate_limited"}, status_code=429, headers={"Retry-After": str(wait)})
    try:
        body = await http_util.json_object(request)
    except UserDataError as e:
        return http_util.error(e)
    sid = auth.login(body.get("token"))
    if sid is None:
        return Orjson({"error": "WRONG TOKEN", "kind": "login_required"}, status_code=401)
    return Orjson({"ok": True}, headers={"Set-Cookie": remote.set_cookie(sid), "Cache-Control": "no-store"})


@router.post("/api/remote/logout")
async def logout(request: Request):
    auth = _auth(request)
    if auth is None:
        return Response(status_code=404)
    auth.logout(remote.cookie_from(request.scope))
    return Orjson({"ok": True}, headers={"Set-Cookie": remote.set_cookie("", 0)})


@router.get("/api/remote/session")
async def session(request: Request):
    if _auth(request) is None:
        return Response(status_code=404)
    return {"remote": True, "authenticated": True}  # the middleware only lets a valid session reach this
