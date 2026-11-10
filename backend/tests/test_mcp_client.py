"""MCP client mode: the protocol client (stdio and Streamable HTTP), the config and presets, the AI integration and the order-tool refusal.

Everything runs against `tests/fake_mcp_server.py` (written for these tests) or a local ASGI app: no third-party MCP package is ever started and
nothing touches the network.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi import FastAPI, Request, Response

from openterm.ai import tools as toolbox
from openterm.mcp import client as mc
from openterm.mcp import external as ext
from tests import fake_mcp_server as fake

HERE = Path(__file__).parent
SCRIPT = str(HERE / "fake_mcp_server.py")


def stdio_spec(name="fake", **kw) -> mc.ServerSpec:
    return mc.ServerSpec(name, command=sys.executable, args=[SCRIPT], **kw)


def sse(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


@pytest.fixture(autouse=True)
def _clean_external():
    toolbox.EXTERNAL.clear()
    yield
    toolbox.EXTERNAL.clear()


# --- the protocol client over stdio -------------------------------------------------------------------------------------------------------
async def test_stdio_initialize_list_and_call_and_close_kills_the_process():
    c = mc.Client(stdio_spec())
    assert not c.running and c._proc is None  # lazy: nothing started yet
    tools = await c.list_tools()
    assert {"echo", "big", "get_market_status"} <= {t.name for t in tools}
    assert c.server_info["name"] == "fake"
    ok, text = await c.call("echo", {"text": "hi"})
    assert ok and text == "echo:hi"
    proc = c._proc
    await c.close()
    assert proc.returncode is not None and not c.running


async def test_tool_error_result_is_not_ok():
    c = mc.Client(stdio_spec())
    try:
        ok, text = await c.call("fail", {})
        assert ok is False and "something broke" in text
    finally:
        await c.close()


async def test_timeout_then_the_next_call_starts_a_fresh_server():
    c = mc.Client(stdio_spec(timeout_s=0.6))
    try:
        await c.list_tools()
        first = c._proc
        with pytest.raises(mc.McpError, match="TIMEOUT"):
            await c.call("slow", {"seconds": 5})
        assert first.returncode is not None  # the stuck server was killed
        ok, text = await c.call("echo", {"text": "again"})
        assert ok and text == "echo:again" and c._proc is not first
    finally:
        await c.close()


async def test_crash_is_an_error_and_the_server_restarts_on_the_next_call():
    c = mc.Client(stdio_spec())
    try:
        await c.list_tools()
        with pytest.raises(mc.McpError, match="EXITED"):
            await c.call("die", {})
        ok, text = await c.call("echo", {"text": "back"})
        assert ok and text == "echo:back"
    finally:
        await c.close()


async def test_oversized_result_is_cut_to_the_ai_cap_and_wrapped_result_too():
    c = mc.Client(stdio_spec())
    try:
        ok, text = await c.call("big", {})
    finally:
        await c.close()
    assert ok and len(text) <= 6000 and "CHARACTERS OMITTED" in text
    wrapped = mc.wrap_untrusted("fake", "big", "y" * 20000)
    assert len(wrapped) <= 6000 and wrapped.startswith("[THIRD-PARTY DATA") and wrapped.endswith(mc.END)


async def test_idle_server_is_stopped():
    c = mc.Client(stdio_spec(idle_s=0.3))
    try:
        await c.call("echo", {"text": "x"})
        proc = c._proc
        await asyncio.sleep(1.0)
        assert proc.returncode is not None and not c.running
        ok, _ = await c.call("echo", {"text": "y"})  # and it comes back on demand
        assert ok
    finally:
        await c.close()


async def test_child_does_not_inherit_openterm_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-should-never-reach-a-child")
    monkeypatch.setenv("OPENTERM_SECRET_THING", "nope")
    c = mc.Client(stdio_spec(env={"MCP_TEST_KEY": "its-own-secret-value"}))
    try:
        _, text = await c.call("probe_env", {})
    finally:
        await c.close()
    assert json.loads(text) == ["MCP_TEST_KEY"]


async def test_missing_command_says_what_to_install():
    c = mc.Client(mc.ServerSpec("n", command="definitely-not-installed-npx", args=[]))
    with pytest.raises(mc.McpError, match="COMMAND NOT FOUND"):
        await c.list_tools()
    c2 = mc.Client(mc.ServerSpec("n", command="npx-missing-for-test"))
    with pytest.raises(mc.McpError):
        await c2.list_tools()


def test_errors_and_results_are_redacted_with_the_servers_own_secrets():
    spec = stdio_spec(env={"SOME_KEY": "supersecretvalue-123"}, headers={"X-Thing": "headersecret-456"})
    assert spec.clean("failed with supersecretvalue-123 and headersecret-456") == "failed with *** and ***"


# --- Streamable HTTP ----------------------------------------------------------------------------------------------------------------------
def http_app(seen: list) -> FastAPI:
    app = FastAPI()

    @app.post("/mcp")
    async def mcp(request: Request):
        msg = json.loads(await request.body())
        seen.append((msg.get("method"), request.headers.get("mcp-session-id"), request.headers.get("authorization")))
        out = fake.handle(msg)
        if out is None:
            return Response(status_code=202)
        headers = {"Mcp-Session-Id": "sess-1"} if msg["method"] == "initialize" else {}
        if msg["method"] == "tools/call":  # answer calls as an event stream, everything else as plain JSON
            body = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}) + "\n\n" \
                   "event: message\ndata: " + json.dumps(out) + "\n\n"
            return Response(body, media_type="text/event-stream", headers=headers)
        return Response(json.dumps(out), media_type="application/json", headers=headers)

    @app.delete("/mcp")
    async def end(request: Request):
        seen.append(("DELETE", request.headers.get("mcp-session-id"), None))
        return Response(status_code=204)

    return app


async def test_streamable_http_json_and_event_stream_with_session_and_headers():
    seen: list = []
    c = mc.Client(mc.ServerSpec("web", url="http://fake.local/mcp", headers={"Authorization": "Bearer tok-abcdefgh"}),
                  transport=httpx.ASGITransport(app=http_app(seen)))
    tools = await c.list_tools()
    assert "echo" in {t.name for t in tools}
    ok, text = await c.call("echo", {"text": "over http"})
    assert ok and text == "echo:over http"
    await c.close()
    methods = [s[0] for s in seen]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert seen[1][1] == "sess-1" and seen[-1][:2] == ("DELETE", "sess-1")  # the session id is sent back, and the session is ended on close
    assert all(s[2] == "Bearer tok-abcdefgh" for s in seen[:-1])


async def test_http_error_status_is_an_error():
    app = FastAPI()

    @app.post("/mcp")
    async def mcp():
        return Response(status_code=500)

    c = mc.Client(mc.ServerSpec("web", url="http://fake.local/mcp"), transport=httpx.ASGITransport(app=app))
    with pytest.raises(mc.McpError, match="HTTP 500"):
        await c.list_tools()
    await c.close()


# --- order-tool refusal -------------------------------------------------------------------------------------------------------------------
NSE_TOOLS = ["get_equity_details", "get_equity_historical_data", "get_equity_option_chain", "get_index_option_chain", "get_market_status",
             "get_gainers_and_losers_by_index", "stock_quote", "stock_history", "index_option_chain", "market_status", "get_equity_trade_info",
             "get_orders", "get_order_book"]


@pytest.mark.parametrize("name", NSE_TOOLS)
def test_read_only_market_tools_are_not_order_like(name):
    assert not mc.order_like(name, "Get data for a symbol from the exchange website.")


@pytest.mark.parametrize("name", ["place_order", "placeOrder", "create-order", "submit_trade", "buy_stock", "sell", "gtt_create", "kite_login", "orders", "cancel_order", "execute_trade"])
def test_order_names_are_refused(name):
    assert mc.order_like(name)


@pytest.mark.parametrize("desc", ["Place a buy order on the exchange.", "Submit a market order for the user.", "Executes trades for the account.", "Buy or sell shares."])
def test_order_descriptions_are_refused(desc):
    assert mc.order_like("do_it", desc)


def test_no_openterm_own_tool_name_is_order_like():
    """The existing scan (tests/test_phase20_tools.py) forbids order words in OpenTerm's own names; the external classifier must agree with it."""
    assert not [n for n, t in toolbox.REGISTRY.items() if mc.order_like(n, t.description)]


# --- config, presets, manager -------------------------------------------------------------------------------------------------------------
def write_cfg(tmp_path, servers) -> ext.Manager:
    (tmp_path / "mcp_servers.yaml").write_text(yaml.safe_dump({"servers": servers}))
    return ext.Manager(tmp_path)


FAKE_ENTRY = {"command": sys.executable, "args": [SCRIPT], "enabled": True, "allow": ["echo", "inject", "get_market_status", "get_orders"]}


def test_every_server_and_both_nse_presets_are_off_by_default(tmp_path):
    m = ext.Manager(tmp_path)
    st = m.status()
    by = {s["name"]: s for s in st["servers"]}
    assert set(by) == {"stock-nse-india", "nse-mcp"}
    assert all(not s["enabled"] and not s["running"] for s in by.values())
    assert by["stock-nse-india"]["target"] == "npx -y stock-nse-india mcp" and by["nse-mcp"]["target"] == "uvx nse-mcp"
    assert not (tmp_path / "mcp_servers.yaml").exists()  # reading writes nothing
    with pytest.raises(ext.ConfigError, match="IS OFF"):
        m.client("nse-mcp")


async def test_nothing_is_offered_or_started_while_disabled(tmp_path):
    m = write_cfg(tmp_path, {"fake": {**FAKE_ENTRY, "enabled": False}})
    assert await m.prepare() == []
    assert toolbox.EXTERNAL == {} and not m.clients
    assert "fake__echo" not in json.dumps(toolbox.openai_tools())


def test_enabling_a_preset_gives_the_notice_and_a_read_only_allow_list(tmp_path):
    m = ext.Manager(tmp_path)
    r = m.enable("stock-nse-india")
    n = r["notice"]
    for word in ("THIRD-PARTY", "unofficial", "not affiliated", "ON THIS COMPUTER WITH YOUR PERMISSIONS", "Node.js"):
        assert word.lower() in n.lower()
    assert "get_equity_details" in r["allow"] and not any(mc.order_like(t) for t in r["allow"])
    saved = yaml.safe_load((tmp_path / "mcp_servers.yaml").read_text())["servers"]
    assert saved["stock-nse-india"]["enabled"] is True and "nse-mcp" not in saved  # the other preset stays out of the file
    assert "uv" in ext.PRESETS["nse-mcp"].notice
    assert oct((tmp_path / "mcp_servers.yaml").stat().st_mode & 0o777) == oct(0o600)
    for p in ext.PRESETS.values():
        assert not any(mc.order_like(t) for t in p.allow)


def test_bad_entries_are_reported_not_fatal(tmp_path):
    m = write_cfg(tmp_path, {"ok": FAKE_ENTRY, "Bad Name": FAKE_ENTRY, "both": {"command": "x", "url": "http://a"}, "neither": {"enabled": True}, "ftp": {"url": "ftp://x"}})
    st = m.status()
    assert {s["name"] for s in st["servers"]} >= {"ok"} and len(st["problems"]) == 4


def test_status_never_contains_env_or_header_values(tmp_path):
    m = write_cfg(tmp_path, {"web": {"url": "https://user:pw123456@host.example/mcp?key=abcdef123456", "headers": {"Authorization": "Bearer topsecret-789"},
                                     "env": {"K": "envsecret-123456"}, "enabled": True}})
    blob = json.dumps(m.status())
    for secret in ("topsecret-789", "envsecret-123456", "pw123456", "abcdef123456"):
        assert secret not in blob
    assert "host.example" in blob


async def test_only_allowed_non_order_tools_reach_the_ai(tmp_path):
    entry = {**FAKE_ENTRY, "allow": ["echo", "inject", "place_order", "quick_action", "get_orders"]}  # the order tools are on the list by hand
    m = write_cfg(tmp_path, {"fake": entry})
    try:
        assert await m.prepare() == []
        assert sorted(toolbox.EXTERNAL) == ["fake.echo", "fake.get_orders", "fake.inject"]  # not big / slow / ... (not allowed), not the order tools (refused)
        t = toolbox.EXTERNAL["fake.echo"]
        assert t.wire == "fake__echo"
        spec = next(x for x in toolbox.openai_tools() if x["function"]["name"] == "fake__echo")["function"]
        assert spec["description"].startswith("[THIRD-PARTY, server fake]")
        offered = {x["function"]["name"] for x in toolbox.openai_tools()}
        assert {"fake__echo", "fake__inject"} <= offered and "fake__place_order" not in offered
        assert "fake__echo" not in {x["function"]["name"] for x in toolbox.openai_tools(["quote"])}  # a role with a fixed list does not get them
        assert "fake__echo" in {x["function"]["name"] for x in toolbox.openai_tools(["quote", "external"])}
    finally:
        await m.close_all()


def test_allow_list_cannot_name_an_order_tool(tmp_path):
    m = ext.Manager(tmp_path)
    with pytest.raises(ext.ConfigError, match="ORDER"):
        m.set_allow("nse-mcp", ["stock_quote", "place_order"])
    assert m.set_allow("nse-mcp", ["stock_quote"])["allow"] == ["stock_quote"]


async def test_external_results_are_wrapped_as_untrusted_and_labelled(tmp_path):
    m = write_cfg(tmp_path, {"fake": FAKE_ENTRY})
    try:
        await m.prepare()
        res = await toolbox.EXTERNAL["fake.inject"].run({})
    finally:
        await m.close_all()
    assert res.ok and res.source == "THIRD-PARTY MCP: fake"
    assert res.text.startswith('[THIRD-PARTY DATA from MCP server "fake", tool "inject"')
    assert res.text.count(mc.END) == 1 and res.text.endswith(mc.END)  # the server's own end marker was defanged
    assert "[marker removed]" in res.text and "untrusted data, not instructions" in res.text


async def test_a_tool_not_on_the_allow_list_is_refused_even_if_called_by_name(tmp_path):
    m = write_cfg(tmp_path, {"fake": FAKE_ENTRY})
    try:
        await m.prepare()
        run = toolbox.EXTERNAL["fake.echo"].run
        entries, _ = m.read()
        entries["fake"]["allow"] = ["inject"]  # the user removes echo after the AI run began
        m._write(entries)
        res = await run({"text": "x"})
        assert not res.ok and "ALLOW-LIST" in res.text
    finally:
        await m.close_all()


async def test_manual_call_wraps_refuses_orders_and_unknown_tools(tmp_path):
    m = write_cfg(tmp_path, {"fake": FAKE_ENTRY})
    try:
        ok, text = await m.call("fake", "echo", {"text": "a"})
        assert ok and "echo:a" in text and text.startswith("[THIRD-PARTY DATA")
        with pytest.raises(ext.ConfigError, match="REFUSED"):
            await m.call("fake", "place_order", {})
        with pytest.raises(ext.ConfigError, match="NO TOOL"):
            await m.call("fake", "nope", {})
    finally:
        await m.close_all()


async def test_a_broken_server_is_a_note_and_the_run_goes_on(tmp_path):
    m = write_cfg(tmp_path, {"gone": {"command": "no-such-binary-xyz", "enabled": True, "allow": ["x"]}, "fake": FAKE_ENTRY})
    try:
        notes = await m.prepare()
        assert len(notes) == 1 and "gone" in notes[0] and "COMMAND NOT FOUND" in notes[0]
        assert "fake.echo" in toolbox.EXTERNAL
    finally:
        await m.close_all()


# --- through the app: routes, the agent loop, the ledger ---------------------------------------------------------------------------------
def cfg_for_app(client, servers):
    data_dir = Path(client.app.state.settings.openterm_db_path).parent
    (data_dir / "mcp_servers.yaml").write_text(yaml.safe_dump({"servers": servers}))


def test_routes_list_enable_allow_tools_call_and_non_loopback(client):
    from fastapi.testclient import TestClient

    st = client.get("/api/mcpc/servers").json()
    assert {s["name"] for s in st["servers"]} == {"stock-nse-india", "nse-mcp"} and not any(s["enabled"] for s in st["servers"])
    cfg_for_app(client, {"fake": {**FAKE_ENTRY, "enabled": False}})
    assert client.post("/api/mcpc/servers/fake/call", json={"tool": "echo", "arguments": {"text": "x"}}).status_code == 400  # off
    r = client.post("/api/mcpc/servers/fake/enable", json={})
    assert r.status_code == 200 and "THIRD-PARTY" in r.json()["notice"]
    tools = client.get("/api/mcpc/servers/fake/tools").json()["tools"]
    by = {t["name"]: t for t in tools}
    assert by["echo"]["allowed"] and not by["big"]["allowed"] and by["place_order"]["refused"] and by["quick_action"]["refused"]
    assert client.post("/api/mcpc/servers/fake/allow", json={"tools": ["place_order"]}).status_code == 400
    assert client.post("/api/mcpc/servers/fake/allow", json={"tools": ["echo", "big"]}).json()["allow"] == ["big", "echo"]
    r = client.post("/api/mcpc/servers/fake/call", json={"tool": "echo", "arguments": {"text": "ledger"}})
    assert r.status_code == 200 and r.json()["source"] == "THIRD-PARTY MCP: fake" and "echo:ledger" in r.json()["text"]
    assert client.post("/api/mcpc/servers/fake/call", json={"tool": "place_order", "arguments": {}}).status_code == 400
    entries = client.get("/api/ai/ledger").json()["entries"]
    assert entries[0]["kind"] == "mcp" and entries[0]["meta"]["server"] == "fake" and "echo:ledger" not in json.dumps(entries)
    assert client.get("/api/ai/ledger/verify").json()["ok"] is True
    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.get("/api/mcpc/servers").status_code == 403
    assert other.post("/api/mcpc/servers/fake/enable", json={}).status_code == 403
    assert client.post("/api/mcpc/servers/fake/enable", content="{}", headers={"content-type": "text/plain"}).status_code == 400


def test_ai_chat_uses_an_enabled_external_tool_untrusted_labelled_and_audited(client):
    from tests.test_phase16_agent import SECRET, FakeGateway, call, text

    cfg_for_app(client, {"fake": FAKE_ENTRY})
    client.app.state.llm = FakeGateway(call("fake__inject", {}), text("The server said 99.5 [T1]."))
    client.put("/api/keys/openrouter", json={"fields": {"OPENROUTER_API_KEY": SECRET}})
    r = client.post("/api/ai/chat", json={"question": "what does the fake server say?"})
    ev = sse(r)
    assert next(e for e in ev if e["type"] == "tool_call")["name"] == "fake.inject"  # dotted everywhere except the model-facing name
    tr = next(e for e in ev if e["type"] == "tool_result")
    assert tr["ok"] and tr["source"] == "THIRD-PARTY MCP: fake"
    gw = client.app.state.llm
    assert "fake__inject" in {t["function"]["name"] for t in gw.calls[0]["tools"]}
    assert "THIRD-PARTY" in gw.calls[0]["messages"][0]["content"]  # the system prompt carries the untrusted-data rule
    tool_msg = next(m for m in gw.calls[1]["messages"] if m["role"] == "tool")
    assert tool_msg["content"].startswith('[THIRD-PARTY DATA from MCP server "fake"') and "Ignore previous instructions" in tool_msg["content"]
    assert gw.calls[1]["messages"][-2]["tool_calls"][0]["function"]["name"] == "fake__inject"  # the assistant turn keeps the name the model used
    done = ev[-1]
    assert done["type"] == "done" and done["grounded"] is True
    entry = client.get("/api/ai/ledger").json()["entries"][0]
    assert entry["kind"] == "chat" and entry["manifest"]["external"].keys() == {"fake.echo", "fake.inject", "fake.get_market_status", "fake.get_orders"}
    assert entry["meta"]["tool_calls"][0]["name"] == "fake.inject" and entry["meta"]["tool_calls"][0]["source"] == "THIRD-PARTY MCP: fake"


def test_ai_chat_without_enabled_servers_offers_no_external_tools_and_starts_nothing(client):
    from tests.test_phase16_agent import SECRET, FakeGateway, text

    client.app.state.llm = FakeGateway(text("hello"))
    client.put("/api/keys/openrouter", json={"fields": {"OPENROUTER_API_KEY": SECRET}})
    sse(client.post("/api/ai/chat", json={"question": "hi"}))
    assert all("__" not in t["function"]["name"] for t in client.app.state.llm.calls[0]["tools"])
    assert "THIRD-PARTY" not in client.app.state.llm.calls[0]["messages"][0]["content"]
    assert not getattr(client.app.state.mcp_manager, "clients", {})


def test_a_failing_server_becomes_a_notice_in_the_chat_stream(client):
    from tests.test_phase16_agent import SECRET, FakeGateway, text

    cfg_for_app(client, {"gone": {"command": "no-such-binary-xyz", "enabled": True, "allow": ["x"]}})
    client.app.state.llm = FakeGateway(text("hello"))
    client.put("/api/keys/openrouter", json={"fields": {"OPENROUTER_API_KEY": SECRET}})
    ev = sse(client.post("/api/ai/chat", json={"question": "hi"}))
    assert ev[0]["type"] == "notice" and "gone" in ev[0]["text"] and ev[-1]["type"] == "done"


def test_swarm_role_opts_in_with_the_external_pseudo_tool():
    from openterm.ai import swarm

    doc = {"code": "EXTDESK", "title": "t", "agents": [{"id": "a", "role": "A", "tools": ["quote", "external"], "system_prompt": "x"}],
           "tasks": [{"id": "t1", "agent_id": "a", "prompt_template": "go"}]}
    p = swarm.parse_preset(doc, source="test")
    assert "external" in p.roles[0].tools


def test_stdio_command_comes_only_from_the_config_file_never_a_request_or_the_ai(client):
    """Request bodies can carry command/args/env/url fields and the AI can pass them as tool arguments: none of it reaches a spawn."""
    import inspect

    cfg_for_app(client, {"fake": {**FAKE_ENTRY, "enabled": False}})
    path = Path(client.app.state.settings.openterm_db_path).parent / "mcp_servers.yaml"
    evil = {"command": "/bin/sh", "args": ["-c", "touch /tmp/pwned"], "url": "http://127.0.0.1:1/", "env": {"A": "b"}}
    assert client.post("/api/mcpc/servers/fake/enable", json=evil).status_code == 200
    assert client.post("/api/mcpc/servers/fake/allow", json={"tools": ["echo"], **evil}).status_code == 200
    r = client.post("/api/mcpc/servers/fake/call", json={"tool": "echo", "arguments": {"text": "hi", **evil}, **evil})
    assert r.status_code == 200
    saved = yaml.safe_load(path.read_text())["servers"]["fake"]
    assert saved["command"] == FAKE_ENTRY["command"] and saved["args"] == FAKE_ENTRY["args"] and "url" not in saved and "pwned" not in path.read_text()
    assert client.post("/api/mcpc/servers/evil/enable", json=evil).status_code == 400  # not in the file: cannot be created through a route
    assert "evil" not in path.read_text()
    for fn in (ext.Manager.enable, ext.Manager.set_allow):  # (call's `args` are the tool's arguments, sent to the server, never a spawn)
        assert not {"command", "args", "env", "url"} & set(inspect.signature(fn).parameters)
