"""Phase 20 step 5: the SWARM engine upgrade (variables, a DAG of tasks, concurrency 2, a run output cap, user presets, a cost estimate
with a daily-cap check, and an audit manifest that covers the new fields). Models are scripted; nothing touches the network.

A "DAG desk" is a preset loaded from YAML (the Vibe-Trading shape). Here we build them from small Python dicts with `desk_doc()`.
"""

import asyncio
import copy

import pytest
import yaml
from test_phase16_agent import FakeGateway, Tools, run, sse, text

from openterm.ai import swarm


# --- helpers ----------------------------------------------------------------------------------------------------------------------------
def desk_doc(code="MYDESK", **over) -> dict:
    """A 4-agent desk: `a` and `b` have no inputs, `c` reads both, `d` (the final answer) reads `c`. One variable: {target}."""

    def agent(i, extra=""):
        return {"id": i, "role": f"Agent {i}", "tools": ["quote"], "system_prompt": f"You are agent {i} studying {{target}}.{extra}"}

    doc = {
        "code": code, "title": "My desk", "description": "Subject: a ticker.",
        "variables": [{"name": "target", "description": "the ticker"}],
        "agents": [agent("a"), agent("b"), agent("c", "{upstream_context}"), agent("d", "{upstream_context}")],
        "tasks": [
            {"id": "ta", "agent_id": "a", "prompt_template": "Look at {target}"},
            {"id": "tb", "agent_id": "b", "prompt_template": "Look at {target} again"},
            {"id": "tc", "agent_id": "c", "prompt_template": "Combine for {target}", "depends_on": ["ta", "tb"], "input_from": {"a_note": "ta", "b_note": "tb"}},
            {"id": "td", "agent_id": "d", "prompt_template": "Write the answer for {target}", "depends_on": ["tc"], "input_from": {"c_note": "tc"}},
        ],
    }
    doc.update(over)
    return doc


def desk(**over) -> swarm.Preset:
    return swarm.parse_preset(desk_doc(**over), source="test.yaml")


class RoleTools(Tools):
    async def aclose(self):  # swarm.run closes the runner of every role
        pass


def runner_for(role):
    return RoleTools()


async def collect(gw, preset, subject="AAPL", **kw):
    return [e async for e in swarm.run(gw, runner_for, preset, subject, **kw)]


class TrackGateway(FakeGateway):
    """Answers every call with `note N` after a short sleep and records how many calls were in flight at once (the concurrency we really got)."""

    def __init__(self):
        super().__init__()
        self.now = 0
        self.peak = 0

    async def chat(self, messages, model, provider="openrouter", tools=None, max_tokens=1024, temperature=None):
        self.calls.append({"messages": messages, "model": model, "tools": tools})
        self.now += 1
        self.peak = max(self.peak, self.now)
        try:
            await asyncio.sleep(0.05)  # long enough that every task the engine lets start is in here together
        finally:
            self.now -= 1
        for e in text(f"note {len(self.calls)}"):
            yield e


class LowCapGateway(FakeGateway):
    async def spend_status(self):
        return {"today": 4.9999, "cap": 5.0}  # US$0.0001 left of the daily cap


def put_user_preset(tmp_path, name, doc_or_text):
    d = tmp_path / "presets"  # the route reads <folder of the database>/presets
    d.mkdir(exist_ok=True)
    body = doc_or_text if isinstance(doc_or_text, str) else yaml.safe_dump(doc_or_text)
    (d / name).write_text(body, encoding="utf-8")


def script(n=4):
    return [text(f"answer {i}") for i in range(n)]


# --- parsing and the graph --------------------------------------------------------------------------------------------------------------
def test_layers_follow_the_dependencies():
    names = [[t.id for t in layer] for layer in swarm.layers(desk())]
    assert names == [["ta", "tb"], ["tc"], ["td"]]
    assert swarm.final_task(desk()).id == "td"


def test_a_cycle_is_refused_with_the_tasks_in_it():
    doc = desk_doc()
    doc["tasks"][0].update(depends_on=["td"])  # a waits for d, d waits for c, c waits for a
    with pytest.raises(swarm.PresetError, match="CYCLE"):
        swarm.parse_preset(doc, source="cyc.yaml")


def test_an_unknown_dependency_unknown_tool_unknown_agent_and_stray_variable_are_refused():
    doc = desk_doc()
    doc["tasks"][2]["depends_on"] = ["ta", "nope"]
    with pytest.raises(swarm.PresetError, match="UNKNOWN TASK nope"):
        swarm.parse_preset(doc, source="x.yaml")
    doc = desk_doc()
    doc["agents"][0]["tools"] = ["shell_exec"]
    with pytest.raises(swarm.PresetError, match="UNKNOWN TOOL"):
        swarm.parse_preset(doc, source="x.yaml")
    doc = desk_doc()
    doc["tasks"][0]["agent_id"] = "zzz"
    with pytest.raises(swarm.PresetError, match="UNKNOWN AGENT"):
        swarm.parse_preset(doc, source="x.yaml")
    doc = desk_doc()
    doc["agents"][0]["system_prompt"] = "Study {ticker}"  # {ticker} is not declared
    with pytest.raises(swarm.PresetError, match="NO SUCH VARIABLE"):
        swarm.parse_preset(doc, source="x.yaml")


def test_a_partial_or_unavailable_desk_must_say_what_it_cannot_do():
    with pytest.raises(swarm.PresetError, match="limits"):
        swarm.parse_preset(desk_doc(coverage="PARTIAL"), source="x.yaml")
    p = swarm.parse_preset(desk_doc(coverage="PARTIAL", limits=["no live order flow"]), source="x.yaml")
    assert p.coverage == "PARTIAL" and p.limits == ("no live order flow",)
    with pytest.raises(swarm.PresetError, match="coverage"):
        swarm.parse_preset(desk_doc(coverage="MOSTLY"), source="x.yaml")


# --- variables --------------------------------------------------------------------------------------------------------------------------
def test_variables_come_from_pairs_or_the_subject_and_bad_ones_are_refused():
    p = swarm.parse_preset(desk_doc(variables=[{"name": "target"}, {"name": "horizon", "required": False}]), source="x.yaml")
    assert swarm.resolve_variables(p, "AAPL", None) == {"target": "AAPL"}  # the subject fills the first variable
    assert swarm.resolve_variables(p, "", {"target": "MSFT", "horizon": "1Y"}) == {"target": "MSFT", "horizon": "1Y"}
    with pytest.raises(swarm.PresetError, match="MISSING VARIABLE.*target"):
        swarm.resolve_variables(p, "", None)
    with pytest.raises(swarm.PresetError, match="UNKNOWN VARIABLE.*bogus"):
        swarm.resolve_variables(p, "AAPL", {"bogus": "x"})
    # {name} is replaced for known names only: JSON and code in a prompt keep their braces
    assert swarm.render('Study {target} {"k": 1} {other}', {"target": "AAPL"}) == 'Study AAPL {"k": 1} {other}'


def test_run_fills_the_prompts_with_the_variables_and_passes_upstream_notes_on():
    gw = TrackGateway()
    ev = run(collect(gw, desk(), "", variables={"target": "NVDA"}))
    assert ev[0]["variables"] == {"target": "NVDA"} and ev[-1]["type"] == "swarm_done"
    blob = [str(c["messages"]) for c in gw.calls]
    assert all("NVDA" in b for b in blob)
    # the last call is agent d: it must have been given c's note under "Upstream Context"
    assert "Upstream Context" in blob[-1] and "### c_note" in blob[-1]


def test_run_with_a_missing_or_unknown_variable_ends_with_a_bad_request_and_no_model_call():
    gw = FakeGateway()
    ev = run(collect(gw, desk(), "", variables={"bogus": "x"}))
    assert [e["type"] for e in ev] == ["error"] and ev[0]["kind"] == "bad_request" and "UNKNOWN VARIABLE" in ev[0]["text"]
    ev = run(collect(gw, desk(), "", variables=None))
    assert ev[0]["kind"] == "bad_request" and "MISSING VARIABLE" in ev[0]["text"]
    assert gw.calls == []


# --- running the DAG --------------------------------------------------------------------------------------------------------------------
def test_dag_runs_in_dependency_order_and_the_final_task_is_the_answer():
    gw = TrackGateway()
    ev = run(collect(gw, desk()))
    starts = [e["role"] for e in ev if e["type"] == "role_start"]
    assert set(starts[:2]) == {"a", "b"} and starts[2:] == ["c", "d"]  # a and b first (either order), then c, then d
    done = ev[-1]
    assert done["type"] == "swarm_done" and done["failed"] == [] and done["capped"] is False
    assert done["answer"] == "note 4" and len(done["roles"]) == 4  # the answer is the LAST task's (d), not c's


def test_independent_tasks_really_run_two_at_a_time_and_a_lite_desk_one_at_a_time():
    assert swarm.CONCURRENCY == 2
    gw = TrackGateway()
    doc = desk_doc()
    # three independent agents (a, b, c) and a final d: with a limit of 2 the third waits
    doc["tasks"][2] = {"id": "tc", "agent_id": "c", "prompt_template": "Look at {target} too"}
    doc["tasks"][3] = {"id": "td", "agent_id": "d", "prompt_template": "Answer", "depends_on": ["ta", "tb", "tc"], "input_from": {"a": "ta", "b": "tb", "c": "tc"}}
    ev = run(collect(gw, swarm.parse_preset(doc, source="x.yaml")))
    assert ev[-1]["type"] == "swarm_done" and gw.peak == 2
    gw = TrackGateway()
    run(collect(gw, desk(), concurrency=1))
    assert gw.peak == 1
    gw = TrackGateway()
    run(collect(gw, swarm.PRESETS["COMMITTEE"], "AAPL"))
    assert gw.peak == 1  # the built-in desks behave as before: one role at a time


def test_the_output_cap_stops_the_run_and_the_rest_is_skipped():
    gw = FakeGateway(text("big answer"))  # usage says 20 completion tokens
    ev = run(collect(gw, desk(), concurrency=1, out_cap=15))
    done = ev[-1]
    assert done["capped"] is True and done["answer"] == "" and len(gw.calls) == 1  # no second model call
    assert any(e["type"] == "role_error" and e["kind"] == "run_cap" for e in ev)
    assert sorted(done["failed"]) == ["a", "b", "c", "d"]  # a was stopped mid-way, the others never started


def test_a_missing_key_ends_the_dag_run_at_once():
    from openterm.llm.events import Event

    gw = FakeGateway([Event("error", kind="key_required", text="KEY REQUIRED: set OPENROUTER in APIKEYS")])
    ev = run(collect(gw, desk(), concurrency=1))
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == "key_required" and len(gw.calls) == 1


def test_an_unavailable_desk_refuses_with_its_reason():
    p = swarm.parse_preset(desk_doc(coverage="UNAVAILABLE", limits=["needs a tick-level data feed"]), source="x.yaml")
    gw = FakeGateway()
    ev = run(collect(gw, p))
    assert ev == [{"type": "error", "kind": "unavailable", "text": "MYDESK IS UNAVAILABLE: needs a tick-level data feed"}] and gw.calls == []


# --- cost estimate ----------------------------------------------------------------------------------------------------------------------
def test_estimate_is_pessimistic_and_usd_needs_a_known_price():
    est = swarm.estimate(desk())
    assert est["roles"] == 4 and est["in_tokens"] > 0 and est["out_tokens"] > 0
    assert swarm.estimate(desk(), "x" * 300)["in_tokens"] > est["in_tokens"]
    assert swarm.usd(est, {"input": 1.0, "output": 2.0}) == round(est["in_tokens"] / 1e6 + est["out_tokens"] / 1e6 * 2, 4)
    assert swarm.usd(est, None) is None and swarm.usd(est, {"input": None, "output": 1}) is None


def test_packaged_and_builtin_desks_all_have_estimates_and_valid_tools():
    presets, errors = swarm.all_presets(None)
    assert errors == {} and set(swarm.PRESETS) <= set(presets)
    for row in swarm.listing(presets):
        assert row["estimate"]["in_tokens"] > 0 and row["coverage"] in swarm.COVERAGES


# --- user presets -----------------------------------------------------------------------------------------------------------------------
def test_user_presets_load_and_a_bad_file_is_reported_not_executed(tmp_path):
    put_user_preset(tmp_path, "good.yaml", desk_doc("GOODDESK"))
    put_user_preset(tmp_path, "badtool.yaml", {**desk_doc("BADTOOL"), "agents": [{**desk_doc()["agents"][0], "tools": ["shell_exec"]}]})
    put_user_preset(tmp_path, "broken.yaml", "code: [unclosed")
    put_user_preset(tmp_path, "taken.yaml", desk_doc("COMMITTEE"))  # a built-in code cannot be replaced
    marker = tmp_path / "pwned"
    # yaml.safe_load must refuse python tags: if it ever executed this, `marker` would exist
    put_user_preset(tmp_path, "evil.yaml", f"code: EVIL\ntitle: !!python/object/apply:os.mkdir ['{marker.as_posix()}']\n")
    presets, errors = swarm.all_presets(tmp_path / "presets")
    assert "GOODDESK" in presets and presets["GOODDESK"].source == "user:good.yaml"
    assert set(errors) == {"badtool.yaml", "broken.yaml", "taken.yaml", "evil.yaml"}
    assert "UNKNOWN TOOL" in errors["badtool.yaml"] and "ALREADY TAKEN" in errors["taken.yaml"]
    assert not marker.exists()
    assert "COMMITTEE" in presets and presets["COMMITTEE"].source == "built-in"


def test_presets_route_lists_coverage_estimate_usd_variables_and_load_errors(client, tmp_path):
    client.app.state.llm = FakeGateway()
    put_user_preset(tmp_path, "mine.yaml", desk_doc("MYDESK", coverage="PARTIAL", limits=["no intraday data"]))
    put_user_preset(tmp_path, "broken.yaml", "code: [unclosed")
    r = client.get("/api/ai/swarm/presets").json()
    mine = next(p for p in r["presets"] if p["code"] == "MYDESK")
    assert mine["kind"] == "dag" and mine["coverage"] == "PARTIAL" and mine["limits"] == ["no intraday data"]
    assert mine["variables"] == [{"name": "target", "description": "the ticker", "required": True}]
    assert mine["estimate"]["usd"] > 0 and mine["source"] == "user:mine.yaml"
    assert next(p for p in r["presets"] if p["code"] == "COMMITTEE")["kind"] == "lite"
    assert "broken.yaml" in r["errors"] and r["spend"] == {"today": 0.0, "cap": 5.0} and r["model"]


# --- routes: cost cap, force, estimate event, unavailable, variables --------------------------------------------------------------------
def test_route_refuses_a_run_whose_worst_case_is_over_the_daily_cap_and_force_overrides(client, tmp_path):
    client.app.state.llm = gw = LowCapGateway(*script())
    put_user_preset(tmp_path, "mine.yaml", desk_doc())
    r = client.post("/api/ai/swarm", json={"preset": "MYDESK", "subject": "AAPL"})
    assert r.status_code == 402 and r.json()["kind"] == "spend_cap" and "force" in r.json()["error"] and "0.00 LEFT" in r.json()["error"]
    assert gw.calls == []  # refused before any model call
    ev = sse(client.post("/api/ai/swarm", json={"preset": "MYDESK", "subject": "AAPL", "force": True}))
    assert ev[0]["type"] == "swarm_start" and ev[1]["type"] == "estimate" and ev[-1]["type"] == "swarm_done"
    assert ev[1]["usd"] > 0 and ev[1]["cap_left"] < 0.001 and ev[1]["in_tokens"] > 0
    # the built-in desks are checked the same way
    assert client.post("/api/ai/swarm", json={"preset": "COMMITTEE", "subject": "AAPL"}).status_code == 402


def test_route_unavailable_desk_answers_400_with_its_reason(client, tmp_path):
    client.app.state.llm = gw = FakeGateway()
    put_user_preset(tmp_path, "mine.yaml", desk_doc("MYDESK", coverage="UNAVAILABLE", limits=["needs a paid feed"]))
    r = client.post("/api/ai/swarm", json={"preset": "MYDESK", "subject": "AAPL"})
    assert r.status_code == 400 and r.json()["kind"] == "unavailable" and "needs a paid feed" in r.json()["error"] and gw.calls == []


def test_route_takes_variables_and_rejects_bad_ones(client, tmp_path):
    client.app.state.llm = FakeGateway(*script())
    put_user_preset(tmp_path, "mine.yaml", desk_doc())
    ev = sse(client.post("/api/ai/swarm", json={"preset": "mydesk", "variables": {"target": "AAPL"}}))
    assert ev[0]["variables"] == {"target": "AAPL"} and ev[-1]["type"] == "swarm_done"
    ev = sse(client.post("/api/ai/swarm", json={"preset": "MYDESK", "variables": {"nope": "x"}}))
    assert ev[-1]["kind"] == "bad_request" and "UNKNOWN VARIABLE" in ev[-1]["text"]
    assert client.post("/api/ai/swarm", json={"preset": "MYDESK", "variables": {"target": 5}}).status_code == 400  # values must be strings
    assert client.post("/api/ai/swarm", json={"preset": "MYDESK", "variables": ["AAPL"]}).status_code == 400
    assert client.post("/api/ai/swarm", json={"preset": "MYDESK"}).status_code == 400  # a desk with variables needs a subject or variables


def test_a_stored_dag_run_replays_equal_with_no_model_call(client, tmp_path):
    client.app.state.llm = gw = FakeGateway(*script())
    put_user_preset(tmp_path, "mine.yaml", desk_doc())
    ev = sse(client.post("/api/ai/swarm", json={"preset": "MYDESK", "subject": "AAPL"}))
    saved = next(e for e in ev if e["type"] == "saved")
    calls = len(gw.calls)
    rep = sse(client.post(f"/api/ai/runs/{saved['run_id']}/replay"))
    assert rep[0]["type"] == "replay" and rep[0]["run_id"] == saved["run_id"]
    # what was streamed (minus tokens, which are not stored, and the `saved` marker) is exactly what is replayed, estimate event included
    assert rep[1:] == [e for e in ev if e["type"] not in ("token", "saved")]
    assert any(e["type"] == "estimate" for e in rep) and len(gw.calls) == calls


# --- audit ------------------------------------------------------------------------------------------------------------------------------
def test_prompt_text_changes_when_any_prompt_task_variable_tool_or_limit_changes():
    base = swarm.prompt_text(desk())
    assert swarm.prompt_text(desk()) == base

    def changed(mutate) -> bool:
        doc = desk_doc()
        mutate(doc)
        return swarm.prompt_text(swarm.parse_preset(doc, source="x.yaml")) != base

    assert changed(lambda d: d["agents"][0].update(system_prompt="You are agent a, new words {target}."))
    assert changed(lambda d: d["tasks"][0].update(prompt_template="Look closer at {target}"))
    assert changed(lambda d: d["tasks"][3].update(input_from={"c_note": "tc", "extra": "ta"}))
    assert changed(lambda d: d["tasks"][3].update(depends_on=["tc", "ta"]))
    assert changed(lambda d: d["variables"][0].update(description="a different description"))
    assert changed(lambda d: d["agents"][1].update(tools=["quote", "history"]))
    assert changed(lambda d: d.update(coverage="PARTIAL", limits=["x"]))
    assert changed(lambda d: d["agents"][0].update(max_iterations=3))
    # the shared rules text is part of it too
    old = swarm.DESK_RULES
    try:
        swarm.DESK_RULES = old + "\n- extra rule"
        assert swarm.prompt_text(desk()) != base
    finally:
        swarm.DESK_RULES = old


def test_the_ledger_hash_changes_with_the_prompt_and_with_the_variables_of_a_run(client, tmp_path):
    client.app.state.llm = FakeGateway(*script(12))
    doc = desk_doc()
    put_user_preset(tmp_path, "mine.yaml", doc)

    def run_once(**body):
        sse(client.post("/api/ai/swarm", json={"preset": "MYDESK", **body}))
        return client.get("/api/ai/ledger").json()["entries"][0]  # newest first

    a = run_once(variables={"target": "AAPL"})
    b = run_once(variables={"target": "MSFT"})  # same desk, other variable: the question hash must differ, the manifest must not
    assert a["meta"]["question_sha"] != b["meta"]["question_sha"]
    assert a["manifest"]["prompt_sha"] == b["manifest"]["prompt_sha"] and a["seq"] != b["seq"]
    doc2 = copy.deepcopy(doc)
    doc2["agents"][3]["system_prompt"] += " Be brief."
    put_user_preset(tmp_path, "mine.yaml", doc2)  # edit the desk's prompt
    c = run_once(variables={"target": "AAPL"})
    assert c["manifest"]["prompt_sha"] != a["manifest"]["prompt_sha"]
    assert c["meta"]["question_sha"] == a["meta"]["question_sha"]  # the same question as the first run
    assert set(c["manifest"]["tools"]) == {"quote"} and client.get("/api/ai/ledger/verify").json()["ok"] is True
