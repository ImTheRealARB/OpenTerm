"""AI BT CODE: a drafted SignalEngine strategy, validated with the BT EDIT sandbox check (nothing executed), one repair round, ledgered.
The model is scripted (FakeGateway); nothing touches the network."""

from fastapi.testclient import TestClient
from test_phase16_agent import FakeGateway, sse, text

from openterm.ai import btcode
from openterm.bt.templates import SMA_CROSS

GOOD = SMA_CROSS
BAD = "import os\n" + SMA_CROSS


def answer(code, name="my_cross"):
    return text(f"A trend rule.\n```python\n{code}```\nBT_CODE_NAME {name}\n")


def draft_of(ev):
    return next(e for e in ev if e["type"] == "code_draft")["draft"]


def test_valid_draft_passes_validation_and_runs_nothing(client):
    client.app.state.llm = FakeGateway(answer(GOOD))
    ev = sse(client.post("/api/ai/bt_code", json={"idea": "buy when the 20 day average is above the 50 day"}))
    d = draft_of(ev)
    assert d["ok"] is True and d["error"] is None and d["code"] == GOOD and d["name"] == "my_cross" and d["repaired"] is False
    assert "NOT RUN" in d["note"] and "NOT SAVED" in d["note"]
    assert ev[-1]["type"] == "done" and "```" not in ev[-1]["answer"] and "BT_CODE_NAME" not in ev[-1]["answer"]
    assert len(client.app.state.llm.calls) == 1
    assert client.get("/api/bt/runs").json()["runs"] == [] and client.get("/api/bt/strategies").json()["strategies"] == []
    first = client.app.state.llm.calls[0]
    system = first["messages"][0]["content"]
    assert "class SignalEngine" in system and "numpy" in system and "RSI" in system and "BT_CODE_NAME" in system
    assert {t["function"]["name"] for t in first["tools"]} == {"history", "skill"}


def test_invalid_draft_gets_one_repair_round_with_the_error_fed_back(client):
    client.app.state.llm = FakeGateway(answer(BAD), answer(GOOD))
    ev = sse(client.post("/api/ai/bt_code", json={"idea": "x"}))
    d = draft_of(ev)
    assert d["ok"] is True and d["repaired"] is True and d["code"] == GOOD
    assert any("REPAIR" in e["text"] for e in ev if e["type"] == "notice")
    calls = client.app.state.llm.calls
    assert len(calls) == 2
    assert "IMPORT os IS NOT ALLOWED" in calls[1]["messages"][-1]["content"]
    assert [e["type"] for e in ev].count("start") == 1


def test_still_invalid_returns_the_errors_after_exactly_one_repair(client):
    client.app.state.llm = FakeGateway(answer(BAD), answer(BAD), answer(GOOD))
    ev = sse(client.post("/api/ai/bt_code", json={"idea": "x"}))
    d = draft_of(ev)
    assert d["ok"] is False and d["repaired"] is True and d["line"] == 1 and "IMPORT os" in d["error"] and d["code"] == BAD
    assert len(client.app.state.llm.calls) == 2  # never a third round


def test_no_code_block_is_an_error_without_a_repair_round(client):
    client.app.state.llm = FakeGateway(text("I cannot do that."))
    d = draft_of(sse(client.post("/api/ai/bt_code", json={"idea": "x"})))
    assert d["ok"] is False and "CODE BLOCK" in d["error"] and d["code"] == "" and d["name"] == "ai_draft"


def test_ledger_entry_is_written_with_hashes_only(client):
    client.app.state.llm = FakeGateway(answer(BAD), answer(GOOD))
    sse(client.post("/api/ai/bt_code", json={"idea": "SECRETIDEA"}))
    es = client.get("/api/ai/ledger").json()["entries"]
    assert [e["kind"] for e in es] == ["ai_bt_code"]
    assert len(es[0]["meta"]["question_sha"]) == 64 and "SECRETIDEA" not in str(es) and "class SignalEngine" not in str(es)
    assert client.get("/api/ai/ledger/verify").json()["ok"] is True


def test_body_checks_and_non_loopback_refused(client):
    assert client.post("/api/ai/bt_code", json={"idea": ""}).status_code == 400
    assert client.post("/api/ai/bt_code", json={"idea": "y" * 3000}).status_code == 400
    assert client.post("/api/ai/bt_code", json={"idea": "x", "model": "bad model!"}).status_code == 400
    other = TestClient(client.app, client=("203.0.113.9", 5))
    client.app.state.llm = FakeGateway(answer(GOOD))
    assert other.post("/api/ai/bt_code", json={"idea": "x"}).status_code == 403
    assert client.app.state.llm.calls == []


def test_helpers():
    assert btcode.extract_code("a\n```python\nx = 1\n```\nb\n```python\ny = 2\n```") == "y = 2\n"
    assert btcode.extract_code("class SignalEngine:\n    pass") is not None and btcode.extract_code("nothing") is None
    assert btcode.suggest_name("BT_CODE_NAME Bad Name!") == "ai_draft" and btcode.suggest_name("BT_CODE_NAME ok_name-1") == "ok_name-1"
    assert btcode.validate("x = (")["error"].startswith("LINE 1: SYNTAX ERROR")
    assert btcode.validate(GOOD)["ok"] is True
    assert set(btcode.BT_CODE_TOOLS) == {"history", "skill"}
