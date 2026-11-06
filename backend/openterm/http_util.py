"""Small helpers every route module shares: the error answer, body parsing, the "who is asking" checks and the app getters.

They used to live at the top of `api.py`, so `world_routes`, `quant_routes`, `kite_routes`, `delivery/routes` and the AI
routes all imported the biggest file in the project just to build an error. This module is the stable bottom layer instead:
it imports no route module, so any of them can depend on it without an import cycle.

The error answer always has the same shape: `{"error": <text>, "kind": <word>}` plus an optional `detail`, and the HTTP status
comes from the kind (see `errkinds.py` for the words). `error`, `key_error`, `bt_error` and `error_response` differ only in
where the status comes from; all four build the body the same way.
"""

import functools
import inspect

import orjson
from fastapi import Request
from fastapi.responses import Response

from . import errkinds as K
from .errors import DataError
from .origin import LOOPBACK
from .redact import redact
from .responses import Orjson
from .service import DataService
from .userdata import UserData, UserDataError

# kind -> HTTP status for data and user-data errors (anything not listed is a 500)
STATUS = {K.BAD_REQUEST: 400, K.NOT_FOUND: 404, K.TOO_LARGE: 413, K.UNAVAILABLE: 503, K.KEY_REQUIRED: 424,
          K.LOGIN_REQUIRED: 401, K.LOGIN_EXPIRED: 403}  # Phase 15: Kite
# kind -> HTTP status for the key store (APIKEYS), strategy and spend-cap routes
KEY_STATUS = {"unknown_provider": 404, K.BAD_REQUEST: 400, "env_locked": 409, "forbidden": 403}


# --- app getters ---
def svc(request: Request) -> DataService:
    return request.app.state.service


def user(request: Request) -> UserData:
    return request.app.state.userdata


def jobs_of(request: Request):
    return request.app.state.jobs


def loopback(request: Request) -> bool:
    """True when the request comes from this machine (routes that change keys, settings or send messages require it)."""
    return bool(request.client) and request.client.host in LOOPBACK


# --- request bodies ---
MAX_BODY = 4_000_000  # the biggest honest body (a PORT import, a job's params) is well under this


def is_json_type(request: Request) -> bool:
    """True for `Content-Type: application/json` (with or without a charset). A cross-site page can send `text/plain`
    without the browser asking permission first; sending `application/json` makes the browser ask (CORS preflight), so
    insisting on it is a second wall behind the Origin check (audit D-2)."""
    return request.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json"


def require_json_type(request: Request) -> None:
    if not is_json_type(request):
        raise UserDataError(K.BAD_REQUEST, "CONTENT-TYPE MUST BE application/json")


async def json_object(request: Request) -> dict:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:  # refuse before buffering it
        raise UserDataError(K.TOO_LARGE, f"BODY OVER {MAX_BODY // 1_000_000} MB")
    require_json_type(request)
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise UserDataError(K.TOO_LARGE, f"BODY OVER {MAX_BODY // 1_000_000} MB")
    try:
        body = orjson.loads(raw)
    except orjson.JSONDecodeError:
        raise UserDataError(K.BAD_REQUEST, "BODY IS NOT JSON") from None
    if not isinstance(body, dict):
        raise UserDataError(K.BAD_REQUEST, "BODY MUST BE A JSON OBJECT")
    return body


async def json_body(request: Request, key: str):
    body = await json_object(request)
    if key not in body:
        raise UserDataError(K.BAD_REQUEST, f"BODY NEEDS {key}")
    return body[key]


# --- error answers ---
def error_response(status: int, kind: str, message: str) -> Response:
    """The bare error answer with a status the caller already chose. It does NOT redact `message`: callers that may hold
    upstream text (a provider's reason) pass it through `redact()` first, as the other builders below do."""
    return Orjson({"error": message, "kind": kind}, status_code=status)


def error(e: DataError | UserDataError) -> Response:
    """The answer for a DataError or UserDataError: status from `STATUS` (500 if the kind is unknown), text redacted."""
    body = {"error": redact(str(e)), "kind": e.kind}
    if e.kind == K.KEY_REQUIRED and getattr(e, "key", None):
        body["key"] = e.key
        body["detail"] = f"KEY REQUIRED: set {e.key} in APIKEYS"
    elif getattr(e, "detail", None):
        body["detail"] = redact(e.detail)
    return Orjson(body, status_code=STATUS.get(e.kind, 500))


def key_error(kind: str, message: str) -> Response:
    """The answer for the key store, spend cap and strategy-write routes: status from `KEY_STATUS` (500 if unknown), text redacted."""
    return error_response(KEY_STATUS.get(kind, 500), kind, redact(message))


def bt_error(e) -> Response:
    """The answer for a BtError (the backtester): like `error`, plus the `col` of a rule syntax error. An unknown kind is a
    400 here, not a 500, because every BT failure is the user's input until proven otherwise."""
    body = {"error": redact(str(e)), "kind": getattr(e, "kind", K.BAD_REQUEST)}
    if getattr(e, "detail", None):
        body["detail"] = redact(e.detail)
    if getattr(e, "col", None) is not None and e.col >= 0:
        body["col"] = e.col
    return Orjson(body, status_code=STATUS.get(body["kind"], 400))


def data_errors(fn):
    """Route decorator: a `DataError` raised anywhere in the route becomes `error(e)` instead of a 500.

    This replaces the `try: ... except DataError as e: return error(e)` that wrapped the whole body of dozens of routes.
    Put it under the route decorator (`@router.get(...)` first, `@data_errors` just above the `def`). `functools.wraps`
    keeps the route's real signature, so FastAPI still reads the same parameters and the OpenAPI schema does not change.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except DataError as e:
                return error(e)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except DataError as e:
                return error(e)
    return wrapper
