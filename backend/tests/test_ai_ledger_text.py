"""Opt-in ledger text (`ai.storeText`): the redacted question and answer are kept in a side table, outside the hash chain. Models are scripted."""

import json

from test_phase16_agent import SECRET, FakeGateway, sse, text


def set_store_text(client, on: bool):
    cur = client.get("/api/settings").json()
    s = dict(cur["settings"] or {})
    s["ai"] = {**(s.get("ai") or {}), "storeText": on}
    r = client.put("/api/settings", json={"settings": s, "version": cur["version"]})
    assert r.status_code == 200, r.text


def ask(client, q):
    return sse(client.post("/api/ai/chat", json={"question": q}))


def test_text_is_not_stored_by_default(client):
    client.app.state.llm = FakeGateway(text("The answer is PLUM."))
    ask(client, "what about APRICOT?")
    es = client.get("/api/ai/ledger").json()["entries"]
    assert len(es) == 1 and es[0]["has_text"] is False
    assert client.get(f"/api/ai/ledger/{es[0]['seq']}/text").status_code == 404


def test_text_on_stores_redacted_question_and_answer_and_the_chain_still_verifies(client):
    set_store_text(client, True)
    client.app.state.llm = FakeGateway(text(f"The answer is PLUM and token={SECRET}."))
    ask(client, f"what about APRICOT? apikey={SECRET}")
    e = client.get("/api/ai/ledger").json()["entries"][0]
    assert e["has_text"] is True
    t = client.get(f"/api/ai/ledger/{e['seq']}/text").json()
    assert "APRICOT" in t["question"] and "PLUM" in t["answer"] and t["stored_at"] > 0
    assert SECRET not in json.dumps(t) and "***" in t["question"] and "***" in t["answer"]
    assert SECRET not in json.dumps(client.get("/api/ai/ledger").json())
    assert "APRICOT" not in json.dumps(e)  # the ledger entry itself still holds hashes only
    v = client.get("/api/ai/ledger/verify").json()
    assert v["ok"] and v["count"] == 1


def test_purge_removes_text_but_never_breaks_the_chain(client):
    set_store_text(client, True)
    client.app.state.llm = FakeGateway(text("one"), text("two"), text("three"))
    for q in ("q1", "q2", "q3"):
        ask(client, q)
    head = client.get("/api/ai/ledger/verify").json()["head"]
    assert all(e["has_text"] for e in client.get("/api/ai/ledger").json()["entries"])
    r = client.post("/api/ai/ledger/purge-text", json={"seq": 2})
    assert r.json() == {"purged": 1}
    assert [e["has_text"] for e in client.get("/api/ai/ledger").json()["entries"]] == [True, False, True]
    assert client.post("/api/ai/ledger/purge-text", json={}).json() == {"purged": 2}
    assert not any(e["has_text"] for e in client.get("/api/ai/ledger").json()["entries"])
    v = client.get("/api/ai/ledger/verify").json()
    assert v["ok"] and v["count"] == 3 and v["head"] == head  # same chain, text gone
    assert client.get("/api/ai/ledger/1/text").status_code == 404


def test_turning_it_off_again_stops_storing(client):
    set_store_text(client, True)
    client.app.state.llm = FakeGateway(text("a"), text("b"))
    ask(client, "first")
    set_store_text(client, False)
    ask(client, "second")
    assert [e["has_text"] for e in client.get("/api/ai/ledger").json()["entries"]] == [False, True]


def test_every_run_kind_stores_text_when_on(client):
    set_store_text(client, True)
    client.app.state.llm = FakeGateway(text("fund"), text("tech"), text("risk"), text("chair"), text("No backtest was run."), text("a rule"))
    sse(client.post("/api/ai/swarm", json={"preset": "COMMITTEE", "subject": "AAPL"}))
    sse(client.post("/api/ai/auto", json={"hypothesis": "momentum works"}))
    sse(client.post("/api/ai/bt", json={"idea": "buy dips"}))
    es = client.get("/api/ai/ledger").json()["entries"]
    assert [e["kind"] for e in es] == ["ai_bt", "ai_auto", "swarm"] and all(e["has_text"] for e in es)
    assert "momentum works" in client.get(f"/api/ai/ledger/{es[1]['seq']}/text").json()["question"]


def test_text_routes_are_loopback_only(client):
    from fastapi.testclient import TestClient

    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.get("/api/ai/ledger/1/text").status_code == 403
    assert other.post("/api/ai/ledger/purge-text", json={}).status_code == 403


def test_settings_validate_store_text(client):
    cur = client.get("/api/settings").json()
    s = dict(cur["settings"] or {})
    s["ai"] = {"storeText": "yes"}
    assert client.put("/api/settings", json={"settings": s, "version": cur["version"]}).status_code == 400
