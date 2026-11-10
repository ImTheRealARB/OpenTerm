"""Pure JSON-RPC 2.0 dispatcher for the MCP server (no FastAPI in this file, so it is easy to test).

`handle(message, runner)` takes one decoded JSON-RPC message and returns the answer dict, or None for a
notification (a message without an `id`: the sender expects no reply).

Tools are the AI agent's registry (`ai.tools.REGISTRY`) minus the `doc_only` ones. They run through the same
`ToolRunner` the AI agent uses, so validation, shaping and size caps are identical.
"""

from __future__ import annotations

import json
from typing import Any

from .. import APP_NAME, __version__
from ..ai import tools as toolbox
from ..redact import redact

PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC error codes (fixed by the spec).
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# Compute jobs: they start work in a worker process, so a client must not treat them as pure reads.
NOT_READ_ONLY = {"backtest_run", "quant"}


# The user's own trade journal stays inside OpenTerm: it is not offered to outside MCP clients.
PRIVATE = {"journal"}


def exposed_tools() -> list[toolbox.Tool]:
    """The tools a client may see: everything in the agent registry except document-only helpers and private ones."""
    return [t for t in toolbox.REGISTRY.values() if not t.doc_only and t.name not in PRIVATE]


def tool_list() -> list[dict]:
    return [{
        "name": t.name,
        "description": t.description,
        "inputSchema": t.parameters,
        "annotations": {"readOnlyHint": t.name not in NOT_READ_ONLY, "destructiveHint": False},
    } for t in exposed_tools()]


def error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": redact(message)}}


def _result(id_: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


async def call_tool(runner: Any, name: str, args: dict) -> dict:
    """Runs one tool and shapes the MCP `tools/call` result. A failed tool is a result with isError, never a protocol error."""
    res = await runner.call(name, args)
    meta = {"source": res.source, "age_s": res.age_s, "stale": res.stale, "empty": res.empty}
    if not res.ok:
        text = redact(res.text)
        return {"content": [{"type": "text", "text": text}], "structuredContent": {**meta, "error": redact(res.error or text)}, "isError": True}
    # The text carries the provenance line first so a client that ignores structuredContent still shows where data came from.
    head = f"[source={res.source} age_s={res.age_s} stale={res.stale} empty={res.empty}]"
    structured: dict = dict(meta)
    try:
        structured["data"] = json.loads(res.text)
    except ValueError:  # truncated text is not valid JSON: leave the data in the text only
        pass
    return {"content": [{"type": "text", "text": f"{head}\n{res.text}"}], "structuredContent": structured, "isError": False}


async def handle(message: Any, runner: Any) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        # An array (batch) lands here too: the 2025-06-18 spec dropped batches.
        return error(None, INVALID_REQUEST, "INVALID REQUEST: SEND ONE JSON-RPC 2.0 OBJECT")
    method = message.get("method")
    if not isinstance(method, str):
        return error(message.get("id"), INVALID_REQUEST, "INVALID REQUEST: method MUST BE A STRING")
    if "id" not in message:  # notification (for example notifications/initialized): no answer
        return None
    id_ = message["id"]
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return error(id_, INVALID_PARAMS, "params MUST BE AN OBJECT")

    if method == "initialize":
        # Older client versions are accepted by answering with ours; the client then decides whether it can talk to us.
        return _result(id_, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": APP_NAME, "version": __version__},
        })
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": tool_list()})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if not isinstance(name, str) or name not in {t.name for t in exposed_tools()}:
            return error(id_, INVALID_PARAMS, f"UNKNOWN TOOL {str(name)[:60]}")
        if not isinstance(args, dict):
            return error(id_, INVALID_PARAMS, "arguments MUST BE AN OBJECT")
        return _result(id_, await call_tool(runner, name, args))
    return error(id_, METHOD_NOT_FOUND, f"METHOD NOT FOUND: {method[:60]}")
