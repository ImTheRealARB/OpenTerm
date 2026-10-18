"""Phase 16 step 5: SWARM (a fixed DAG of roles over the agent loop), stored runs with replay, AI AUTO (hypothesis -> backtest -> evidence report) and
THESIS notes. Models are scripted (FakeGateway); nothing touches the network."""

import json

from test_phase16_agent import FakeGateway, Tools, call, ok, run, sse, text

from openterm.llm.events import Event


class RoleTools(Tools):
    async def aclose(self):
        pass


def err(kind="provider", msg="PROVIDER DOWN"):
    return [Event("error", kind=kind, text=msg)]


async def collect_swarm(gw, preset="COMMITTEE", subject="AAPL", results=()):
    from openterm.ai import swarm

    made: list[tuple[str, RoleTools]] = []

    def runner_for(role):
        t = RoleTools(*results)
        made.append((role.id, t))
        return t

    ev = [e async for e in swarm.run(gw, runner_for, swarm.PRESETS[preset], subject)]
    return ev, made


# --- presets ----------------------------------------------------------------------------------------------------------------------------
def test_presets_are_a_dag_of_analysts_then_one_chair_with_real_read_only_tools():
    from openterm.ai import swarm, tools

    assert set(swarm.PRESETS) == {"COMMITTEE", "RISK", "EARNINGS", "MACRO", "QUANT"}
    for p in swarm.PRESETS.values():
        assert [r.chair for r in p.roles].count(True) == 1 and p.roles[-1].chair, p.code
        assert len({r.id for r in p.roles}) == len(p.roles)
        for r in p.roles:
            assert r.tools and set(r.tools) <= set(tools.REGISTRY), (p.code, r.id)
            assert not any(w in t for t in r.tools for w in ("order", "kite", "gtt", "margin", "holding")), (p.code, r.id)
            assert "doc_search" not in r.tools
    listing = swarm.listing()
    assert [x["code"] for x in listing] == list(swarm.PRESETS) and all(x["roles"][-1]["id"] == "chair" for x in listing)


# --- the run ----------------------------------------------------------------------------------------------------------------------------
def test_committee_runs_every_role_with_its_own_tools_and_the_chair_sees_the_notes():
    gw = FakeGateway(call("quote", {"symbols": "AAPL"}), text("Price 123.45 [T1]."), text("Trend is up."), text("Headlines are quiet."),
                     text("The desk agrees on 123.45."))
    ev, made = run(collect_swarm(gw, results=[ok({"price": 123.45})]))
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "swarm_start" and kinds[-1] == "swarm_done" and kinds.count("role_done") == 4 and kinds.count("role_start") == 4
    assert [m[0] for m in made] == ["fundamental", "technical", "risk", "chair"]
    assert all(e["role"] for e in ev if e["type"] in ("token", "tool_call", "tool_result", "usage", "role_done"))
    offered = [[t["function"]["name"] for t in (c["tools"] or [])] for c in gw.calls]
    assert sorted(offered[0]) == sorted(["quote", "profile", "fa", "research", "skill"]) and sorted(offered[2]) == sorted(["history", "quote", "options_chain"])
    sent = next(c for c in gw.calls if "Analyst notes" in json.dumps(c["messages"]))
    user = sent["messages"][-1]["content"]
    assert "Subject: AAPL" in user and "Price 123.45 [T1]." in user and "Trend is up." in user and "Headlines are quiet." in user
    done = ev[-1]
    assert done["answer"] == "The desk agrees on 123.45." and done["failed"] == [] and done["grounded"] is True and done["unsourced"] == []
    assert done["cost"] > 0 and len(done["roles"]) == 4


def test_a_number_the_chair_invents_is_listed_as_unsourced():
    gw = FakeGateway(call("quote", {"symbols": "AAPL"}), text("Price 123.45 [T1]."), text("Up."), text("Quiet."), text("Fair value is 999.99 and price 123.45."))
    ev, _ = run(collect_swarm(gw, results=[ok({"price": 123.45})]))
    assert ev[-1]["unsourced"] == ["999.99"]


def test_no_analyst_used_a_tool_means_the_desk_is_ungrounded():
    gw = FakeGateway(text("a"), text("b"), text("c"), text("d"))
    ev, _ = run(collect_swarm(gw))
    assert ev[-1]["grounded"] is False and ev[-1]["label"] == "UNGROUNDED"


def test_a_failed_role_is_retried_once_and_then_the_run_goes_on():
    gw = FakeGateway(text("fundamental ok"), err(), text("technical ok on retry"), text("risk ok"), text("chair ok"))
    ev, made = run(collect_swarm(gw))
    assert [e["role"] for e in ev if e["type"] == "role_retry"] == ["technical"]
    assert ev[-1]["failed"] == [] and ev[-1]["answer"] == "chair ok"
    assert [m[0] for m in made].count("technical") == 2


def test_a_role_that_fails_twice_is_reported_to_the_chair_and_the_run_still_ends():
    gw = FakeGateway(text("fundamental ok"), err(), err(), text("risk ok"), text("chair knows"))
    ev, _ = run(collect_swarm(gw))
    assert ev[-1]["failed"] == ["technical"] and ev[-1]["answer"] == "chair knows"
    assert [e["type"] for e in ev].count("role_error") == 2
    chair_prompt = gw.calls[-1]["messages"][-1]["content"]
    assert "ROLE FAILED" in chair_prompt and "PROVIDER DOWN" in chair_prompt


def test_an_empty_answer_counts_as_a_failure_and_is_retried():
    gw = FakeGateway(text(""), text(""), text("fundamental on retry"), text("t"), text("r"), text("c"))  # the 2nd "" is the agent's closing call
    ev, _ = run(collect_swarm(gw))
    assert [e["role"] for e in ev if e["type"] == "role_retry"] == ["fundamental"] and ev[-1]["failed"] == []


def test_a_missing_key_stops_the_whole_run_at_once():
    gw = FakeGateway(err("key_required", "KEY REQUIRED: set OPENROUTER in APIKEYS"))
    ev, _ = run(collect_swarm(gw))
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == "key_required" and not any(e["type"] == "swarm_done" for e in ev)
    assert len(gw.calls) == 1


# --- routes: SWARM, stored runs, replay --------------------------------------------------------------------------------------------------
def test_swarm_route_streams_stores_the_run_and_replays_it_without_a_model(client):
    client.app.state.llm = gw = FakeGateway(text("fund 1"), text("tech 2"), text("risk 3"), text("chair 4"))
    ev = sse(client.post("/api/ai/swarm", json={"preset": "committee", "subject": "AAPL"}))
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "swarm_start" and kinds[-1] == "swarm_done" and kinds[-2] == "saved"
    run_id = ev[-2]["run_id"]
    listed = client.get("/api/ai/runs").json()["runs"]
    assert listed[0]["id"] == run_id and listed[0]["kind"] == "swarm" and listed[0]["symbol"] == "AAPL" and listed[0]["title"] == "COMMITTEE AAPL"
    stored = client.get(f"/api/ai/runs/{run_id}").json()
    assert stored["events"][-1]["type"] == "swarm_done" and not any(e["type"] == "token" for e in stored["events"])
    calls = len(gw.calls)
    rep = sse(client.post(f"/api/ai/runs/{run_id}/replay"))
    assert rep[0]["type"] == "replay" and rep[0]["run_id"] == run_id and rep[-1]["type"] == "swarm_done" and rep[-1]["answer"] == "chair 4"
    assert len(gw.calls) == calls  # a replay never calls the model


def test_swarm_route_validates_the_preset_and_subject(client):
    assert client.post("/api/ai/swarm", json={"preset": "nope", "subject": "AAPL"}).status_code == 400
    r = client.post("/api/ai/swarm", json={"preset": "COMMITTEE", "subject": ""})
    assert r.status_code == 400 and "SUBJECT" in r.json()["error"]
    assert client.post("/api/ai/swarm", json={"preset": "COMMITTEE", "subject": "x" * 400}).status_code == 400
    presets = client.get("/api/ai/swarm/presets").json()["presets"]
    assert next(p["code"] for p in presets) == "COMMITTEE"


def test_swarm_without_a_key_says_key_required(client):
    ev = sse(client.post("/api/ai/swarm", json={"preset": "MACRO", "subject": ""}))  # MACRO needs no subject
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == "key_required" and "OPENROUTER" in ev[-1]["text"]


def test_unknown_or_malformed_run_ids_are_not_found(client):
    assert client.get("/api/ai/runs/doesnotexist").status_code == 404
    assert client.get("/api/ai/runs/zzzzzzzzzzzz").status_code == 404
    assert client.post("/api/ai/runs/000000000000/replay").status_code == 404


def test_the_swarm_routes_expose_no_order_surface():
    from openterm.main import app

    paths = [p for p in app.openapi()["paths"] if p.startswith(("/api/ai/", "/api/theses"))]
    assert any(p.endswith("/swarm") for p in paths) and any(p.endswith("/auto") for p in paths)
    assert not any(w in p for p in paths for w in ("order", "kite", "gtt", "margin", "holding"))


# --- AI AUTO ----------------------------------------------------------------------------------------------------------------------------
def test_auto_without_a_backtest_says_so_and_stores_the_run(client):
    client.app.state.llm = FakeGateway(
        [Event("tool_call", id="c1", name="strategy_check", args={"rule": "SMA20 CROSS> SMA50"}), Event("done")], text("I could not run a backtest."))
    ev = sse(client.post("/api/ai/auto", json={"hypothesis": "AAPL trends after a 20/50 cross"}))
    kinds = [e["type"] for e in ev]
    assert kinds[-3:] == ["evidence", "saved", "done"] or kinds[-3:] == ["saved", "evidence", "done"]
    evid = next(e for e in ev if e["type"] == "evidence")
    assert evid["runs"] == [] and evid["tested"] is False and "NO BACKTEST" in evid["note"]
    assert client.get("/api/ai/runs", params={"kind": "auto"}).json()["runs"][0]["title"] == "AAPL trends after a 20/50 cross"


def test_auto_collects_the_run_ids_of_backtests_the_agent_ran():
    from openterm.ai import routes_run

    assert routes_run.RUN_ID_IN_TEXT.findall('{"run_id":"0123456789ab","metrics":{}} {"run_id": "fedcba987654"}') == ["0123456789ab", "fedcba987654"]
    assert routes_run.RUN_ID_IN_TEXT.findall('{"id":"9a81900108345b07","run_id":"9a81900108345b07"}') == ["9a81900108345b07"]  # the real BT id (found by the live smoke)
    assert routes_run.RUN_ID_IN_TEXT.findall('{"run_id":"short"}') == []
    assert "backtest_run" in routes_run.AUTO_TOOLS and "portfolio" not in routes_run.AUTO_TOOLS


def test_auto_validates_the_hypothesis(client):
    assert client.post("/api/ai/auto", json={"hypothesis": "  "}).status_code == 400
    assert client.post("/api/ai/auto", json={}).status_code == 400


# --- THESIS -----------------------------------------------------------------------------------------------------------------------------
def test_thesis_crud_with_status_invalidation_and_linked_runs(client):
    assert client.get("/api/theses").json() == {"theses": []}
    r = client.post("/api/theses", json={"symbol": "aapl", "text": "Services growth carries margins", "invalidation": "Services growth < 8% two quarters running",
                                          "run_ids": ["0123456789ab"]})
    assert r.status_code == 200
    t = r.json()["thesis"]
    assert t["symbol"] == "AAPL" and t["status"] == "open" and t["run_ids"] == ["0123456789ab"] and t["invalidation"].startswith("Services")
    client.post("/api/theses", json={"symbol": "MSFT", "text": "Cloud"})
    assert [x["symbol"] for x in client.get("/api/theses", params={"symbol": "msft"}).json()["theses"]] == ["MSFT"]
    assert len(client.get("/api/theses").json()["theses"]) == 2
    p = client.patch(f"/api/theses/{t['id']}", json={"status": "invalidated", "run_ids": ["0123456789ab", "ba9876543210"]})
    assert p.status_code == 200 and p.json()["thesis"]["status"] == "invalidated" and len(p.json()["thesis"]["run_ids"]) == 2
    assert p.json()["thesis"]["updated_at"] >= t["updated_at"] and p.json()["thesis"]["text"] == t["text"]
    assert client.delete(f"/api/theses/{t['id']}").status_code == 200
    assert client.delete(f"/api/theses/{t['id']}").status_code == 404
    assert client.patch("/api/theses/9999", json={"status": "closed"}).status_code == 404


def test_thesis_input_is_validated(client):
    assert client.post("/api/theses", json={"symbol": "bad symbol!", "text": "x"}).status_code == 400
    assert client.post("/api/theses", json={"symbol": "AAPL", "text": "  "}).status_code == 400
    assert client.post("/api/theses", json={"symbol": "AAPL", "text": "x" * 2001}).status_code == 400
    assert client.post("/api/theses", json={"symbol": "AAPL", "text": "x", "run_ids": ["nope"]}).status_code == 400
    t = client.post("/api/theses", json={"symbol": "AAPL", "text": "x"}).json()["thesis"]
    r = client.patch(f"/api/theses/{t['id']}", json={"status": "great"})
    assert r.status_code == 400 and "STATUS" in r.json()["error"]


def test_store_keeps_events_without_tokens_and_only_the_newest_runs():
    import asyncio

    from openterm.ai.store import KEEP_RUNS, AiStore
    from openterm.db import open_db

    async def go():
        db = await open_db(":memory:")
        st = AiStore(db)
        rid = await st.save_run("swarm", "T", "AAPL", [{"type": "token", "text": "a"}, {"type": "swarm_done", "answer": "b"}])
        assert [e["type"] for e in (await st.run(rid))["events"]] == ["swarm_done"]
        for i in range(KEEP_RUNS + 5):
            await st.save_run("auto", f"r{i}", None, [])
        assert len(await st.runs()) == 50  # the list is capped; the table keeps KEEP_RUNS
        async with db.execute("SELECT COUNT(*) FROM ai_runs") as cur:
            assert (await cur.fetchone())[0] == KEEP_RUNS
        await db.close()

    asyncio.run(go())
