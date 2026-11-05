"""Phase 16 step 3: finance playbooks (skills), the `skill` and `strategy_check` tools, `AI BT` (a drafted rule, shown and never run by the AI)
and `AI CHART` (a vision model describing the chart image). Written before the code; models are scripted (FakeGateway), nothing touches the network."""

import json

from test_phase16_agent import FakeGateway, call, sse, text

from openterm.llm.events import Event

NAMES = {"valuation", "earnings", "options", "risk", "macro"}
DRAFT = {"symbols": ["AAPL"], "rule": "SMA20 CROSS> SMA50", "range": "5Y", "interval": "1D", "rationale": "Trend following on the 20/50 average cross."}


def draft_text(d=None, lead="Here is a trend rule."):
    return text(f"{lead}\nBT_DRAFT {json.dumps(d or DRAFT)}\n")


# --- skills -----------------------------------------------------------------------------------------------------------------------------
def test_five_playbooks_exist_and_only_name_real_tools():
    from openterm.ai import skills, tools

    assert NAMES <= set(skills.names())  # Phase 20 ported more playbooks next to these five (test_phase20_skills.py)
    for n in NAMES:
        body = skills.get(n)
        assert body and 300 < len(body) < 5000, n
        assert "not personalised investment advice" in body.lower() or "not investment advice" in body.lower(), n
        for word in body.replace("`", " ` ").split("`")[1::2]:  # every `backticked` identifier that looks like a tool must exist
            if word.islower() and word.replace("_", "").isalpha() and word in {"quote", "history", "fa", "filings", "news", "research", "options_chain", "rates", "macro",
                                                                              "portfolio", "backtest_run", "quant", "screener", "profile"}:
                assert word in tools.REGISTRY
    assert skills.get("nope") is None


def test_skill_and_strategy_check_tools_are_registered_and_validated():
    from openterm.ai import tools

    assert "skill" in tools.REGISTRY and "strategy_check" in tools.REGISTRY
    assert tools.validate("skill", {"name": "valuation"}) is None
    assert "name" in tools.validate("skill", {"name": "astrology"})
    assert tools.validate("strategy_check", {"rule": "SMA20>SMA50"}) is None
    assert "rule" in tools.validate("strategy_check", {})


def test_agent_can_load_a_playbook_and_check_a_rule_through_the_app(client):
    client.app.state.llm = FakeGateway([
        Event("tool_call", id="c1", name="skill", args={"name": "risk"}),
        Event("tool_call", id="c2", name="strategy_check", args={"rule": "SMA20 CROSS> SMA50"}),
        Event("tool_call", id="c3", name="strategy_check", args={"rule": "SMA20 >>> SMA50"}),
        Event("done")], text("ok"))
    ev = sse(client.post("/api/ai/chat", json={"question": "use a playbook"}))
    res = {e["id"]: e for e in ev if e["type"] == "tool_result"}
    assert res["T1"]["ok"] and res["T1"]["bytes"] > 300
    sent = [m for m in client.app.state.llm.calls[1]["messages"] if m["role"] == "tool"]
    assert json.loads(sent[1]["content"]) == {"valid": True, "rule": "SMA20 CROSS> SMA50", "warmup_bars": 50}
    bad = json.loads(sent[2]["content"])
    assert bad["valid"] is False and "error" in bad and isinstance(bad["col"], int)
    assert res["T3"]["ok"]  # a rejected rule is information for the model, not a failed call (it must not trip the loop guard)


# --- AI BT ------------------------------------------------------------------------------------------------------------------------------
def test_ai_bt_returns_a_validated_draft_command_and_runs_nothing(client):
    client.app.state.llm = FakeGateway(draft_text())
    r = client.post("/api/ai/bt", json={"idea": "buy AAPL when the 20 day average crosses the 50 day"})
    ev = sse(r)
    d = next(e for e in ev if e["type"] == "draft")["draft"]
    assert d["command"] == "BT AAPL SMA20 CROSS> SMA50 1D 5Y" and d["rule"] == "SMA20 CROSS> SMA50" and d["symbols"] == ["AAPL"]
    assert d["rationale"].startswith("Trend following") and "HISTORICAL SIMULATION" in d["note"]
    assert ev[-1]["type"] == "done"
    assert client.get("/api/bt/runs").json()["runs"] == []  # drafting never runs a backtest
    first = client.app.state.llm.calls[0]
    assert "BT_DRAFT" in first["messages"][0]["content"] and {t["function"]["name"] for t in first["tools"]} >= {"strategy_check", "history", "skill"}
    assert not {t["function"]["name"] for t in first["tools"]} & {"backtest_run", "quant"}  # the draft is the model's whole job


def test_ai_bt_rejects_a_rule_the_engine_would_reject_and_missing_drafts(client):
    client.app.state.llm = FakeGateway(draft_text({**DRAFT, "rule": "SMA20 >>> SMA50"}))
    ev = sse(client.post("/api/ai/bt", json={"idea": "x"}))
    assert not [e for e in ev if e["type"] == "draft"]
    assert "RULE" in next(e for e in ev if e["type"] == "draft_error")["text"].upper()
    client.app.state.llm = FakeGateway(text("I cannot do that."))
    ev = sse(client.post("/api/ai/bt", json={"idea": "x"}))
    assert "BT_DRAFT" in next(e for e in ev if e["type"] == "draft_error")["text"]
    client.app.state.llm = FakeGateway(draft_text({**DRAFT, "symbols": ["AAPL"] * 0}))
    assert [e for e in sse(client.post("/api/ai/bt", json={"idea": "x"})) if e["type"] == "draft_error"]


def test_ai_bt_body_checks(client):
    assert client.post("/api/ai/bt", json={"idea": ""}).status_code == 400
    assert client.post("/api/ai/bt", json={"idea": "y" * 3000}).status_code == 400


# --- AI CHART ---------------------------------------------------------------------------------------------------------------------------
PNG = "data:image/png;base64,iVBORw0KGgo="


def test_ai_chart_sends_the_image_to_the_vision_model_with_no_tools(client):
    client.app.state.llm = FakeGateway(text("The chart shows an uptrend. [IMAGE]"))
    ev = sse(client.post("/api/ai/chart", json={"image": PNG, "symbol": "AAPL", "range": "1Y"}))
    call_ = client.app.state.llm.calls[0]
    assert call_["tools"] is None and call_["model"] == "deepseek/deepseek-v4.1-flash"  # the default vision model
    user = call_["messages"][-1]["content"]
    assert user[0]["type"] == "text" and "AAPL" in user[0]["text"] and user[1] == {"type": "image_url", "image_url": {"url": PNG}}
    done = ev[-1]
    assert done["type"] == "done" and done["label"] == "CHART IMAGE ONLY" and "uptrend" in done["answer"]
    assert ev[0]["type"] == "start" and ev[0]["model"] == "deepseek/deepseek-v4.1-flash"


def test_ai_chart_validates_the_image(client):
    assert client.post("/api/ai/chart", json={"image": "http://evil/x.png"}).status_code == 400
    assert client.post("/api/ai/chart", json={"image": "data:text/html;base64,AAAA"}).status_code == 400
    assert client.post("/api/ai/chart", json={"image": "data:image/png;base64," + "A" * 4_200_000}).status_code == 400
    assert client.post("/api/ai/chart", json={}).status_code == 400


def test_ai_chart_without_a_key_says_key_required(client):
    ev = sse(client.post("/api/ai/chart", json={"image": PNG, "symbol": "AAPL"}))
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == "key_required"


def test_chat_with_calls_still_works_after_the_registry_grew(client):
    client.app.state.llm = FakeGateway(call("quote", {"symbols": "AAPL"}), text("AAPL is at 343.46 [T1]."))
    assert sse(client.post("/api/ai/chat", json={"question": "AAPL?"}))[-1]["grounded"] is True
