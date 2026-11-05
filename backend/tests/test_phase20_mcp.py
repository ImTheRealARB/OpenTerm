"""Phase 20 step 8: the MCP server must expose the Phase 20 read tools and have a console entry point.

The server itself was built in Phase 17 (see test_phase17_mcp.py); this file only checks what Phase 20 added.
Nothing here touches the network: the app runs in fixture mode through the shared `client` fixture.
"""

import re
import tomllib
from pathlib import Path

from openterm.mcp import server

# The twelve read-only tools Step 4 added. They are `desk_only` (kept out of plain AI chat to save prompt tokens)
# but an MCP client lists tools once, so it must see them.
PHASE20_TOOLS = {
    "indicators", "option_price", "option_payoff", "etf", "holders", "insiders",
    "calendar", "pred", "energy", "crypto_funding", "crypto_depth", "rigor",
}
# Words that must never appear in a tool name (spec rule 6). `holdings` is blocked as a write-style broker word.
FORBIDDEN = re.compile(r"\b(orders?|trades?|gtt|margins?|kill|holdings?)\b", re.IGNORECASE)


def _names() -> set[str]:
    return {t.name for t in server.exposed_tools()}


def test_phase20_tools_are_listed_over_mcp():
    assert PHASE20_TOOLS <= _names()


def test_backtest_run_is_listed():
    assert "backtest_run" in _names()


def test_no_forbidden_tool_name():
    bad = [n for n in _names() if FORBIDDEN.search(n)]
    assert bad == []


def test_tools_list_over_the_wire_includes_phase20_tools(client):
    """Same check through the real JSON-RPC route, so a listing filter in routes.py cannot hide a tool."""
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200
    listed = {t["name"] for t in r.json()["result"]["tools"]}
    assert PHASE20_TOOLS <= listed


def test_console_script_points_at_the_stdio_bridge():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["openterm-mcp"] == "openterm.mcp.__main__:main"
