"""SWARM, AI AUTO, stored runs and THESIS routes (Phase 16 step 5). Split from routes.py; shares its helpers."""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import api as api_mod
from . import agent, tools
from .routes import MAX_QUESTION, _body, _err, _models, _stream, ai_settings, router

AUTO_TOOLS = ["history", "quote", "profile", "skill", "strategy_check", "backtest_run", "backtest_get"]
RUN_ID_IN_TEXT = re.compile(r'"run_id"\s*:\s*"([0-9a-f]{12})"')
SUBJECT_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9.\-^=]{0,11}$")
SYMBOL_ARG = re.compile(r"^[A-Za-z0-9.^=\-]{1,12}$")
AUTO_SYSTEM = """You test a market hypothesis with evidence for OpenTerm. Today is {today}.
Method: (1) restate the hypothesis as one testable rule; (2) look at the symbol with the history tool; (3) check the rule with strategy_check and fix it until it is valid;
(4) run it with backtest_run (rule grammar: terms CLOSE OPEN HIGH LOW VOLUME, SMA<n> EMA<n> RSI<n> HIGH<n> LOW<n> RET<n>; operators > < >= <= CROSS> CROSS<; AND OR;
example "SMA20 CROSS> SMA50"); (5) write the evidence report: the hypothesis, the rule tested, the data window, the metrics from the run (return, drawdown, trades,
costs), what the result does and does not show, and what would falsify it. Tool calls are numbered [T1], [T2]: cite the call after each figure.
A backtest is a historical simulation, not a forecast; a good result is not proof. Report failed or empty tool results plainly. Analysis only, not investment advice.
Plain text, at most 18 lines, no tables. Never claim a result you did not get from backtest_run."""


def _store(request: Request):
    from .store import AiStore

    return AiStore(api_mod.user(request).db)


async def save_events(request: Request, events: AsyncIterator[dict], kind: str, title: str, symbol: str | None, final: str) -> AsyncIterator[dict]:
    """Pass events through, keep them, and at the final event store the run and send `saved {run_id}` just before it so the panel can link it."""
    kept: list[dict] = []
    async for ev in events:
        kept.append(ev)
        if ev["type"] == final:
            run_id = await _store(request).save_run(kind, title, symbol, kept)
            yield {"type": "saved", "run_id": run_id}
        yield ev


def subject_symbol(subject: str) -> str | None:
    first = (subject.split() or [""])[0]
    return first.upper() if SUBJECT_SYMBOL.match(first) and first.isupper() else None


@router.get("/swarm/presets")
async def swarm_presets():
    from . import swarm

    return {"presets": swarm.listing()}


@router.post("/swarm")
async def swarm_run(request: Request):
    from . import swarm

    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    preset = swarm.PRESETS.get(str(body.get("preset") or "").upper())
    subject = body.get("subject") if isinstance(body.get("subject"), str) else ""
    if preset is None:
        return _err(400, "bad_request", f"PRESET MUST BE ONE OF {', '.join(swarm.PRESETS)}")
    if len(subject) > 300 or (preset.needs_subject and not subject.strip()):
        return _err(400, "bad_request", "SUBJECT IS REQUIRED (UP TO 300 CHARACTERS) FOR THIS PRESET. " + preset.note)
    names = _models(body, await ai_settings(request))
    if names is None:
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    client = (request.client.host, request.client.port)

    def runner_for(role) -> tools.ToolRunner:
        return tools.ToolRunner(request.app, client=client, tools=list(role.tools))

    subject = subject.strip()
    inner = swarm.run(api_mod.llm_of(request), runner_for, preset, subject, model=names[0], provider=names[1])
    events = save_events(request, inner, "swarm", f"{preset.code} {subject}"[:120], subject_symbol(subject), "swarm_done")
    return _stream(request, t0, events)


@router.post("/auto")
async def auto(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    hypothesis = body.get("hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > MAX_QUESTION:
        return _err(400, "bad_request", f"HYPOTHESIS MUST BE 1-{MAX_QUESTION} CHARACTERS")
    names = _models(body, await ai_settings(request))
    if names is None:
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    runner = tools.ToolRunner(request.app, client=(request.client.host, request.client.port), tools=AUTO_TOOLS)
    runs: list[str] = []

    async def seen(name: str, args: dict) -> tools.ToolResult:
        res = await runner(name, args)
        if name == "backtest_run" and res.ok:
            runs.extend(r for r in RUN_ID_IN_TEXT.findall(res.text) if r not in runs)
        return res

    system = AUTO_SYSTEM.format(today=time.strftime("%Y-%m-%d", time.gmtime()))
    inner = agent.run(api_mod.llm_of(request), seen, hypothesis.strip(), [], model=names[0], provider=names[1], tools=AUTO_TOOLS, system=system, max_rounds=8)

    async def with_evidence() -> AsyncIterator[dict]:
        async for ev in inner:
            if ev["type"] == "done":
                yield {"type": "evidence", "runs": runs, "tested": bool(runs),
                       "note": "HISTORICAL SIMULATION, NOT A FORECAST" if runs else "NO BACKTEST WAS RUN: THIS REPORT HAS NO BACKTEST EVIDENCE"}
            yield ev

    events = save_events(request, with_evidence(), "auto", hypothesis.strip(), None, "done")
    return _stream(request, t0, events, runner)


@router.get("/runs")
async def runs_list(request: Request, kind: str | None = None):
    return {"runs": await _store(request).runs(kind if kind in ("swarm", "auto") else None)}


@router.get("/runs/{run_id}")
async def run_get(request: Request, run_id: str):
    run = await _store(request).run(run_id)
    return run if run is not None else _err(404, "not_found", f"NO STORED RUN {run_id[:20]}")


@router.post("/runs/{run_id}/replay")
async def run_replay(request: Request, run_id: str):
    """Replays a stored run as SSE with no model call and no spend; the first event says it is a replay."""
    t0 = time.perf_counter()
    run = await _store(request).run(run_id)
    if run is None:
        return _err(404, "not_found", f"NO STORED RUN {run_id[:20]}")

    async def events() -> AsyncIterator[dict]:
        yield {"type": "replay", "run_id": run["id"], "kind": run["kind"], "title": run["title"], "created_at": run["created_at"]}
        for ev in run["events"]:
            yield ev

    return _stream(request, t0, events())


# --- THESIS ------------------------------------------------------------------------------------------------------------------------
theses_router = APIRouter(prefix="/api/theses")


@theses_router.get("")
async def theses_list(request: Request, symbol: str | None = None):
    return {"theses": await _store(request).theses(symbol if symbol and SYMBOL_ARG.match(symbol) else None)}


@theses_router.post("")
async def thesis_add(request: Request):
    from .store import StoreError

    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        return {"thesis": await _store(request).add_thesis(body)}
    except StoreError as e:
        return _err(400, e.kind, str(e))


@theses_router.patch("/{tid}")
async def thesis_update(request: Request, tid: int):
    from .store import StoreError

    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        t = await _store(request).update_thesis(tid, body)
    except StoreError as e:
        return _err(400, e.kind, str(e))
    return {"thesis": t} if t is not None else _err(404, "not_found", f"NO THESIS {tid}")


@theses_router.delete("/{tid}")
async def thesis_delete(request: Request, tid: int):
    if not api_mod.loopback(request):
        return _err(403, "forbidden", "THESES CAN ONLY BE CHANGED FROM THIS MACHINE")
    return {"deleted": tid} if await _store(request).delete_thesis(tid) else _err(404, "not_found", f"NO THESIS {tid}")
