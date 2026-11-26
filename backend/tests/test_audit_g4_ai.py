"""Audit group 4: AI grounding labels and the audit trail (C-13, C-14, H-19, H-21, H-32, M-15).

Each test states the REQUIREMENT (what the user is told, what the ledger records), not the code's predicate. The model is scripted; nothing
touches the network."""

import json

from test_phase16_agent import FakeGateway, call, ok, run, sse, text
from test_phase16_swarm import collect_swarm
from test_phase20_filings import BAD as FILING_BAD
from test_phase20_filings import GOOD as FILING_GOOD
from test_phase20_filings import points_reply, sec  # noqa: F401 - `sec` is a fixture the filing route tests need

from openterm.ai import audit, tools, web


def offered_registry_names(call_tools: list[dict] | None) -> list[str]:
    """Names of the tools a gateway call actually offered the model (third-party tools excluded: none are enabled in tests)."""
    return sorted(t["function"]["name"] for t in call_tools or [])


# --- C-14 / H-32: the manifest lists what the model was really offered ------------------------------------------------------------------
def test_default_manifest_tools_are_exactly_the_tools_offered_to_the_model():
    offered = offered_registry_names(tools.openai_tools())
    assert offered, "the default chat offers some tools"
    assert audit.manifest("p", None, "m", "o")["tools"] == offered
    # the tools plain chat does not get must not be claimed: desk-only, doc-only and web-only ones
    claimed = set(audit.manifest("p", None, "m", "o")["tools"])
    assert not claimed & {t.name for t in tools.REGISTRY.values() if t.desk_only or t.doc_only or t.web_only}


def test_chat_ledger_entry_lists_the_tools_the_gateway_was_given(client):
    client.app.state.llm = FakeGateway(text("hello"))
    sse(client.post("/api/ai/chat", json={"question": "hi"}))
    sent = offered_registry_names(client.app.state.llm.calls[0]["tools"])
    entry = client.get("/api/ai/ledger").json()["entries"][0]
    assert entry["manifest"]["tools"] == sent


def test_manifest_with_web_on_is_the_default_tools_plus_the_two_web_tools():
    cfg = web.WebConfig(provider="brave")
    # what agent.run offers with web access on: the default tools plus the web tools
    offered = offered_registry_names(tools.openai_tools() + tools.openai_tools(list(web.WEB_TOOLS)))
    assert audit.manifest("p", web.offered_names(None, cfg), "m", "o")["tools"] == offered


# --- C-13: grounded / UNGROUNDED labels -------------------------------------------------------------------------------------------------
def test_bt_code_that_used_no_tool_data_is_labelled_ungrounded(client):
    from openterm.bt.templates import SMA_CROSS

    client.app.state.llm = FakeGateway(text(f"A trend rule.\n```python\n{SMA_CROSS}```\nBT_CODE_NAME x\n"))
    done = sse(client.post("/api/ai/bt_code", json={"idea": "trend"}))[-1]
    assert done["type"] == "done" and done["tool_calls"] == 0
    assert done["grounded"] is False and done["label"] == "UNGROUNDED"


def test_bt_code_that_read_history_is_grounded(client):
    from openterm.bt.templates import SMA_CROSS

    client.app.state.llm = FakeGateway(call("history", {"symbol": "AAPL", "range": "1Y"}), text(f"Rule.\n```python\n{SMA_CROSS}```\nBT_CODE_NAME x\n"))
    done = sse(client.post("/api/ai/bt_code", json={"idea": "trend"}))[-1]
    assert done["tool_calls"] == 1 and done["grounded"] is True and done["label"] is None


def test_swarm_is_grounded_when_only_the_chair_used_tool_data():
    gw = FakeGateway(text("a"), text("b"), text("c"), call("quote", {"symbols": "AAPL"}), text("Price 123.45 [T1]."))
    # the analysts' notes hold no number, the chair fetched 123.45 itself: the figure is sourced and the desk is grounded
    ev, _ = run(collect_swarm(gw, results=[ok({"price": 123.45})]))
    done = ev[-1]
    assert done["type"] == "swarm_done" and done["grounded"] is True and done["label"] is None
    assert done["unsourced"] == []


def test_swarm_chair_number_nobody_fetched_is_still_unsourced_when_the_chair_used_a_tool():
    gw = FakeGateway(text("a"), text("b"), text("c"), call("quote", {"symbols": "AAPL"}), text("Price 123.45 and fair value 999.99."))
    ev, _ = run(collect_swarm(gw, results=[ok({"price": 123.45})]))
    assert ev[-1]["unsourced"] == ["999.99"]


# --- H-19: AI FILING says UNGROUNDED when no quote verified -----------------------------------------------------------------------------
def test_filing_with_no_verified_quote_is_ungrounded(client, sec):  # noqa: F811 - the imported fixture
    client.app.state.llm = FakeGateway(points_reply(FILING_BAD))
    done = sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "What supply chain risks does the company have?"}))[-1]
    assert done["verified"] == 0 and done["unverified"] == 1
    assert done["grounded"] is False and done["label"] == "UNGROUNDED"


def test_filing_with_a_verified_quote_stays_grounded(client, sec):  # noqa: F811 - the imported fixture
    client.app.state.llm = FakeGateway(points_reply(FILING_GOOD))
    done = sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "What supply chain risks does the company have?"}))[-1]
    assert done["verified"] == 1 and done["grounded"] is True and done["label"] is None


# --- H-21: a chart read is an AI run, so it is in the ledger ----------------------------------------------------------------------------
def test_chart_description_writes_a_ledger_entry_with_no_tools_and_no_text(client):
    client.app.state.llm = FakeGateway(text("An up trend SECRETCHART."))
    image = "data:image/png;base64,iVBORw0KGgo="
    ev = sse(client.post("/api/ai/chart", json={"image": image, "symbol": "AAPL", "range": "1Y"}))
    assert ev[-1]["type"] == "done" and ev[-1]["grounded"] is False
    es = client.get("/api/ai/ledger").json()["entries"]
    assert [e["kind"] for e in es] == ["ai_chart"]
    assert es[0]["manifest"]["tools"] == [] and es[0]["meta"]["grounded"] is False
    assert "SECRETCHART" not in json.dumps(es) and image not in json.dumps(es)
    assert client.get("/api/ai/ledger/verify").json()["ok"] is True


# --- M-15: context and the web prompt -----------------------------------------------------------------------------------------------------
def test_fit_never_blanks_the_tool_results_of_the_current_question():
    from openterm.ai.context import DROPPED, fit

    def turn(cid, q, body):
        return [{"role": "user", "content": q},
                {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": "quote", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": cid, "content": body}]

    msgs = [{"role": "system", "content": "SYS"}, *turn("a", "old", "o" * 60000), *turn("b", "now", "n" * 20000)]
    out = fit(msgs, budget=3000)
    now = next(m for m in out if m.get("tool_call_id") == "b")
    assert now["content"] != DROPPED  # the data the answer is being written from stays, whatever else goes


def test_a_desk_role_offered_web_tools_is_not_told_it_has_no_web_access():
    """M-15 (agent.py part) checked: the rewrite works for the desk rules, the only prompt that claims "no web access"; the plain chat prompt claims nothing."""
    from test_phase16_agent import Tools

    from openterm.ai import agent, swarm

    async def go(tool_names):
        gw = FakeGateway(text("ok"))
        _ = [e async for e in agent.run(gw, Tools(), "q?", [], model="m", tools=tool_names, system=swarm.DESK_RULES.format(today="2026-01-01"))]
        return gw.calls[0]["messages"][0]["content"]

    assert "no web access" not in run(go(["quote", *web.WEB_TOOLS])).lower()
    assert "no web access" in run(go(["quote"])).lower()
    assert "web access" not in agent.SYSTEM.lower()
