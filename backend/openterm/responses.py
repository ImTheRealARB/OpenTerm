"""JSON responses. Every OpenTerm router uses `OrjsonRoute`, so a route can return a plain dict or list and still skip
FastAPI's jsonable_encoder (audit E-1)."""

import functools
import inspect
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import orjson
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel


def _default(o: Any) -> Any:
    """Types orjson does not know but jsonable_encoder did, so switching encoders changes no answer.

    Called only for those types; dicts, lists, numbers and strings stay on orjson's fast path. Anything else still raises.
    """
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json", by_alias=True)
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


class Orjson(Response):
    """orjson for untyped dict payloads (FastAPI's built-in ORJSONResponse is deprecated)."""

    media_type = "application/json"

    def render(self, content) -> bytes:
        return orjson.dumps(content, default=_default)


def _to_orjson(result: Any) -> Any:
    return Orjson(result) if isinstance(result, (dict, list)) else result


def _wrap(endpoint: Callable) -> Callable:
    """The endpoint, returning `Orjson(x)` where it returned a dict or list `x`.

    Why: with no response_model, FastAPI walks a returned dict with jsonable_encoder (pure Python, on the event loop:
    8 ms for a 10-year chart, 34 ms for the screener) before the response class sees it; a returned Response skips that.
    `functools.wraps` keeps the signature (FastAPI reads parameters through `__wrapped__`), and the wrapper is async
    exactly when the endpoint is, so FastAPI still runs sync endpoints in its thread pool.
    """
    if inspect.iscoroutinefunction(endpoint):
        @functools.wraps(endpoint)
        async def run_async(*args, **kwargs):
            return _to_orjson(await endpoint(*args, **kwargs))
        return run_async

    @functools.wraps(endpoint)
    def run_sync(*args, **kwargs):
        return _to_orjson(endpoint(*args, **kwargs))
    return run_sync


class OrjsonRoute(APIRoute):
    """Route class for every router: `APIRouter(..., route_class=OrjsonRoute)`. A new route cannot forget the rule."""

    def __init__(self, path: str, endpoint: Callable, **kwargs: Any) -> None:
        super().__init__(path, _wrap(endpoint), **kwargs)
