"""SWARM: preset multi-agent runs. A fixed DAG of roles over the same agent loop; each role has its own tool allow-list and prompt.

Analyst roles run first (in order), then the chair role writes the synthesis from their notes. A role that errors or returns nothing is retried
once; if it still fails the chair is told which role failed and why. A missing key stops the whole run. Events are the agent's events with a
`role` field, plus `swarm_start`, `role_start`, `role_retry`, `role_done`, `role_error` and `swarm_done`. Numbers in the synthesis are checked
against the analysts' notes (a check, not a proof); the analysts' own numbers are checked against their tool results.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import agent, ground
from . import tools as toolbox

MAX_RETRIES = 1
ROLE_ROUNDS = 5
ROLE_CALLS = 10

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


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    brief: str
    tools: tuple[str, ...]
    chair: bool = False


@dataclass(frozen=True)
class Preset:
    code: str
    title: str
    roles: tuple[Role, ...]
    note: str = ""
    needs_subject: bool = True
    tags: tuple[str, ...] = field(default=())


def _chair(brief: str, tools: tuple[str, ...] = ("quote",)) -> Role:
    return Role("chair", "Chair", brief, tools, chair=True)


PRESETS: dict[str, Preset] = {p.code: p for p in [
    Preset("COMMITTEE", "Investment committee", (
        Role("fundamental", "Fundamental analyst", "Value the business: size, growth, margins, balance sheet, the profile.", ("quote", "profile", "fa", "research", "skill")),
        Role("technical", "Technical analyst", "Describe the price trend, range and (if listed) options positioning.", ("history", "quote", "options_chain")),
        Role("risk", "Risk analyst", "Find what could go wrong: news, filings, drawdowns.", ("news", "filings", "history")),
        _chair("Give the committee's view on the subject: a balanced case, not a recommendation to trade.")), "Subject: one ticker, e.g. AAPL."),
    Preset("RISK", "Risk committee", (
        Role("exposure", "Exposure analyst", "Read the user's portfolios and say what is held and how it is concentrated.", ("portfolio", "quote")),
        Role("var", "Risk-model analyst", "Run the risk analytics (VaR, drawdown) for the named portfolio.", ("quant", "portfolio")),
        Role("headlines", "News analyst", "Find news relevant to the largest positions.", ("news", "portfolio")),
        _chair("Summarise the portfolio's risk: concentration, VaR and drawdown, and headline risks.")), "Subject: a portfolio name, e.g. MAIN."),
    Preset("EARNINGS", "Earnings desk", (
        Role("estimates", "Estimates analyst", "Report earnings estimates, revisions and the last results.", ("research", "quote", "skill")),
        Role("reports", "Filings analyst", "Read the latest filings and statements for what changed.", ("filings", "fa", "news")),
        _chair("Say what to watch at the next earnings report and how the estimates compare with the filed numbers.")), "Subject: one ticker."),
    Preset("MACRO", "Macro desk", (
        Role("rates", "Rates analyst", "Describe the yield curve and what it implies.", ("rates", "macro", "skill")),
        Role("series", "Economic-data analyst", "Find the macro series relevant to the question.", ("macro", "news")),
        _chair("Summarise the macro picture and the main uncertainties.")), "Subject: a theme, e.g. INFLATION.", needs_subject=False),
    Preset("QUANT", "Quant desk", (
        Role("trend", "Trend analyst", "Describe the price history of the subject (returns, volatility, range).", ("history", "quote")),
        Role("tester", "Backtest analyst", "Test one simple rule on the subject with backtest_run (validate it with strategy_check first) and report the metrics.",
             ("history", "strategy_check", "backtest_run", "skill")),
        _chair("Summarise the evidence. A backtest is a historical simulation, not a forecast.")), "Subject: a ticker."),
]}


def listing() -> list[dict]:
    return [{"code": p.code, "title": p.title, "roles": [{"id": r.id, "title": r.title, "tools": list(r.tools)} for r in p.roles], "note": p.note,
             "needs_subject": p.needs_subject} for p in PRESETS.values()]


def role_system(role: Role, today: str) -> str:
    return (CHAIR if role.chair else COMMON).format(today=today, title=role.title, brief=role.brief)


def role_question(role: Role, subject: str, notes: list[tuple[Role, str]]) -> str:
    base = f"Subject: {subject}" if subject else "No specific subject was given: use the general picture."
    if not role.chair:
        return base
    body = "\n\n".join(f"## {r.title} ({r.id})\n{text}" for r, text in notes)
    return f"{base}\n\nAnalyst notes:\n{body}"


RunnerFor = Callable[[Role], toolbox.ToolRunner]


async def run(gateway, runner_for: RunnerFor, preset: Preset, subject: str, *, model: str = agent.DEFAULT_MODEL, provider: str = "openrouter") -> AsyncIterator[dict]:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    yield {"type": "swarm_start", "preset": preset.code, "title": preset.title, "subject": subject, "model": model, "provider": provider,
           "started": datetime.now(UTC).isoformat(timespec="seconds"), "roles": [{"id": r.id, "title": r.title, "tools": list(r.tools)} for r in preset.roles]}
    notes: list[tuple[Role, str]] = []
    outcomes: list[dict] = []
    cost = 0.0
    final: dict | None = None
    for role in preset.roles:
        tries = 0
        done: dict | None = None
        failure = ""
        while tries <= MAX_RETRIES and done is None:
            tries += 1
            if tries > 1:
                yield {"type": "role_retry", "role": role.id, "attempt": tries, "why": failure}
            yield {"type": "role_start", "role": role.id, "title": role.title, "tools": list(role.tools), "attempt": tries}
            runner = runner_for(role)
            events = agent.run(gateway, runner, role_question(role, subject, notes), [], model=model, provider=provider, tools=list(role.tools),
                               system=role_system(role, today), max_rounds=ROLE_ROUNDS, max_calls=ROLE_CALLS, max_tokens=900)
            failure = ""
            try:
                async for ev in events:
                    if ev["type"] == "start":
                        continue
                    if ev["type"] == "error":
                        failure = f"{ev['kind']}: {ev['text']}"
                        if ev["kind"] == "key_required":  # no retry, nothing else can run either
                            yield {"type": "error", "kind": ev["kind"], "text": ev["text"]}
                            return
                        yield {"type": "role_error", "role": role.id, "kind": ev["kind"], "text": ev["text"]}
                        break
                    if ev["type"] == "done":
                        if not ev["answer"].strip():
                            failure = "THE MODEL RETURNED NO ANSWER"
                            yield {"type": "role_error", "role": role.id, "kind": "empty", "text": failure}
                        else:
                            done = ev
                        continue
                    yield {**ev, "role": role.id}
            finally:
                await events.aclose()
                await runner.aclose()
        if done is None:
            outcomes.append({"role": role.id, "ok": False, "why": failure, "cost": 0.0})
            notes.append((role, f"ROLE FAILED: {failure}"))
            continue
        cost += done["cost"]
        if role.chair:
            sources = [t for _, t in notes if not t.startswith("ROLE FAILED")]
            grounded = any(o.get("grounded") for o in outcomes if o["ok"])
            done = {**done, "unsourced": ground.check(done["answer"], sources) if sources else [], "grounded": grounded,
                    "label": None if grounded else "UNGROUNDED"}
            final = done
        else:
            notes.append((role, done["answer"]))
        outcomes.append({"role": role.id, "ok": True, "grounded": done["grounded"], "unsourced": done["unsourced"], "tool_calls": done["tool_calls"],
                         "cost": done["cost"], "stopped": done["stopped"]})
        yield {**done, "type": "role_done", "role": role.id}
    answer = final["answer"] if final else ""
    ok = [o for o in outcomes if o["ok"]]
    yield {"type": "swarm_done", "answer": answer, "roles": outcomes, "cost": cost, "unsourced": final["unsourced"] if final else [],
           "grounded": any(o.get("grounded") for o in ok), "label": None if any(o.get("grounded") for o in ok) else "UNGROUNDED",
           "failed": [o["role"] for o in outcomes if not o["ok"]]}
