"""Phase 17 section A: the MCP server (spec: docs/specs/PHASE_17.md). Nothing here touches the network:
the app runs in fixture mode and the stdio bridge talks to an httpx MockTransport."""

import io
import json
import re
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from openterm.ai import tools as toolbox
from openterm.mcp import __main__ as stdio
from openterm.mcp import server


def rpc(client, method, params=None, id_=1, **kw):
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, **kw)


def test_initialize_handshake(client):
    r = rpc(client, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18"
    assert res["serverInfo"]["name"] == "OpenTerm"
    assert "tools" in res["capabilities"]
    assert r.json()["id"] == 1


def test_tools_list_has_data_tools_and_no_doc_search(client):
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    by = {t["name"]: t for t in tools}
    assert "quote" in by and "history" in by
    assert "doc_search" not in by
    assert by["quote"]["inputSchema"]["required"] == ["symbols"]
    assert by["quote"]["annotations"] == {"readOnlyHint": True, "destructiveHint": False}
    for n in ("backtest_run", "quant"):
        assert by[n]["annotations"]["readOnlyHint"] is False and by[n]["annotations"]["destructiveHint"] is False


def test_tools_call_quote_returns_content_and_source(client):
    r = rpc(client, "tools/call", {"name": "quote", "arguments": {"symbols": "AAPL"}}).json()["result"]
    assert r["isError"] is False
    assert r["content"][0]["type"] == "text" and "AAPL" in r["content"][0]["text"]
    sc = r["structuredContent"]
    assert sc["source"] and sc["stale"] in (True, False) and "age_s" in sc and sc["empty"] is False
    assert "source=" in r["content"][0]["text"]


def test_tool_validation_error_is_a_tool_result(client):
    r = rpc(client, "tools/call", {"name": "quote", "arguments": {}}).json()
    assert "error" not in r
    assert r["result"]["isError"] is True
    assert "MISSING ARGUMENT symbols" in r["result"]["content"][0]["text"]


def test_unknown_tool_and_bad_params(client):
    assert rpc(client, "tools/call", {"name": "nope", "arguments": {}}).json()["error"]["code"] == -32602
    assert rpc(client, "tools/call", {"name": "doc_search", "arguments": {"query": "x"}}).json()["error"]["code"] == -32602
    assert rpc(client, "tools/call", {"name": "quote", "arguments": "x"}).json()["error"]["code"] == -32602


def test_unknown_method_and_batch(client):
    assert rpc(client, "resources/list").json()["error"]["code"] == -32601
    assert rpc(client, "ping").json()["result"] == {}
    r = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert r.json()["error"]["code"] == -32600


def test_notification_gets_202_and_get_is_405(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""
    assert client.get("/mcp").status_code == 405


def test_origin_guard(client):
    assert rpc(client, "ping", headers={"Origin": "https://evil.example"}).status_code == 403
    assert rpc(client, "ping", headers={"Origin": "http://localhost.evil.com"}).status_code == 403
    assert rpc(client, "ping", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert rpc(client, "ping", headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200


def test_non_loopback_refused(client):
    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert rpc(other, "ping").status_code == 403


# --- no order surface -------------------------------------------------------------------------------------------------------------------
FORBIDDEN = re.compile(r"\b(orders?|gtt|margins?|holdings?|kite)\b", re.IGNORECASE)


def test_no_order_surface():
    for t in server.exposed_tools():
        assert not FORBIDDEN.search(t.name + " " + t.description + " " + t.path), t.name
    pkg = Path(server.__file__).parent
    for f in pkg.glob("*.py"):
        assert not FORBIDDEN.search(f.read_text(encoding="utf-8")), f.name


def test_exposed_tools_are_the_agent_registry_minus_doc_only():
    assert {t.name for t in server.exposed_tools()} == {n for n, t in toolbox.REGISTRY.items() if not t.doc_only}


# --- stdio bridge -----------------------------------------------------------------------------------------------------------------------
def test_stdio_bridge_forwards_lines_and_skips_notifications():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((str(request.url), body["method"]))
        if "id" not in body:
            return httpx.Response(202)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    lines = ['{"jsonrpc":"2.0","id":7,"method":"ping"}', "", '{"jsonrpc":"2.0","method":"notifications/initialized"}']
    out = io.StringIO()
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        stdio.bridge(lines, out, c, "http://127.0.0.1:8000")
    assert seen == [("http://127.0.0.1:8000/mcp", "ping"), ("http://127.0.0.1:8000/mcp", "notifications/initialized")]
    answers = [json.loads(x) for x in out.getvalue().splitlines()]
    assert answers == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


def test_stdio_bridge_reports_openterm_not_running():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    out = io.StringIO()
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        stdio.bridge(['{"jsonrpc":"2.0","id":3,"method":"tools/list"}'], out, c, "http://127.0.0.1:8000")
    err = json.loads(out.getvalue())
    assert err["id"] == 3 and "OPENTERM IS NOT RUNNING AT http://127.0.0.1:8000" in err["error"]["message"]
