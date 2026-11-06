"""Browser-origin guard (audit D-2).

Why this exists: any web page open in the user's browser can send a request to http://127.0.0.1:8000. Such a request
arrives from a loopback address, so the "this machine only" checks pass. A cross-site POST with a `text/plain` body
is a "simple request": the browser sends it WITHOUT asking permission first (no CORS preflight), so the server would
run it (a backtest, a paid AI call, an alert test) before the browser ever hides the answer. WebSockets are not
covered by CORS at all.

The one thing a page cannot fake is the `Origin` header: the browser fills it in. So:
- every request that changes something (POST / PUT / PATCH / DELETE) must carry no Origin (a script, curl, the MCP
  stdio bridge) or an Origin that is this machine;
- a WebSocket must come from this machine AND carry no Origin or a local one.
The same allowlist is used by `POST /mcp` (it calls `origin_ok` too).
"""

from __future__ import annotations

import orjson

LOOPBACK = {"127.0.0.1", "::1", "localhost"}

ALLOWED_ORIGINS = ("http://localhost", "http://127.0.0.1", "http://[::1]")
CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def origin_ok(origin: str | None) -> bool:
    """True when there is no Origin (not a browser page) or it is this machine. 'null' (sandboxed pages, file://) is refused."""
    if origin is None:
        return True
    # "http://localhost" itself or followed by a port / path; "http://localhost.evil.com" must not pass.
    return any(origin == p or origin.startswith((p + ":", p + "/")) for p in ALLOWED_ORIGINS)


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", ()):
        if k == name:
            return v.decode("latin-1")
    return None


class OriginGuardMiddleware:
    """Pure ASGI (like perf.TimingMiddleware, no BaseHTTPMiddleware overhead): refuses a foreign Origin before the route runs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "http" and scope["method"] in CHANGING_METHODS:
            if not origin_ok(_header(scope, b"origin")):
                return await self._refuse_http(send)
        elif kind == "websocket":
            client = scope.get("client")
            if not client or client[0] not in LOOPBACK or not origin_ok(_header(scope, b"origin")):
                # Answering the handshake with a close frame before accept() makes the server reply HTTP 403.
                await receive()
                return await send({"type": "websocket.close", "code": 1008})
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse_http(send) -> None:
        body = orjson.dumps({"error": "FORBIDDEN: ORIGIN NOT ALLOWED", "kind": "forbidden"})
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
