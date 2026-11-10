"""Pin one data source for one request (`?source=nasdaq`, command `SRC=NASDAQ`).

The pin lives in a context variable for the length of a request, so every layer below the route (data service, research, derivs,
rates, world) sees it without a new argument. The router reads it: a pinned source is the ONLY source asked, and when it cannot
answer the user gets an error that names it (never a quiet fallback). The cache key carries it (`cachekeys.scoped`).

Imports nothing from the app, so any module can use it.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from urllib.parse import parse_qs

import orjson

PIN: ContextVar[str | None] = ContextVar("openterm_source_pin", default=None)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}\Z")


def clean(raw: str | None) -> str | None:
    """`" NASDAQ "` -> `"nasdaq"`; empty -> None; anything that cannot be a source name -> ValueError."""
    name = (raw or "").strip().lower()
    if not name:
        return None
    if not NAME_RE.match(name):
        raise ValueError(name[:40])
    return name


class SourcePinMiddleware:
    """Pure ASGI: reads `?source=` and sets `PIN` for the request. An unknown source is a 400 before the route runs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or b"source=" not in scope.get("query_string", b""):
            return await self.app(scope, receive, send)
        raw = parse_qs(scope["query_string"].decode("latin-1")).get("source", [""])[0]
        try:
            name = clean(raw)
        except ValueError:
            return await self._refuse(send, f"SRC={raw.strip().upper()[:40]}: NOT A SOURCE NAME")
        if name is None:
            return await self.app(scope, receive, send)
        service = getattr(getattr(scope.get("app"), "state", None), "service", None)
        known = service.router.providers if service is not None else {}
        if known and name not in known:
            return await self._refuse(send, f"SRC={name.upper()}: UNKNOWN SOURCE (SEE /api/sources)")
        token = PIN.set(name)
        try:
            await self.app(scope, receive, send)
        finally:
            PIN.reset(token)

    @staticmethod
    async def _refuse(send, message: str) -> None:
        body = orjson.dumps({"error": message, "kind": "bad_request"})
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
