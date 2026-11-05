"""Phase 16 step 6: the hash-chained audit ledger for AI, SWARM, AI AUTO and BT runs. Models are scripted; nothing touches the network."""

import asyncio
import json
import time

from test_phase16_agent import FakeGateway, call, sse, text

from openterm.db import open_db


def run(coro):
    return asyncio.run(coro)


async def ledger():
    from openterm.ai.audit import AuditLog

    return AuditLog(await open_db(":memory:"))


MF = {"model": "m", "prompt_sha": "x"}


# --- the chain --------------------------------------------------------------------------------------------------------------------------
def test_entries_chain_and_verify():
    async def go():
        led = await ledger()
        assert (await led.verify()) == {"ok": True, "count": 0, "head": "0" * 64, "broken_at": None, "reason": None}
        a = await led.append("chat", "", "m", MF, {"n": 1})
        b = await led.append("swarm", "0123456789ab", "m", MF, {"n": 2})
        assert a["prev_hash"] == "0" * 64 and b["prev_hash"] == a["hash"] and a["hash"] != b["hash"]
        v = await led.verify()
        assert v["ok"] and v["count"] == 2 and v["head"] == b["hash"]
        es = await led.entries()
        assert [e["seq"] for e in es] == [2, 1] and es[1]["manifest"] == MF and es[0]["meta"] == {"n": 2}
        await led.db.close()

    run(go())


def test_changing_removing_or_reordering_an_entry_breaks_the_chain_at_that_entry():
    async def go():
        led = await ledger()
        for i in range(4):
            await led.append("chat", str(i), "m", MF, {"i": i})
        await led.db.execute("UPDATE ai_ledger SET meta=? WHERE seq=2", (json.dumps({"i": 99}),))
        await led.db.commit()
        v = await led.verify()
        assert not v["ok"] and v["broken_at"] == 2 and "CHANGED" in v["reason"]
        await led.db.execute("UPDATE ai_ledger SET meta=? WHERE seq=2", (json.dumps({"i": 1}, separators=(",", ":")),))  # undo (same canonical text)
        await led.db.commit()
        assert (await led.verify())["ok"]
        await led.db.execute("DELETE FROM ai_ledger WHERE seq=2")
        await led.db.commit()
        v = await led.verify()
        assert not v["ok"] and v["broken_at"] == 3 and "REMOVED" in v["reason"]
        await led.db.close()

    run(go())


def test_concurrent_appends_keep_one_unbroken_chain():
    async def go():
        led = await ledger()
        await asyncio.gather(*(led.append("chat", str(i), "m", MF, {"i": i}) for i in range(12)))
        v = await led.verify()
        assert v["ok"] and v["count"] == 12
        await led.db.close()

    run(go())


def test_manifest_hashes_prompt_tools_and_skills_without_storing_text():
    from openterm.ai import audit, tools

    m = audit.manifest("secret prompt text", ["quote", "history"], "deepseek/x", "openrouter")
    assert m["tools"] == ["history", "quote"] and len(m["prompt_sha"]) == 64 and len(m["tools_sha"]) == 64
    assert {"valuation", "earnings", "options", "risk", "macro"} <= set(m["skills"]) and m["model"] == "deepseek/x" and m["app"]
    assert "secret prompt text" not in json.dumps(m)
    assert audit.manifest("secret prompt text", ["quote"], "deepseek/x", "openrouter")["tools_sha"] != m["tools_sha"]
    assert set(audit.manifest("p", None, "m", "o")["tools"]) == {t.name for t in tools.REGISTRY.values() if not t.doc_only}


# --- routes -----------------------------------------------------------------------------------------------------------------------------
def test_chat_swarm_and_auto_each_write_one_entry_with_hashes_only(client):
    client.app.state.llm = FakeGateway(
        call("quote", {"symbols": "AAPL"}, cid="c1"), text("AAPL at 5.5 [T1]."),
        text("fund"), text("tech"), text("risk"), text("chair"),
        text("No backtest was run."))
    sse(client.post("/api/ai/chat", json={"question": "what is the price of SECRETWORD?"}))
    sse(client.post("/api/ai/swarm", json={"preset": "COMMITTEE", "subject": "AAPL"}))
    sse(client.post("/api/ai/auto", json={"hypothesis": "momentum works"}))
    es = client.get("/api/ai/ledger").json()["entries"]
    assert [e["kind"] for e in es] == ["ai_auto", "swarm", "chat"]
    chat = es[2]
    assert chat["model"] == "deepseek/deepseek-v4-pro" and chat["manifest"]["prompt_sha"] and len(chat["meta"]["question_sha"]) == 64
    assert chat["meta"]["tool_calls"][0]["name"] == "quote" and len(chat["meta"]["tool_calls"][0]["args_sha"]) == 64
    assert es[1]["ref"] and len(es[1]["ref"]) == 12  # the stored SWARM run id
    assert "SECRETWORD" not in json.dumps(es) and "momentum" not in json.dumps(es)  # hashes and metadata only
    v = client.get("/api/ai/ledger/verify").json()
    assert v["ok"] and v["count"] == 3 and v["head"] == es[0]["hash"]


def test_an_error_run_writes_no_entry(client):
    sse(client.post("/api/ai/chat", json={"question": "hi"}))  # no key: KEY REQUIRED, nothing answered
    assert client.get("/api/ai/ledger").json() == {"entries": []}
    assert client.get("/api/ai/ledger/verify").json()["ok"] is True


def test_a_bt_run_is_recorded_with_its_hashes(client):
    r = client.post("/api/bt/run", json={"rule": "SMA20>SMA50", "symbols": ["AAPL"], "interval": "1D", "range": "10Y"})
    end = time.monotonic() + 30
    job = {}
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{r.json()['id']}").json()
        if job["state"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.05)
    assert job["state"] == "done"
    es = client.get("/api/ai/ledger").json()["entries"]
    assert [e["kind"] for e in es] == ["bt"] and es[0]["ref"] == job["result"]["run_id"]
    assert len(es[0]["meta"]["data_sha"]) >= 16 and len(es[0]["meta"]["config_sha"]) == 64 and es[0]["meta"]["metrics"]
    assert client.get("/api/ai/ledger/verify").json()["ok"] is True
