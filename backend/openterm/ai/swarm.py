"""SWARM: preset multi-agent runs. A DAG of roles over the same agent loop; each role has its own tool allow-list and prompt.

Two kinds of preset share one engine:
  * LITE desks (the five built-in ones below): analysts run first, in order, then the chair writes the synthesis from their notes.
    They behave exactly as they did before Phase 20 (one role at a time, same prompts).
  * DAG desks (Vibe-Trading shape, Phase 20): `variables` filled from the user's prompt, `tasks` with `depends_on` / `input_from`, run in
    topological order, up to `CONCURRENCY` independent tasks at once. A user can add their own in `<data dir>/presets/*.yaml`; the file is
    parsed with `yaml.safe_load` and checked, never executed.
A role that errors, times out or returns nothing is retried once; if it still fails, the roles that depend on it are told which role failed
and why. A missing key stops the whole run. A run also stops at its output-token cap. Events are the agent's events with a `role` field plus
`swarm_start`, `role_start`, `role_retry`, `role_done`, `role_error` and `swarm_done`. Numbers in the final answer are checked against the
notes it was written from (a check, not a proof); each role's own numbers are checked against its tool results.
Cost is estimated before a run (`estimate`) from the worst case: every round used, every tool result at its size cap.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from . import agent, ground
from . import tools as toolbox

MAX_RETRIES = 1
FATAL_KINDS = ("key_required", "invalid", "spend_cap", "price_unknown")  # every role would hit the same wall: no retry, stop the run
ROLE_ROUNDS = 5  # LITE desks (unchanged)
ROLE_CALLS = 10
DESK_ROUNDS = 8  # DAG desks: Vibe's default of 50 would cost ten times more for the same answer
DESK_CALLS = 16
ROLE_TIMEOUT_S = 120.0
CONCURRENCY = 2  # independent tasks at once; token cost is the same, wall time is shorter
RUN_OUTPUT_CAP = 40_000  # completion tokens for a whole run; the run stops when it is passed
ROLE_MAX_TOKENS = 900
TOOL_RESULT_TOKENS = 1_500  # the size cap of one tool result, in tokens (context.RESULT_LIMIT characters)

COMMON = """You are one role in an OpenTerm research desk. Today is {today}. Your role: {title}. {brief}
Rules:
- Get every market figure from a tool. Never answer a price, ratio, date or statistic from memory; if no tool can supply it, say so.
- Tool calls are numbered in the order you make them: the first is [T1], the second [T2]. Cite the call after each figure, like "343.46 [T1]".
- Report failed, stale or empty data plainly. Do not repeat a failed call unchanged. You can only read data: there are no order or trading tools.
- Historical backtests are simulations, not forecasts. Analysis only, not personalised investment advice.
- Write a short note (at most 8 lines, plain text, no tables) for the chair of the desk."""

CHAIR = """You are the chair of an OpenTerm research desk. Today is {today}. {brief}
You get the notes of your analysts below the question. Write the desk's answer: where they agree, where they disagree, what is missing or failed, and what
would change the view. Use only facts and figures that appear in the notes (or that you fetch with a tool); quote them as written. Say which analyst a claim
comes from. If a role failed, say so. Analysis only, not personalised investment advice. Plain text, at most 14 lines, no tables."""

# Appended to every DAG role's own prompt (which is a ported Vibe prompt): OpenTerm's rules win over anything the prompt says.
DESK_RULES = """

## OpenTerm rules (these override anything above)
- Today is {today}. You can only call the tools listed for you; there is no shell, no file access and no web access. If the text above asks for one, say that
  capability is missing and work from the tools you have. Do not invent output from a tool you cannot call.
- Every figure comes from a tool result or from the upstream context above. Tool calls are numbered [T1], [T2] in the order you make them: cite them after
  each figure. If you cannot source a number, leave it out and say so.
- Report failed, stale or empty data plainly. Historical backtests are simulations, not forecasts. Analysis only: there are no order tools and no personal advice.
- Be concise: plain text, no tables, at most 14 lines unless the instructions above ask for less."""


class PresetError(ValueError):
    """A preset is malformed (bad YAML shape, unknown tool, cycle, missing variable). The message says what and where."""


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    brief: str
    tools: tuple[str, ...]
    chair: bool = False
    system: str | None = None  # a DAG role's own system prompt (with {variables} and {upstream_context}); None = the LITE templates
    max_iterations: int = ROLE_ROUNDS
    timeout_s: float = ROLE_TIMEOUT_S


@dataclass(frozen=True)
class Task:
    id: str
    role: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    input_from: tuple[tuple[str, str], ...] = ()  # (key, source task id)


@dataclass(frozen=True)
class Variable:
    name: str
    description: str = ""
    required: bool = True


@dataclass(frozen=True)
class Preset:
    code: str
    title: str
    roles: tuple[Role, ...]
    note: str = ""
    needs_subject: bool = True
    tags: tuple[str, ...] = field(default=())
    tasks: tuple[Task, ...] = ()  # empty = a LITE desk (analysts, then the chair)
    variables: tuple[Variable, ...] = ()
    coverage: str = "FULL"  # FULL | PARTIAL | UNAVAILABLE
    limits: tuple[str, ...] = ()  # what a PARTIAL / UNAVAILABLE desk cannot do, shown on screen
    source: str = "built-in"


def _chair(brief: str, tools: tuple[str, ...] = ("quote",)) -> Role:
    return Role("chair", "Chair", brief, tools, chair=True)


PRESETS: dict[str, Preset] = {p.code: p for p in [
    Preset("COMMITTEE", "Investment committee", (
        Role("fundamental", "Fundamental analyst", "Value the business: size, growth, margins, balance sheet, the profile.", ("quote", "profile", "fa", "research", "skill", "skills")),
        Role("technical", "Technical analyst", "Describe the price trend, range and (if listed) options positioning.", ("history", "quote", "options_chain")),
        Role("risk", "Risk analyst", "Find what could go wrong: news, filings, drawdowns.", ("news", "filings", "history")),
        _chair("Give the committee's view on the subject: a balanced case, not a recommendation to trade.")), "Subject: one ticker, e.g. AAPL."),
    Preset("RISK", "Risk committee", (
        Role("exposure", "Exposure analyst", "Read the user's portfolios and say what is held and how it is concentrated.", ("portfolio", "quote")),
        Role("var", "Risk-model analyst", "Run the risk analytics (VaR, drawdown) for the named portfolio.", ("quant", "portfolio")),
        Role("headlines", "News analyst", "Find news relevant to the largest positions.", ("news", "portfolio")),
        _chair("Summarise the portfolio's risk: concentration, VaR and drawdown, and headline risks.")), "Subject: a portfolio name, e.g. MAIN."),
    Preset("EARNINGS", "Earnings desk", (
        Role("estimates", "Estimates analyst", "Report earnings estimates, revisions and the last results.", ("research", "quote", "skill", "skills")),
        Role("reports", "Filings analyst", "Read the latest filings and statements for what changed.", ("filings", "fa", "news")),
        _chair("Say what to watch at the next earnings report and how the estimates compare with the filed numbers.")), "Subject: one ticker."),
    Preset("MACRO", "Macro desk", (
        Role("rates", "Rates analyst", "Describe the yield curve and what it implies.", ("rates", "macro", "skill", "skills")),
        Role("series", "Economic-data analyst", "Find the macro series relevant to the question.", ("macro", "news")),
        _chair("Summarise the macro picture and the main uncertainties.")), "Subject: a theme, e.g. INFLATION.", needs_subject=False),
    Preset("QUANT", "Quant desk", (
        Role("trend", "Trend analyst", "Describe the price history of the subject (returns, volatility, range).", ("history", "quote")),
        Role("tester", "Backtest analyst", "Test one simple rule on the subject with backtest_run (validate it with strategy_check first) and report the metrics.",
             ("history", "strategy_check", "backtest_run", "skill", "skills")),
        _chair("Summarise the evidence. A backtest is a historical simulation, not a forecast.")), "Subject: a ticker."),
]}


# ---------------------------------------------------------------- loading presets from YAML (Vibe shape)
_VAR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,13}\Z")
COVERAGES = ("FULL", "PARTIAL", "UNAVAILABLE")


def _need(d: dict, key: str, where: str, kind: type = str):
    v = d.get(key)
    if not isinstance(v, kind) or (kind is str and not v.strip()):
        raise PresetError(f"{where}: `{key}` MUST BE A NON-EMPTY {kind.__name__.upper()}")
    return v


def parse_preset(doc: dict, *, source: str, known_tools: set[str] | None = None) -> Preset:
    """Builds a Preset from a parsed YAML document and checks it: tools exist, the graph is acyclic, every variable has a source."""
    if not isinstance(doc, dict):
        raise PresetError(f"{source}: A PRESET FILE MUST BE A MAPPING")
    known = (set(toolbox.REGISTRY) | {toolbox.EXTERNAL_ALL}) if known_tools is None else known_tools  # `external` = the user's enabled third-party MCP tools
    code = _need(doc, "code", source).upper()
    if not CODE_RE.match(code):
        raise PresetError(f"{source}: CODE {code!r} MUST BE 2-14 CHARACTERS: A-Z, 0-9, _")
    coverage = str(doc.get("coverage") or "FULL").upper()
    if coverage not in COVERAGES:
        raise PresetError(f"{source}: coverage MUST BE ONE OF {', '.join(COVERAGES)}")
    limits = tuple(str(x) for x in (doc.get("limits") or []))
    if coverage != "FULL" and not limits:
        raise PresetError(f"{source}: A {coverage} PRESET MUST SAY WHAT IT CANNOT DO (limits)")
    variables = tuple(Variable(_need(v, "name", f"{source} variables"), str(v.get("description") or ""), bool(v.get("required", True)))
                      for v in (doc.get("variables") or []))
    roles = []
    for a in _need(doc, "agents", source, list):
        rid = _need(a, "id", f"{source} agent")
        tools = tuple(a.get("tools") or [])
        if bad := [t for t in tools if t not in known]:
            raise PresetError(f"{source}: ROLE {rid} NAMES UNKNOWN TOOL(S) {', '.join(bad)}")
        roles.append(Role(rid, str(a.get("role") or rid), "", tools, system=_need(a, "system_prompt", f"{source} agent {rid}"),
                          max_iterations=min(int(a.get("max_iterations") or DESK_ROUNDS), DESK_ROUNDS),
                          timeout_s=min(float(a.get("timeout_seconds") or ROLE_TIMEOUT_S), ROLE_TIMEOUT_S)))
    ids = [r.id for r in roles]
    if len(set(ids)) != len(ids):
        raise PresetError(f"{source}: DUPLICATE AGENT IDS")
    tasks = []
    for t in _need(doc, "tasks", source, list):
        tid = _need(t, "id", f"{source} task")
        if _need(t, "agent_id", f"{source} task {tid}") not in ids:
            raise PresetError(f"{source}: TASK {tid} USES UNKNOWN AGENT {t['agent_id']}")
        tasks.append(Task(tid, t["agent_id"], _need(t, "prompt_template", f"{source} task {tid}"), tuple(t.get("depends_on") or ()),
                          tuple((str(k), str(v)) for k, v in (t.get("input_from") or {}).items())))
    if len({t.role for t in tasks}) != len(tasks):
        raise PresetError(f"{source}: EACH AGENT MUST HAVE EXACTLY ONE TASK")
    preset = Preset(code, _need(doc, "title", source), tuple(roles), str(doc.get("description") or ""), needs_subject=bool(variables),
                    tasks=tuple(tasks), variables=variables, coverage=coverage, limits=limits, source=source)
    layers(preset)  # raises on unknown task ids and cycles
    declared = {v.name for v in variables}
    for r in roles:
        stray = set(_VAR.findall(r.system or "")) - declared - {"upstream_context"}
        if stray:
            raise PresetError(f"{source}: ROLE {r.id} USES {{{', '.join(sorted(stray))}}} BUT NO SUCH VARIABLE IS DECLARED")
    return preset


def load_dir(path: Path, *, source_prefix: str = "") -> tuple[dict[str, Preset], dict[str, str]]:
    """Loads every *.yaml in `path`. Returns (presets by code, errors by file name): one bad file never hides the others."""
    import yaml

    out: dict[str, Preset] = {}
    errors: dict[str, str] = {}
    if not path.is_dir():
        return out, errors
    for f in sorted(path.glob("*.yaml")):
        try:
            p = parse_preset(yaml.safe_load(f.read_text(encoding="utf-8")), source=f"{source_prefix}{f.name}")
            if p.code in PRESETS or p.code in out:
                raise PresetError(f"{f.name}: CODE {p.code} IS ALREADY TAKEN")
            out[p.code] = p
        except (PresetError, yaml.YAMLError, OSError, ValueError, TypeError, KeyError) as e:
            errors[f.name] = str(e)[:300]
    return out, errors


# ---------------------------------------------------------------- the graph
def layers(preset: Preset) -> list[list[Task]]:
    """Tasks grouped by depth: every task in a layer depends only on earlier layers. Raises PresetError on an unknown id or a cycle."""
    by_id = {t.id: t for t in preset.tasks}
    for t in preset.tasks:
        for dep in (*t.depends_on, *(s for _, s in t.input_from)):
            if dep not in by_id:
                raise PresetError(f"TASK {t.id} DEPENDS ON UNKNOWN TASK {dep}")
    done: set[str] = set()
    out: list[list[Task]] = []
    left = list(preset.tasks)
    while left:
        ready = [t for t in left if all(d in done for d in (*t.depends_on, *(s for _, s in t.input_from)))]
        if not ready:
            raise PresetError(f"THE TASKS FORM A CYCLE: {', '.join(t.id for t in left)}")
        out.append(ready)
        done |= {t.id for t in ready}
        left = [t for t in left if t.id not in done]
    return out


def effective_tasks(preset: Preset) -> list[Task]:
    """A LITE desk's tasks: analysts with no dependencies, then the chair depending on all of them (and reading their notes)."""
    if preset.tasks:
        return list(preset.tasks)
    analysts = [r for r in preset.roles if not r.chair]
    tasks = [Task(r.id, r.id, "") for r in analysts]
    tasks += [Task(r.id, r.id, "", tuple(a.id for a in analysts), tuple((a.id, a.id) for a in analysts)) for r in preset.roles if r.chair]
    return tasks


def final_task(preset: Preset) -> Task:
    """The task whose answer is the desk's answer: the last one nobody depends on."""
    tasks = effective_tasks(preset)
    needed = {d for t in tasks for d in (*t.depends_on, *(s for _, s in t.input_from))}
    sinks = [t for t in tasks if t.id not in needed]
    return sinks[-1]


# ---------------------------------------------------------------- variables and text
def resolve_variables(preset: Preset, subject: str, given: dict[str, str] | None) -> dict[str, str]:
    """Fills the preset's variables from `KEY=value` pairs, else the first required one from the subject text. Raises PresetError."""
    values = {str(k): str(v) for k, v in (given or {}).items() if v not in (None, "")}
    unknown = set(values) - {v.name for v in preset.variables}
    if unknown and preset.variables:
        raise PresetError(f"UNKNOWN VARIABLE(S) {', '.join(sorted(unknown))}: THIS DESK TAKES {', '.join(v.name for v in preset.variables)}")
    if preset.variables and subject.strip():
        first = next((v.name for v in preset.variables if v.name not in values), None)
        if first and first not in values:
            values[first] = subject.strip()
    missing = [v.name for v in preset.variables if v.required and v.name not in values]
    if missing:
        raise PresetError(f"MISSING VARIABLE(S) {', '.join(missing)}: ADD {missing[0]}=... (THIS DESK TAKES {', '.join(v.name for v in preset.variables)})")
    return values


def render(text: str, values: dict[str, str]) -> str:
    """Replaces {name} for the names we know and leaves every other brace alone (prompts contain code and JSON with braces)."""
    return _VAR.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def upstream_block(parts: list[tuple[str, str]]) -> str:
    return "" if not parts else "## Upstream Context (from previous agents)\n\n" + "\n\n".join(f"### {k}\n{v}" for k, v in parts)


def listing(presets: dict[str, Preset] | None = None) -> list[dict]:
    return [{"code": p.code, "title": p.title, "roles": [{"id": r.id, "title": r.title, "tools": list(r.tools)} for r in p.roles], "note": p.note,
             "needs_subject": p.needs_subject, "coverage": p.coverage, "limits": list(p.limits), "kind": "dag" if p.tasks else "lite",
             "variables": [{"name": v.name, "description": v.description, "required": v.required} for v in p.variables], "source": p.source,
             "estimate": estimate(p)} for p in (presets or PRESETS).values()]


def prompt_text(preset: Preset) -> str:
    """Everything that shapes the prompts of a preset (templates, role ids, briefs, system prompts, tasks, variables, limits, tool lists):
    hashed into the audit manifest, so changing any of it changes the manifest."""
    roles = [[r.id, r.title, r.brief, list(r.tools), r.chair, r.system, r.max_iterations, r.timeout_s] for r in preset.roles]
    tasks = [[t.id, t.role, t.prompt, list(t.depends_on), [list(x) for x in t.input_from]] for t in preset.tasks]
    variables = [[v.name, v.description, v.required] for v in preset.variables]
    return "\n".join([COMMON, CHAIR, DESK_RULES, preset.code, preset.coverage, repr(list(preset.limits)), repr(roles), repr(tasks), repr(variables)])


def role_system(role: Role, today: str) -> str:
    return (CHAIR if role.chair else COMMON).format(today=today, title=role.title, brief=role.brief)


def role_question(role: Role, subject: str, notes: list[tuple[Role, str]]) -> str:
    base = f"Subject: {subject}" if subject else "No specific subject was given: use the general picture."
    if not role.chair:
        return base
    body = "\n\n".join(f"## {r.title} ({r.id})\n{text}" for r, text in notes)
    return f"{base}\n\nAnalyst notes:\n{body}"


# ---------------------------------------------------------------- cost
def estimate(preset: Preset, subject: str = "") -> dict:
    """Worst-case tokens for a run: every role uses all its rounds, and every round adds a full-size tool result to what is re-sent.

    Deliberately pessimistic (real runs end far sooner); its purpose is to refuse a run that COULD cost more than the daily cap allows.
    `in_tokens` is what the model reads in total, `out_tokens` what it writes. Multiply by the model's price for dollars (see `usd`)."""
    n_in = n_out = 0
    for r in preset.roles:
        rounds = r.max_iterations if r.system is not None else ROLE_ROUNDS
        calls = DESK_CALLS if r.system is not None else ROLE_CALLS
        base = ((len(r.system or "") + len(r.brief) + len(COMMON) + len(subject)) // 4) + 400  # prompt, rules, tool schemas
        if r.chair or any(t.input_from for t in preset.tasks if t.role == r.id):
            base += TOOL_RESULT_TOKENS  # upstream notes
        for i in range(rounds):  # round i re-reads the prompt plus everything fetched so far
            fetched = min(i, calls) * TOOL_RESULT_TOKENS
            n_in += base + fetched + i * ROLE_MAX_TOKENS
            n_out += ROLE_MAX_TOKENS
    retries = 1 + MAX_RETRIES  # one retry per role is possible: the worst case pays twice
    return {"roles": len(preset.roles), "in_tokens": n_in * retries, "out_tokens": min(n_out * retries, RUN_OUTPUT_CAP * 4)}


def usd(est: dict, price: dict | None) -> float | None:
    """Dollars for an `estimate` at a model price ({"input": usd per million, "output": usd per million}); None when the price is unknown."""
    if not price or price.get("input") is None or price.get("output") is None:
        return None
    return round(est["in_tokens"] / 1e6 * price["input"] + est["out_tokens"] / 1e6 * price["output"], 4)


PACKAGED_DIR = Path(__file__).parent / "presets"  # the ported desks, shipped with OpenTerm
_packaged: tuple[dict[str, Preset], dict[str, str]] | None = None


def all_presets(user_dir: Path | None = None) -> tuple[dict[str, Preset], dict[str, str]]:
    """Every preset available now: built-in LITE desks, the packaged ports, then the user's own (`<data dir>/presets/*.yaml`).

    Returns (presets by code, load errors by file). A broken file is reported, never silently skipped, and never hides the others.
    The packaged directory is read once per process; the user's directory on every call, so a new file shows up without a restart."""
    global _packaged
    if _packaged is None:
        _packaged = load_dir(PACKAGED_DIR)
    presets = {**PRESETS, **_packaged[0]}
    errors = dict(_packaged[1])
    if user_dir is not None:
        mine, bad = load_dir(user_dir, source_prefix="user:")
        for code in list(mine):
            if code in presets:
                bad[f"{mine[code].source}"] = f"CODE {code} IS ALREADY TAKEN"
                del mine[code]
        presets.update(mine)
        errors.update(bad)
    return presets, errors


RunnerFor = Callable[[Role], toolbox.ToolRunner]


class _State:
    """What the concurrent role runners share: the money spent, the tokens written, the stop flag and each task's result."""

    def __init__(self):
        self.cost = 0.0
        self.out_tokens = 0
        self.stop: str | None = None  # a reason the whole run must end (fatal gateway error, output cap)
        self.summaries: dict[str, str] = {}
        self.outcomes: list[dict] = []
        self.notes: list[tuple[Role, str]] = []
        self.final: dict | None = None
        self.fatal_error: dict | None = None  # an error that ends the run before anything was kept


async def _run_task(gateway, runner_for, preset: Preset, role: Role, task: Task, subject: str, values: dict[str, str], today: str,
                    st: _State, emit, model: str, provider: str, out_cap: int) -> None:
    """One role, with its retry. Pushes events through `emit`; records the outcome and summary on `st`."""
    lite = role.system is None
    upstream = [(k, st.summaries[s]) for k, s in task.input_from if s in st.summaries]
    if lite:
        system, question = role_system(role, today), role_question(role, subject, st.notes)
        rounds, calls = ROLE_ROUNDS, ROLE_CALLS
    else:
        system = render(role.system, values).replace("{upstream_context}", upstream_block(upstream)) + DESK_RULES.format(today=today)
        question = render(task.prompt, values)
        rounds, calls = role.max_iterations, DESK_CALLS
    tries, done, failure = 0, None, ""
    while tries <= MAX_RETRIES and done is None and not st.stop:
        tries += 1
        if tries > 1:
            await emit({"type": "role_retry", "role": role.id, "attempt": tries, "why": failure})
        await emit({"type": "role_start", "role": role.id, "title": role.title, "tools": list(role.tools), "attempt": tries, "task": task.id})
        runner = runner_for(role)
        events = agent.run(gateway, runner, question, [], model=model, provider=provider, tools=list(role.tools), system=system,
                           max_rounds=rounds, max_calls=calls, max_tokens=ROLE_MAX_TOKENS)
        failure = ""
        try:
            async with asyncio.timeout(role.timeout_s):
                async for ev in events:
                    if ev["type"] == "start":
                        continue
                    if ev["type"] == "error":
                        failure = f"{ev['kind']}: {ev['text']}"
                        if ev["kind"] in FATAL_KINDS:  # no retry, nothing else can run either
                            if not any(o["ok"] for o in st.outcomes):  # nothing to keep: end the run with the error
                                st.fatal_error = {"type": "error", "kind": ev["kind"], "text": ev["text"]}
                            st.stop = f"{ev['kind']}"
                        await emit({"type": "role_error", "role": role.id, "kind": ev["kind"], "text": ev["text"]})
                        break
                    if ev["type"] == "done":
                        if not ev["answer"].strip():
                            failure = "THE MODEL RETURNED NO ANSWER"
                            await emit({"type": "role_error", "role": role.id, "kind": "empty", "text": failure})
                        else:
                            done = ev
                        continue
                    if ev["type"] == "usage":  # counted here, so an attempt that failed after it was paid for still shows in the total
                        st.cost += ev.get("cost") or 0.0
                        st.out_tokens += ev.get("completion_tokens") or 0
                        if st.out_tokens > out_cap and not st.stop:
                            st.stop = "run_cap"
                            failure = f"RUN OUTPUT CAP: {st.out_tokens} TOKENS WRITTEN (CAP {out_cap})"
                            await emit({"type": "role_error", "role": role.id, "kind": "run_cap", "text": failure})
                            await emit({**ev, "role": role.id})
                            break
                    await emit({**ev, "role": role.id})
        except TimeoutError:
            failure = f"TIMEOUT: THE ROLE RAN OVER {role.timeout_s:.0f} s"
            await emit({"type": "role_error", "role": role.id, "kind": "timeout", "text": failure})
        finally:
            await events.aclose()
            await runner.aclose()
    if done is None:
        st.outcomes.append({"role": role.id, "ok": False, "why": failure or "SKIPPED", "cost": 0.0})
        st.summaries[task.id] = f"ROLE FAILED: {failure or 'THE RUN WAS STOPPED BEFORE THIS ROLE'}"
        st.notes.append((role, st.summaries[task.id]))
        return
    is_final = task.id == final_task(preset).id
    if is_final:
        sources = [t for _, t in st.notes if not t.startswith("ROLE FAILED")]
        grounded = any(o.get("grounded") for o in st.outcomes if o["ok"])
        done = {**done, "unsourced": ground.check(done["answer"], sources) if sources else [], "grounded": grounded, "label": None if grounded else "UNGROUNDED"}
        st.final = done
    else:
        st.notes.append((role, done["answer"]))
    st.summaries[task.id] = done["answer"]
    st.outcomes.append({"role": role.id, "ok": True, "grounded": done["grounded"], "unsourced": done["unsourced"], "tool_calls": done["tool_calls"],
                        "cost": done["cost"], "stopped": done["stopped"],
                        **({"web": done["web"]} if done.get("web") else {})})
    await emit({**done, "type": "role_done", "role": role.id})


async def run(gateway, runner_for: RunnerFor, preset: Preset, subject: str, *, model: str = agent.DEFAULT_MODEL, provider: str = "openrouter",
              variables: dict[str, str] | None = None, concurrency: int | None = None, out_cap: int = RUN_OUTPUT_CAP) -> AsyncIterator[dict]:
    if preset.coverage == "UNAVAILABLE":
        yield {"type": "error", "kind": "unavailable", "text": f"{preset.code} IS UNAVAILABLE: {'; '.join(preset.limits)}"}
        return
    try:
        values = resolve_variables(preset, subject, variables)
        plan = layers_of(preset)
    except PresetError as e:
        yield {"type": "error", "kind": "bad_request", "text": str(e)}
        return
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    roles = {r.id: r for r in preset.roles}
    yield {"type": "swarm_start", "preset": preset.code, "title": preset.title, "subject": subject, "model": model, "provider": provider,
           "started": datetime.now(UTC).isoformat(timespec="seconds"), "roles": [{"id": r.id, "title": r.title, "tools": list(r.tools)} for r in preset.roles],
           "coverage": preset.coverage, "limits": list(preset.limits), "variables": values}
    limit = concurrency if concurrency is not None else (CONCURRENCY if preset.tasks else 1)  # LITE desks stay one-at-a-time
    st = _State()
    queue: asyncio.Queue = asyncio.Queue()
    sem = asyncio.Semaphore(max(1, limit))

    async def emit(ev: dict) -> None:
        await queue.put(ev)

    async def guarded(task: Task) -> None:
        async with sem:
            if st.stop:
                st.outcomes.append({"role": task.role, "ok": False, "why": "SKIPPED", "cost": 0.0})
                st.summaries[task.id] = "ROLE FAILED: THE RUN WAS STOPPED BEFORE THIS ROLE"
                return
            await _run_task(gateway, runner_for, preset, roles[task.role], task, subject, values, today, st, emit, model, provider, out_cap)

    for layer in plan:
        workers = [asyncio.create_task(guarded(t)) for t in layer]
        try:
            pending = set(workers)
            while pending or not queue.empty():
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    pending = {w for w in pending if not w.done()}
            for w in workers:
                w.result()  # a crashed role runner raises here instead of vanishing
        finally:
            for w in workers:
                w.cancel()
        if st.fatal_error:
            yield st.fatal_error
            return
        if st.stop and st.stop != "run_cap":
            break
    answer = st.final["answer"] if st.final else ""
    ok = [o for o in st.outcomes if o["ok"]]
    yield {"type": "swarm_done", "answer": answer, "roles": st.outcomes, "cost": st.cost, "unsourced": st.final["unsourced"] if st.final else [],
           "grounded": any(o.get("grounded") for o in ok), "label": None if any(o.get("grounded") for o in ok) else "UNGROUNDED",
           "failed": [o["role"] for o in st.outcomes if not o["ok"]], "capped": st.stop == "run_cap", "coverage": preset.coverage, "limits": list(preset.limits), "web": _web_report(ok)}


def _web_report(outcomes: list[dict]) -> dict:
    """What the desks took from the open web, as its own class: untrusted third-party text. `grounded`, `unsourced` and the coverage numbers
    count data from OpenTerm's own tools only; a desk that used nothing but web text is UNGROUNDED."""
    used = [o for o in outcomes if o.get("web")]
    urls: list[str] = []
    for o in used:
        urls.extend(u for u in o["web"]["urls"] if u not in urls)
    return {"class": "UNTRUSTED THIRD-PARTY WEB TEXT (NOT DATA, NOT COUNTED IN GROUNDING)", "used": bool(used), "roles": [o["role"] for o in used],
            "calls": sum(o["web"]["calls"] for o in used), "urls": urls[:30]}


def layers_of(preset: Preset) -> list[list[Task]]:
    """Layers for any preset: a LITE desk's analysts first, then its chair."""
    if preset.tasks:
        return layers(preset)
    tasks = effective_tasks(preset)
    return [[t for t in tasks if not t.depends_on], [t for t in tasks if t.depends_on]]


# --- opt-in web access (SETTINGS AI WEB ON) -----------------------------------------------------------------------------------------------
WEB_LIMIT = "NO WEB ACCESS"  # the ported presets start this limit with these words when only web tools were missing
_LIMIT_ROLES = re.compile(r"\(roles:\s*([^)]*)\)\s*\Z")


def with_web(preset: Preset, web: bool) -> Preset:
    """The preset as it runs. With web access ON, the roles named in a `NO WEB ACCESS` limit get web_search and read_url and that limit goes;
    a preset left with no limits is FULL. A preset with other limits (no code execution, no data source) stays PARTIAL, minus the web limit.
    Computed from the limits, never hard-coded, so a new preset gets it for free. With web OFF the preset is returned unchanged."""
    if not web or not any(lim.startswith(WEB_LIMIT) for lim in preset.limits):
        return preset
    from .web import WEB_TOOLS

    named: set[str] = set()
    for lim in preset.limits:
        m = _LIMIT_ROLES.search(lim) if lim.startswith(WEB_LIMIT) else None
        named |= {x.strip() for x in m.group(1).split(",") if x.strip()} if m else set()
    roles = tuple(replace(r, tools=(*r.tools, *(t for t in WEB_TOOLS if t not in r.tools))) if r.id in named else r for r in preset.roles)
    limits = tuple(lim for lim in preset.limits if not lim.startswith(WEB_LIMIT))
    coverage = preset.coverage if limits else ("FULL" if preset.coverage == "PARTIAL" else preset.coverage)
    return replace(preset, roles=roles, limits=limits, coverage=coverage)


def web_full(presets: dict[str, Preset] | None = None) -> list[str]:
    """Codes of the desks that are PARTIAL today only because web access is missing: FULL when web is ON."""
    return [c for c, p in (presets or PRESETS).items() if p.coverage == "PARTIAL" and with_web(p, True).coverage == "FULL"]
