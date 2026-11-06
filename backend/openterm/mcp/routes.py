"""HTTP transport for MCP: `POST /mcp` (Streamable HTTP, plain JSON response mode).

Two guards, both required by the MCP spec for local servers:
- loopback only: a request from another machine is refused (the tools read the user's own data);
- Origin check: a browser page on another site could try to reach 127.0.0.1 (DNS rebinding), so a request that carries
  an Origin header that is not localhost / 127.0.0.1 is refused. Non-browser clients send no Origin and pass.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .. import api as api_mod
from ..ai import tools as toolbox
from ..origin import origin_ok
from ..redact import redact
from . import server

router = APIRouter()

_origin_ok = origin_ok  # the one allowlist lives in openterm/origin.py (the whole app uses it, not just /mcp)


@router.get("/mcp")
async def mcp_get() -> Response:
    # We never push server-initiated messages, so there is no SSE stream to offer (spec: answer 405).
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if not api_mod.loopback(request):
        return JSONResponse({"error": "FORBIDDEN: MCP IS LOOPBACK ONLY"}, status_code=403)
    if not _origin_ok(request.headers.get("origin")):
        return JSONResponse({"error": "FORBIDDEN: ORIGIN NOT ALLOWED"}, status_code=403)
    try:
        message = json.loads(await request.body())
    except ValueError:
        return JSONResponse(server.error(None, -32700, "PARSE ERROR: BODY IS NOT JSON"), status_code=400)
    # Same construction as the AI agent: calls the app's own routes in-process.
    runner = toolbox.ToolRunner(request.app, client=(request.client.host, request.client.port), tools=[t.name for t in server.exposed_tools()])
    try:
        answer = await server.handle(message, runner)
    except Exception as e:  # noqa: BLE001 - a tool bug must come back as a JSON-RPC error, not a bare 500
        answer = server.error(message.get("id") if isinstance(message, dict) else None, -32603,
                              f"INTERNAL ERROR {type(e).__name__}: {redact(str(e))[:120]}")
    finally:
        await runner.aclose()
    if answer is None:  # notification: accepted, nothing to say
        return Response(status_code=202)
    return JSONResponse(answer)
