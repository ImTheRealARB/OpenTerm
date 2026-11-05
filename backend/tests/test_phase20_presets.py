"""Phase 20 step 6: the 30 swarm presets ported from Vibe-Trading (HKUDS/Vibe-Trading @ 8172827, MIT) by scripts/port_vibe_presets.py.

Everything here is table-driven over the packaged files in `openterm/ai/presets/`, so a preset added or regenerated is checked with no new test:
every file loads and passes the engine's own validation, names only tools OpenTerm has, never a shell / file / web / order-like tool, has an acyclic
task graph and a source for every variable, and carries an honest coverage label. Each FULL / PARTIAL desk then runs to a chair answer under ONE
generic scripted model (no network, no real LLM, zero spend); an UNAVAILABLE desk refuses with its reason; and the audit ledger records a run of
every desk and verifies. The cut rules themselves are checked on small inputs at the end.
"""

import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from test_phase16_agent import FakeGateway, Tools, sse, text

from openterm.ai import swarm
from openterm.ai import tools as toolbox

PRESET_DIR = Path(swarm.__file__).parent / "presets"
FILES = sorted(PRESET_DIR.glob("*.yaml"))
BUILT_IN = {"COMMITTEE", "RISK", "EARNINGS", "MACRO", "QUANT"}
HEADER_RE = re.compile(r"^# Ported from HKUDS/Vibe-Trading @ 8172827 \(MIT\) agent/src/swarm/presets/(\S+\.yaml)$")
# Tools a desk must never be offered (Phase 20 rules 6 and 8): no shell, no files, no web, no order-like tool.
FORBIDDEN_TOOLS = {"bash", "read_file", "write_file", "edit_file", "web_search", "read_url"}
FORBIDDEN_NAME = re.compile(r"^(order|trade|gtt|margin|kill)")  # a tool NAME starting like this (not the word inside another: "skill")
# Names that exist in Vibe-Trading's tool set but not in OpenTerm's: a ported prompt must not tell the model to call them.
VIBE_ONLY_NAMES = re.compile(
    r"\b(bash|read_file|write_file|edit_file|web_search|read_url|load_skill|get_market_data|get_financial_statements|get_stock_profile|get_stock_news|"
    r"get_options_chain|get_fundamentals|get_fund_flow|get_margin_trading|get_research_reports|options_pricing|options_payoff|factor_analysis|"
    r"financial_rigor|technical_indicators|screen_market|etf_holdings|orderbook_depth|report_audit|analyze_trade_journal|quantlib_call)\b")
VAR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def raw(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parsed(path: Path) -> swarm.Preset:
    return swarm.parse_preset(raw(path), source=path.name)


PRESETS = {p.name: parsed(p) for p in FILES}
RUNNABLE = [p for p in PRESETS.values() if p.coverage != "UNAVAILABLE"]
UNAVAILABLE = [p for p in PRESETS.values() if p.coverage == "UNAVAILABLE"]
ids = lambda ps: [p.code for p in ps]


# --- the set as a whole ----------------------------------------------------------------------------------------------------------------------
def test_there_are_thirty_files_each_with_the_licence_header_naming_its_own_source():
    assert len(FILES) == 30
    for f in FILES:
        first = f.read_text(encoding="utf-8").splitlines()[0]
        m = HEADER_RE.match(first)
        assert m and m.group(1) == f.name, f"{f.name}: the first line must name the source file and commit"
        assert "NOTICE" in f.read_text(encoding="utf-8").splitlines()[1]


def test_preset_codes_follow_the_code_rule_and_are_unique():
    codes = [p.code for p in PRESETS.values()]
    assert len(set(codes)) == 30
    for c in codes:
        assert c == c.upper() and len(c) <= 14 and swarm.CODE_RE.match(c), c
        assert c not in BUILT_IN, f"{c} clashes with a built-in desk"
    assert len({raw(f)["name"] for f in FILES}) == 30  # the Vibe names (the mapping table in docs/PHASE_20_PRESETS.md) are unique too


def test_the_engine_loads_all_thirty_next_to_the_five_built_in_desks_with_no_errors():
    presets, errors = swarm.all_presets()
    assert errors == {}
    assert BUILT_IN <= set(presets) and {p.code for p in PRESETS.values()} <= set(presets) and len(presets) == 35
    rows = {r["code"]: r for r in swarm.listing(presets)}
    for p in PRESETS.values():
        r = rows[p.code]
        assert r["coverage"] == p.coverage and r["kind"] == "dag" and r["limits"] == list(p.limits)
        assert r["estimate"]["in_tokens"] > 0 and r["variables"]


def test_every_label_is_one_of_the_three_and_a_missing_capability_is_always_stated():
    for p in PRESETS.values():
        assert p.coverage in ("FULL", "PARTIAL", "UNAVAILABLE")
        assert (p.coverage == "FULL") == (not p.limits), p.code
        assert all(x.split(":")[0].isupper() for x in p.limits)  # on-screen limits start in capitals, like every other status text


# --- one table row per preset: structure ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", FILES, ids=[f.stem for f in FILES])
def test_the_preset_is_valid_under_the_engines_own_checks(path):
    doc = raw(path)
    p = parsed(path)  # raises PresetError: unknown tool, duplicate id, cycle, undeclared variable in a system prompt, unknown agent
    assert p.tasks and len(p.tasks) == len(p.roles)  # exactly one task per agent
    assert [t.id for layer in swarm.layers(p) for t in layer]  # acyclic: every task lands in a layer
    assert swarm.final_task(p).id in {t.id for t in p.tasks}
    for r in p.roles:
        reads_notes = any(t.input_from for t in p.tasks if t.role == r.id)
        assert (r.tools or reads_notes) and len(r.tools) <= 12 and len(set(r.tools)) == len(r.tools)  # a synthesiser may need no tool of its own
        assert r.max_iterations <= swarm.DESK_ROUNDS and r.timeout_s <= swarm.ROLE_TIMEOUT_S
        assert set(r.tools) <= set(toolbox.REGISTRY)
    assert doc["code"] == p.code and p.title and p.note


@pytest.mark.parametrize("path", FILES, ids=[f.stem for f in FILES])
def test_no_shell_file_web_or_order_like_tool_is_offered_and_no_vibe_only_tool_is_named(path):
    p = parsed(path)
    for r in p.roles:
        assert not set(r.tools) & FORBIDDEN_TOOLS, f"{p.code}/{r.id}"
        for t in r.tools:
            assert not FORBIDDEN_NAME.match(t), f"{p.code}/{r.id}: {t}"
        assert not any(toolbox.REGISTRY[t].doc_only for t in r.tools)
        assert not VIBE_ONLY_NAMES.search(r.system or ""), f"{p.code}/{r.id}: {VIBE_ONLY_NAMES.search(r.system).group(0)}"
    for t in p.tasks:
        assert not VIBE_ONLY_NAMES.search(t.prompt), f"{p.code}/{t.id}: {VIBE_ONLY_NAMES.search(t.prompt).group(0)}"


@pytest.mark.parametrize("path", FILES, ids=[f.stem for f in FILES])
def test_every_variable_has_a_source_and_every_upstream_note_reaches_its_reader(path):
    p = parsed(path)
    declared = {v.name for v in p.variables}
    assert declared and len(declared) == len(p.variables)
    used = set()
    for r in p.roles:
        used |= set(VAR.findall(r.system))
    for t in p.tasks:
        used |= set(VAR.findall(t.prompt))
        assert set(VAR.findall(t.prompt)) <= declared, f"{p.code}/{t.id}: a task prompt uses an undeclared variable"
    assert declared <= used, f"{p.code}: declared but never used: {declared - used}"
    by_role = {r.id: r for r in p.roles}
    for t in p.tasks:
        if t.input_from:  # the notes of earlier roles are placed where the prompt says {upstream_context}
            assert "{upstream_context}" in by_role[t.role].system, f"{p.code}/{t.role} never sees its upstream notes"
            assert {s for _, s in t.input_from} <= set(t.depends_on) | {s for _, s in t.input_from}
    sources = {s for t in p.tasks for _, s in t.input_from}
    assert sources <= {t.id for t in p.tasks}


@pytest.mark.parametrize("path", FILES, ids=[f.stem for f in FILES])
def test_a_role_that_lost_a_capability_says_so_in_its_prompt_and_in_the_limits(path):
    p = parsed(path)
    notes = [r for r in p.roles if "## OpenTerm tool notes" in r.system]
    if p.coverage == "FULL":
        assert not notes
        return
    assert p.limits and notes or any("(task " in x for x in p.limits)
    text_limits = " ".join(p.limits)
    for r in notes:  # every role with a note is named in some limit
        assert r.id in text_limits, f"{p.code}/{r.id}"


# --- one table row per preset: running ---------------------------------------------------------------------------------------------------------
class GenericGateway(FakeGateway):
    """One scripted model for every preset: answers every call with a short note numbered by call, no tool calls, nothing from memory."""

    async def chat(self, messages, model, provider="openrouter", tools=None, max_tokens=1024, temperature=None):
        self.calls.append({"messages": json.loads(json.dumps(messages)), "model": model, "tools": tools})
        for e in text(f"Desk note {len(self.calls)}: the data the tools returned is limited; nothing is quoted from memory.", cost=0.0001):
            yield e


class RoleTools(Tools):
    async def aclose(self):  # swarm.run closes the runner of every role
        pass


def runner_for(role):
    return RoleTools()


def values_for(p):
    return {v.name: f"VALUE_{v.name.upper()}" for v in p.variables}


async def play(p, gw):
    return [e async for e in swarm.run(gw, runner_for, p, "", variables=values_for(p))]


@pytest.mark.parametrize("p", RUNNABLE, ids=ids(RUNNABLE))
def test_a_full_or_partial_desk_runs_to_a_chair_answer_under_the_scripted_model(p):
    gw = GenericGateway()
    ev = asyncio.run(play(p, gw))
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "swarm_start" and kinds[-1] == "swarm_done" and "error" not in kinds and "role_error" not in kinds, kinds
    start, done = ev[0], ev[-1]
    assert start["coverage"] == p.coverage and start["limits"] == list(p.limits) and start["variables"] == values_for(p)
    assert done["coverage"] == p.coverage and done["limits"] == list(p.limits)  # the label travels with the answer
    assert done["answer"].startswith("Desk note") and done["failed"] == [] and done["capped"] is False
    assert kinds.count("role_done") == len(p.roles) == len(gw.calls)  # one round per role, no retries
    assert done["label"] == "UNGROUNDED"  # the scripted model called no tool, so the panel must say so
    systems = [c["messages"][0]["content"] for c in gw.calls]
    users = [c["messages"][1]["content"] for c in gw.calls]
    for s in systems:
        assert "{upstream_context}" not in s and "## OpenTerm rules" in s
        assert not any("{" + v + "}" in s for v in values_for(p))  # every variable was filled in
    assert sum("## Upstream Context" in s for s in systems) == sum(1 for t in p.tasks if t.input_from)
    for t in p.tasks:  # each reader got a labelled section per upstream key
        for key, _ in t.input_from:
            assert any(f"### {key}\n" in s for s in systems), f"{p.code}: section {key} never reached a prompt"
    for name, val in values_for(p).items():
        assert any(val in s or val in u for s, u in zip(systems, users, strict=True)), f"{p.code}: {name} never reached the model"
    offered = {tuple(sorted(t["function"]["name"] for t in c["tools"])) for c in gw.calls}
    assert offered == {tuple(sorted(r.tools)) for r in p.roles}  # a role is offered exactly its own tools, nothing else
    final = swarm.final_task(p)
    assert next(r for r in ev if r["type"] == "role_done" and r["role"] == final.role)["answer"] == done["answer"]


@pytest.mark.parametrize("p", RUNNABLE, ids=ids(RUNNABLE))
def test_the_worst_case_cost_is_known_and_inside_the_default_daily_cap(p):
    est = swarm.estimate(p)
    usd = swarm.usd(est, {"input": 0.2, "output": 0.4})  # the scripted price the route tests use
    assert est["roles"] == len(p.roles) and usd is not None and 0 < usd < 5.0, (p.code, usd)


def test_an_unavailable_desk_refuses_with_its_reason_and_calls_no_model():
    def refuse(p):
        gw = GenericGateway()
        ev = asyncio.run(play(p, gw))
        assert [e["type"] for e in ev] == ["error"] and ev[0]["kind"] == "unavailable" and gw.calls == []
        assert all(x in ev[0]["text"] for x in (p.code, p.limits[0]))

    for p in UNAVAILABLE:  # whichever shipped ports the rules marked UNAVAILABLE (there may be none)
        refuse(p)
    # and always one made on the spot from a shipped desk, so the path is covered even when no port needs it
    doc = raw(FILES[0])
    doc.update(coverage="UNAVAILABLE", limits=["NO TRADE JOURNAL: fills cannot be read, so execution quality is not assessable"])
    refuse(swarm.parse_preset(doc, source="made-up.yaml"))


# --- the audit ledger ------------------------------------------------------------------------------------------------------------------------
def test_a_run_of_every_runnable_desk_is_recorded_in_the_audit_ledger_and_the_chain_verifies(client):
    client.app.state.llm = GenericGateway()
    secret = "XYZ_SECRET_SUBJECT"
    for p in RUNNABLE:
        ev = sse(client.post("/api/ai/swarm", json={"preset": p.code, "variables": {v.name: secret for v in p.variables}}))
        assert ev[0]["type"] == "swarm_start" and ev[-1]["type"] == "swarm_done" and ev[-1]["coverage"] == p.coverage, (p.code, ev[-1])
    entries = client.get("/api/ai/ledger?limit=500").json()["entries"]
    assert len(entries) == len(RUNNABLE)
    by_sha = {e["manifest"]["prompt_sha"]: e for e in entries}
    assert len(by_sha) == len(RUNNABLE)  # every desk has its own prompt hash
    for p in RUNNABLE:
        sha = hashlib.sha256(swarm.prompt_text(p).encode("utf-8")).hexdigest()
        e = by_sha[sha]  # the manifest hashes exactly what shapes this desk's prompts (roles, tasks, variables, limits, tool lists)
        assert e["kind"] == "swarm" and set(e["manifest"]["tools"]) == {t for r in p.roles for t in r.tools}
    assert secret not in json.dumps(entries)  # hashes and metadata only
    v = client.get("/api/ai/ledger/verify").json()
    assert v["ok"] and v["count"] == len(RUNNABLE) and v["head"] == entries[0]["hash"]


def test_the_route_lists_the_ported_desks_with_their_labels_and_refuses_an_unavailable_one(client, tmp_path):
    client.app.state.llm = GenericGateway()
    rows = {r["code"]: r for r in client.get("/api/ai/swarm/presets").json()["presets"]}
    assert set(rows) >= {p.code for p in PRESETS.values()} | BUILT_IN
    assert all(rows[p.code]["coverage"] == p.coverage and rows[p.code]["limits"] == list(p.limits) for p in PRESETS.values())
    assert rows["COMMITTEE"]["coverage"] == "FULL" and rows["COMMITTEE"]["kind"] == "lite"  # the five built-in desks still work as before
    d = tmp_path / "presets"  # a user desk marked UNAVAILABLE is refused by the route before any model call
    d.mkdir(exist_ok=True)
    doc = raw(FILES[0])
    doc.update(code="JOURNALDESK", coverage="UNAVAILABLE", limits=["NO TRADE JOURNAL: fills cannot be read"])
    (d / "journal.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    r = client.post("/api/ai/swarm", json={"preset": "JOURNALDESK", "variables": values_for(parsed(FILES[0]))})
    assert r.status_code == 400 and r.json()["kind"] == "unavailable" and "NO TRADE JOURNAL" in r.json()["error"]
    assert client.app.state.llm.calls == []


# --- the porting script's cut rules, on small inputs ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def port():
    root = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(root))
    try:
        import port_vibe_presets as mod
    finally:
        sys.path.remove(str(root))
    return mod


def clean(port, prompt):
    from collections import Counter

    return port.clean_prompt(prompt, {"risk", "valuation"}, Counter())


def test_a_sentence_that_runs_code_is_cut_with_the_list_it_introduces_and_the_rest_stays(port):
    out, cuts = clean(port, "Compute the VaR.\nFrom bars pulled with `get_market_data`, in `bash`:\n- `src.quantlib.risk.historical_var`\n- `fit_gpd_tail`\n\nName the window.")
    assert "bash" not in out and "src.quantlib" not in out and "fit_gpd_tail" not in out
    assert "Compute the VaR." in out and "Name the window." in out
    assert [c["how"] for c in cuts] == ["cut", "cut (list under a cut sentence)", "cut (list under a cut sentence)"]


def test_a_labelled_output_item_keeps_its_label_and_says_it_is_not_available(port):
    out, cuts = clean(port, "## Outputs\n1. **Risk metrics** — VaR from `src.quantlib.risk` at 95%\n2. **Narrative** — Plain words")
    assert "1. **Risk metrics** (not available here: no code execution" in out and "2. **Narrative** — Plain words" in out
    assert cuts[0]["how"] == "stubbed" and cuts[0]["kinds"] == ["code"]


def test_web_calls_playbook_names_and_tool_names_are_rewritten_by_rule(port):
    out, cuts = clean(port, 'Use the read_url tool for the latest data.\nUse load_skill("risk-analysis") and load_skill("harmonic"); pull bars with get_market_data.\n`backtest` it.')
    assert "read_url" not in out and cuts[0]["kinds"] == ["web"]
    assert 'skill("risk")' in out  # an alias to an installed playbook
    assert 'your own knowledge of "harmonic"' in out  # a playbook OpenTerm does not have
    assert "pull bars with history" in out and "`backtest_run` it." in out


def test_coverage_is_computed_from_what_was_cut(port, tmp_path):
    src = tmp_path / "pairs_research_lab.yaml"
    doc = {"name": "pairs_research_lab", "title": "T", "description": "D", "variables": [{"name": "target", "description": "x", "required": True}],
           "agents": [{"id": "a", "role": "A", "system_prompt": "Study {target}.\nRun it in `bash`.", "tools": ["bash", "get_market_data"], "skills": [],
                       "max_iterations": 50, "timeout_seconds": 1800, "max_retries": 1},
                      {"id": "b", "role": "B", "system_prompt": "Study {target}. {upstream_context}", "tools": ["load_skill"], "skills": [],
                       "max_iterations": 50, "timeout_seconds": 1800, "max_retries": 1}],
           "tasks": [{"id": "t1", "agent_id": "a", "prompt_template": "Go for {target}", "depends_on": []},
                     {"id": "t2", "agent_id": "b", "prompt_template": "Chair {target}", "depends_on": ["t1"], "input_from": {"a_note": "t1"}}]}
    src.write_text(yaml.safe_dump(doc), encoding="utf-8")
    d, info = port.port_one(src, {"risk"})
    assert info["coverage"] == "PARTIAL" and d["limits"][0].startswith("NO CODE EXECUTION") and "(roles: a)" in d["limits"][0]
    assert "quant" in d["agents"][0]["tools"] and "bash" not in d["agents"][0]["tools"] and d["agents"][1]["tools"] == ["skill"]
    doc["agents"][0]["system_prompt"] = "Study {target}."  # nothing cut and nothing missing: FULL
    doc["agents"][0]["tools"] = ["load_skill", "get_market_data"]
    src.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert port.port_one(src, {"risk"})[1]["coverage"] == "FULL"
    doc["agents"][0]["tools"] = ["load_skill"]  # a first role with no data tool at all is blind; half the desk blind = UNAVAILABLE
    src.write_text(yaml.safe_dump(doc), encoding="utf-8")
    d, info = port.port_one(src, {"risk"})
    assert info["coverage"] == "UNAVAILABLE" and any("NO DATA SOURCE" in x for x in d["limits"])
