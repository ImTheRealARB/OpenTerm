"""Audit group 7 (extensions, MCP, remote): H-12 items 1, 3(skipped, see below), 4, 6, 7 and H-13.

Each test fails on the code as it was before the fix (see the commit message / report for the failing output).
"""

import asyncio
import os
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from openterm import remote
from openterm.ai import tools as toolbox
from openterm.mcpclient.client import order_like


async def _dummy_app(scope, receive, send):  # the ToolRunner never reaches the app for a `local` tool
    raise AssertionError("not called")


# --- H-12 item 1: a synchronous `local` tool must not freeze the event loop, and must time out -------------------------------------------
def _slow_tool(seconds: float) -> toolbox.Tool:
    def local(args: dict, ctx: dict) -> dict:
        time.sleep(seconds)  # a blocking call, like an extension doing a slow file read or a network call
        return {"done": True}

    return toolbox.Tool("ext.slow.tool", "slow", toolbox.obj({}), "local:ext.slow.tool", local=local, desk_only=True)


@pytest.mark.asyncio
async def test_a_blocking_local_tool_does_not_freeze_the_event_loop(monkeypatch):
    monkeypatch.setitem(toolbox.REGISTRY, "ext.slow.tool", _slow_tool(0.6))
    runner = toolbox.ToolRunner(_dummy_app, tools=["ext.slow.tool"])
    worst_gap = 0.0
    stop = False

    async def ticker():
        nonlocal worst_gap
        last = time.monotonic()
        while not stop:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            worst_gap = max(worst_gap, now - last)
            last = now

    t = asyncio.create_task(ticker())
    await asyncio.sleep(0.1)  # let the ticker start ticking before the tool runs
    res = await runner.call("ext.slow.tool", {})
    stop = True
    await t
    await runner.aclose()
    assert res.ok
    assert worst_gap < 0.3, f"the loop was blocked for {worst_gap:.2f}s while a local tool ran"


@pytest.mark.asyncio
async def test_a_local_tool_that_runs_too_long_comes_back_as_a_tool_error(monkeypatch):
    monkeypatch.setattr(toolbox, "LOCAL_TIMEOUT_S", 0.2)
    monkeypatch.setitem(toolbox.REGISTRY, "ext.slow.tool", _slow_tool(1.0))
    runner = toolbox.ToolRunner(_dummy_app, tools=["ext.slow.tool"])
    t0 = time.monotonic()
    res = await runner.call("ext.slow.tool", {})
    await runner.aclose()
    assert not res.ok and "TIMED OUT" in res.text
    assert time.monotonic() - t0 < 0.8


# --- H-12 item 3 (extension tools over /mcp): SKIPPED. docs/EXTENSIONS.md and test_extensions.py pin it as intended: an enabled extension's
# tools are offered to MCP clients under their full name, loopback-only and read-only (order-word guard). Hiding every `desk_only` tool
# would also hide the 12 built-in desk tools that docs/MCP.md and test_phase20_mcp.py promise.


# --- H-12 item 4: POST /mcp reads a capped body and wants application/json ------------------------------------------------------------------
def test_mcp_refuses_a_huge_body(client):
    big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * 5_000_000 + b'"}}'
    r = client.post("/mcp", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_mcp_refuses_a_body_that_is_not_declared_json(client):
    r = client.post("/mcp", content=b'{"jsonrpc":"2.0","id":1,"method":"ping"}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 400 and "application/json" in r.text


def test_mcp_still_answers_a_normal_message(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200 and r.json()["result"] == {}


# --- H-12 item 6: a read verb in front of an order phrase must not hide an order tool --------------------------------------------------------
@pytest.mark.parametrize("name", ["get_place_order", "list_submit_order", "fetch_modify_order", "read_cancel_order", "getPlaceOrder",
                                  "show_execute_trade", "get_amend_position", "search_square_position"])
def test_read_verb_does_not_hide_an_order_action(name):
    assert order_like(name), name


@pytest.mark.parametrize("name", ["get_orders", "list_open_orders", "get_positions", "get_order_book", "stock_quote", "get_trade_history",
                                  "search_trades", "market_status", "index_option_chain", "get_equity_details"])
def test_read_only_names_still_pass(name):
    assert not order_like(name), name


# --- H-12 item 7: one run's external tools are not wiped by another run's prepare() -------------------------------------------------------
@pytest.mark.asyncio
async def test_a_runner_keeps_its_own_external_tools_when_the_global_set_is_replaced():
    async def run(args: dict) -> toolbox.ToolResult:
        return toolbox.ToolResult(ok=True, text="hi", source="x")

    tool = toolbox.ExternalTool("srv.echo", "srv__echo", "srv", "echo", toolbox.obj({}), run)
    toolbox.EXTERNAL.clear()
    toolbox.EXTERNAL["srv.echo"] = tool
    try:
        run_a = toolbox.ToolRunner(_dummy_app, tools=["srv.echo"])  # run A starts: its tools are fixed now
        toolbox.EXTERNAL.clear()  # run B's prepare() (or a shutdown) replaces the global set
        res = await run_a.call("srv.echo", {})
        assert res.ok and res.text == "hi"
        run_b = toolbox.ToolRunner(_dummy_app, tools=["srv.echo"])  # a run that starts later sees the new (empty) set
        assert not (await run_b.call("srv.echo", {})).ok
        await run_a.aclose()
        await run_b.aclose()
    finally:
        toolbox.EXTERNAL.clear()


# --- H-13: no public bind without remote mode ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_bind_is_fine(host, monkeypatch):
    monkeypatch.delenv("OPENTERM_REMOTE", raising=False)
    remote.check_bind(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", ""])
def test_public_bind_is_refused_without_remote_mode(host, monkeypatch):
    monkeypatch.delenv("OPENTERM_REMOTE", raising=False)
    monkeypatch.delenv("OPENTERM_ALLOW_PUBLIC_BIND", raising=False)
    with pytest.raises(RuntimeError, match="OPENTERM_REMOTE"):
        remote.check_bind(host)


def test_public_bind_is_allowed_in_remote_mode_or_with_the_explicit_flag(monkeypatch):
    monkeypatch.setenv("OPENTERM_REMOTE", "1")
    remote.check_bind("0.0.0.0")
    monkeypatch.delenv("OPENTERM_REMOTE")
    monkeypatch.setenv("OPENTERM_ALLOW_PUBLIC_BIND", "1")
    remote.check_bind("0.0.0.0")


def test_python_dash_m_openterm_refuses_to_start_on_0_0_0_0():
    env = {k: v for k, v in os.environ.items() if k not in ("OPENTERM_REMOTE", "OPENTERM_ALLOW_PUBLIC_BIND")}
    env["OPENTERM_HOST"] = "0.0.0.0"
    p = subprocess.run([sys.executable, "-m", "openterm"], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode != 0 and "OPENTERM_REMOTE" in (p.stderr + p.stdout)


# --- H-13: Kite login `state` -------------------------------------------------------------------------------------------------------------
KEY, SECRET, REQUEST_TOKEN = "docshape_api_key", "docshape_secret", "docshape_request_token"


def _set_keys(client):
    r = client.put("/api/keys/kite", json={"fields": {"KITE_API_KEY": KEY, "KITE_API_SECRET": SECRET}})
    assert r.status_code == 200, r.text


def _state_from_login(client) -> str:
    loc = client.get("/api/kite/login", follow_redirects=False).headers["location"]
    sent = parse_qs(urlsplit(loc).query)["redirect_params"][0]  # Kite hands this string back on the redirect
    return parse_qs(sent)["state"][0]


def test_kite_callback_without_state_is_refused(client):
    _set_keys(client)
    r = client.get("/api/kite/callback", params={"request_token": REQUEST_TOKEN, "status": "success"})
    assert r.status_code == 403 and "STATE" in r.text.upper()
    assert client.get("/api/kite/status").json()["state"] == "LOGGED OUT"


def test_kite_callback_with_a_wrong_state_is_refused(client):
    _set_keys(client)
    _state_from_login(client)
    r = client.get("/api/kite/callback", params={"request_token": REQUEST_TOKEN, "status": "success", "state": "forged"})
    assert r.status_code == 403
    assert client.get("/api/kite/status").json()["state"] == "LOGGED OUT"


def test_kite_state_is_new_each_login_and_works_once(client):
    _set_keys(client)
    s1, s2 = _state_from_login(client), _state_from_login(client)
    assert s1 != s2 and len(s2) >= 16
    ok = client.get("/api/kite/callback", params={"request_token": REQUEST_TOKEN, "status": "success", "state": s2})
    assert ok.status_code == 200 and "LOGGED IN" in ok.text.upper()
    again = client.get("/api/kite/callback", params={"request_token": REQUEST_TOKEN, "status": "success", "state": s2})
    assert again.status_code == 403  # a state is used up by the first answer
