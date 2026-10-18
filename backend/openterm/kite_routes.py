"""Kite Connect routes (Phase 15, READ-ONLY): login, callback, status, logout, symbol resolve and the instrument dump summary.

Nothing here reads or returns the access token, the secret, the public token or the enctoken, and nothing here sends anything to the
broker beyond the login exchange and market-data reads. The callback and the login redirect answer loopback clients only.
"""

from __future__ import annotations

import html
from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .api import error, loopback
from .kite import KITE_LOGIN
from .kite.client import KiteLoginFailed
from .kite.session import KEY_REQUIRED_MESSAGE
from .kite.symbols import to_kite
from .redact import redact
from .responses import Orjson
from .service import DataError

router = APIRouter(prefix="/api/kite")

PAGE = ("<!doctype html><meta charset=utf-8><title>OpenTerm KITE</title>"
        "<body style='background:#000;color:#ffb000;font:16px monospace;padding:2em'><h2>{head}</h2><p>{body}</p>")


def provider(request: Request):
    return request.app.state.kite


def page(head: str, body: str, status: int) -> HTMLResponse:
    return HTMLResponse(PAGE.format(head=html.escape(head), body=html.escape(body)), status_code=status)


def no_key() -> Response:
    return Orjson({"error": KEY_REQUIRED_MESSAGE, "kind": "key_required", "key": "KITE_API_KEY"}, status_code=400)


@router.get("/status")
async def status(request: Request):
    return provider(request).session.status()


@router.get("/login")
async def login(request: Request):
    if not loopback(request):
        return Orjson({"error": "KITE LOGIN CAN ONLY BE STARTED FROM THIS MACHINE", "kind": "forbidden"}, status_code=403)
    creds = provider(request).session.credentials()
    if creds is None:
        return no_key()
    return RedirectResponse(f"{KITE_LOGIN}?v=3&api_key={quote(creds[0], safe='')}", status_code=302)


@router.get("/callback")
async def callback(request: Request, request_token: str | None = None, status: str | None = None):
    if not loopback(request):
        return page("LOGIN FAILED", "THE KITE CALLBACK CAN ONLY BE OPENED FROM THIS MACHINE", 403)
    kite = provider(request)
    if status != "success" or not request_token or len(request_token) > 200:
        return page("LOGIN FAILED", f"KITE DID NOT SEND A REQUEST TOKEN (STATUS {status or 'MISSING'}). RUN KITE LOGIN AGAIN", 400)
    if not kite.session.has_key:
        return page("LOGIN FAILED", KEY_REQUIRED_MESSAGE, 400)
    try:
        data = await kite.client.exchange_token(request_token)
    except KiteLoginFailed as e:
        return page("LOGIN FAILED", redact(str(e)), 403)
    kite.session.login(data["access_token"], data.get("user_id"))
    kite.instruments.forget()
    return page("LOGGED IN", "KITE LOGIN OK. CLOSE THIS TAB AND RETURN TO OPENTERM", 200)


@router.post("/logout")
async def logout(request: Request):
    if not loopback(request):
        return Orjson({"error": "KITE LOGOUT CAN ONLY BE DONE FROM THIS MACHINE", "kind": "forbidden"}, status_code=403)
    provider(request).session.logout()
    return provider(request).session.status()


@router.get("/resolve")
async def resolve_symbol(request: Request, symbol: str):
    kite = provider(request)
    if not kite.session.has_key:
        return no_key()
    key = to_kite(symbol.strip().upper())
    if key is None:
        return Orjson({"error": "NOT A KITE SYMBOL: USE RELIANCE.NS, TCS.BO, ^NSEI, ^NSEBANK, <X>.NFO OR <X>.MCX", "kind": "bad_request"},
                      status_code=400)
    try:
        session = kite.session
        session.auth()  # a logged-out or expired session says so before any download
        inst = await kite.instruments.resolve(key)
    except DataError as e:
        return error(e)
    if inst is None:
        return Orjson({"error": f"{key} IS NOT IN THE KITE INSTRUMENT DUMP", "kind": "not_found"}, status_code=404)
    return {"symbol": symbol.strip().upper(), "kite": key, **inst}


@router.get("/instruments")
async def instruments(request: Request):
    """Refreshes the instrument dump from Kite (an authenticated call) and answers a summary, never the dump itself."""
    kite = provider(request)
    if not kite.session.has_key:
        return no_key()
    try:
        dump = await kite.instruments.get(force=True)
    except DataError as e:
        return error(e)
    return {"count": len(dump.by_key), "fetched_at": dump.fetched_at,
            "segments": dict(Counter(r["segment"] for r in dump.by_key.values())), "source": kite.source}
