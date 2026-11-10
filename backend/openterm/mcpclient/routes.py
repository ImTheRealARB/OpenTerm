"""Routes for MCP client mode (third-party servers): `/api/mcpc/...`. Loopback only: enabling a server lets OpenTerm start a program on this machine.

GET  /servers                 every server (file entries plus the presets), off until enabled; no env or header values
POST /servers/{name}/enable   turns it on (a preset gets its read-only allow-list) and returns the third-party notice
POST /servers/{name}/disable  turns it off and stops it
POST /servers/{name}/allow    {tools: [...]} replaces the per-tool allow-list
GET  /servers/{name}/tools    lists the server's tools (starts it); each says whether it is allowed or refused
POST /servers/{name}/call     {tool, arguments} one manual call; the result is wrapped as third-party data; recorded in the audit ledger
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request, Response

from .. import http_util
from ..ai.audit import audit_of, canonical, sha
from ..redact import redact
from ..responses import OrjsonRoute
from .client import McpError
from .external import ConfigError, manager_of

log = logging.getLogger("openterm.mcpclient.routes")
router = APIRouter(prefix="/api/mcpc", route_class=OrjsonRoute)


def _guard(request: Request) -> Response | None:
    if not http_util.loopback(request):
        return http_util.error_response(403, "forbidden", "THIRD-PARTY MCP SERVERS CAN ONLY BE MANAGED FROM THIS MACHINE")
    if request.method != "GET" and not http_util.is_json_type(request):
        return http_util.error_response(400, "bad_request", "CONTENT-TYPE MUST BE application/json")
    return None


async def _body(request: Request) -> dict:
    try:
        return await http_util.json_object(request)
    except Exception:  # noqa: BLE001 - UserDataError carries the text
        return {}


def _fail(e: Exception) -> Response:
    if isinstance(e, ConfigError):
        return http_util.error_response(400, "bad_request", redact(str(e)))
    return http_util.error_response(502, "mcp", redact(str(e)[:300]))


@router.get("/servers")
async def servers(request: Request):
    if bad := _guard(request):
        return bad
    return manager_of(request.app).status()


@router.post("/servers/{name}/enable")
async def enable(name: str, request: Request):
    if bad := _guard(request):
        return bad
    try:
        return manager_of(request.app).enable(name)
    except ConfigError as e:
        return _fail(e)


@router.post("/servers/{name}/disable")
async def disable(name: str, request: Request):
    if bad := _guard(request):
        return bad
    try:
        return await manager_of(request.app).disable(name)
    except ConfigError as e:
        return _fail(e)


@router.post("/servers/{name}/allow")
async def allow(name: str, request: Request):
    if bad := _guard(request):
        return bad
    tools = (await _body(request)).get("tools")
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        return http_util.error_response(400, "bad_request", "tools MUST BE A LIST OF TOOL NAMES")
    try:
        return manager_of(request.app).set_allow(name, tools)
    except ConfigError as e:
        return _fail(e)


@router.get("/servers/{name}/tools")
async def tools(name: str, request: Request):
    if bad := _guard(request):
        return bad
    mgr = manager_of(request.app)
    try:
        listed = await mgr.list_tools(name, fresh=True)
        _spec, raw = mgr.spec(name)
    except (ConfigError, McpError) as e:
        return _fail(e)
    allowed = {str(t) for t in raw.get("allow") or []}
    rows = [{"name": t.name, "description": t.description[:200], "allowed": t.name in allowed, "refused": mgr.refusal(t)} for t in listed]
    return {"server": name, "tools": rows, "note": "THIRD-PARTY TOOLS. ONLY ALLOWED ONES REACH THE AI AS <server>.<tool>"}


@router.post("/servers/{name}/call")
async def call(name: str, request: Request):
    if bad := _guard(request):
        return bad
    body = await _body(request)
    tool, args = body.get("tool"), body.get("arguments", {})
    if not isinstance(tool, str) or not isinstance(args, dict):
        return http_util.error_response(400, "bad_request", "SEND {tool: string, arguments: object}")
    mgr = manager_of(request.app)
    t0 = time.time()
    try:
        ok, text = await mgr.call(name, tool, args)
    except (ConfigError, McpError) as e:
        await _record(request, name, tool, args, False)
        return _fail(e)
    await _record(request, name, tool, args, ok)
    return {"server": name, "tool": tool, "ok": ok, "source": f"THIRD-PARTY MCP: {name}", "text": text, "elapsed_s": round(time.time() - t0, 2)}


async def _record(request: Request, server: str, tool: str, args: dict, ok: bool) -> None:
    """A manual call goes in the audit ledger too (hashes only)."""
    try:
        ledger = audit_of(request.app, http_util.user(request).db)
        meta = {"server": server, "tool": tool, "args_sha": sha(canonical(args)), "ok": ok}
        await ledger.append("mcp", f"{server}.{tool}"[:60], "", {"app": "OpenTerm", "external": {f"{server}.{tool}": ""}}, meta)
    except Exception:
        log.exception("mcp ledger append failed")
