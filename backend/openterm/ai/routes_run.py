"""SWARM, AI AUTO, stored runs and THESIS routes (Phase 16 step 5). Split from routes.py; shares its helpers."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import api as api_mod
from .. import http_util
from ..idents import AI_SYMBOL_RE
from ..responses import OrjsonRoute
from . import agent, tools
from .routes import MAX_QUESTION, _body, _models, _stream, ai_settings, audit, router

log = logging.getLogger("openterm.ai")
AUTO_TOOLS = ["history", "quote", "profile", "skill", "skills", "strategy_check", "backtest_run", "backtest_get"]
RUN_ID_IN_TEXT = re.compile(r'"run_id"\s*:\s*"([0-9a-f]{8,32})"')  # BT run ids are 16 hex characters
SUBJECT_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9.\-^=]{0,11}$")
AUTO_SYSTEM = """You test a market hypothesis with evidence for OpenTerm. Today is {today}.
Method: (1) restate the hypothesis as one testable rule; (2) look at the symbol with the history tool; (3) check the rule with strategy_check and fix it until it is valid;
(4) run it with backtest_run (rule grammar: terms CLOSE OPEN HIGH LOW VOLUME, SMA<n> EMA<n> RSI<n> HIGH<n> LOW<n> RET<n>; operators > < >= <= CROSS> CROSS<; AND OR;
example "SMA20 CROSS> SMA50"); (5) write the evidence report: the hypothesis, the rule tested, the data window, the metrics from the run (return, drawdown, trades,
costs), what the result does and does not show, and what would falsify it. Tool calls are numbered [T1], [T2]: cite the call after each figure.
A backtest is a historical simulation, not a forecast; a good result is not proof. Report failed or empty tool results plainly. Analysis only, not investment advice.
Plain text, at most 18 lines, no tables. Never claim a result you did not get from backtest_run."""


def _store(request: Request):
    from .store import AiStore

    return AiStore(http_util.user(request).db)


async def save_events(request: Request, events: AsyncIterator[dict], kind: str, title: str, symbol: str | None, final: str) -> AsyncIterator[dict]:
    """Pass events through, keep them, and at the final event store the run and send `saved {run_id}` just before it so the panel can link it."""
    kept: list[dict] = []
    async with aclosing(events) as stream:
        async for ev in stream:
            kept.append(ev)
            if ev["type"] == final:
                try:  # a full disk must not cost the user the answer they already paid for
                    run_id = await _store(request).save_run(kind, title, symbol, kept)
                except Exception:
                    log.exception("could not store the %s run", kind)
                else:
                    yield {"type": "saved", "run_id": run_id}
            yield ev


def subject_symbol(subject: str) -> str | None:
    first = (subject.split() or [""])[0]
    return first.upper() if SUBJECT_SYMBOL.match(first) and first.isupper() else None


def user_presets_dir(request: Request):
    """`<data dir>/presets`: next to the database, so it is wherever the user keeps their OpenTerm data."""
    from pathlib import Path

    return Path(request.app.state.settings.openterm_db_path).parent / "presets"


@router.get("/swarm/presets")
async def swarm_presets(request: Request):
    from . import swarm

    presets, errors = swarm.all_presets(user_presets_dir(request))
    names = _models({}, await ai_settings(request)) or (agent.DEFAULT_MODEL, "openrouter")
    price = await api_mod.llm_of(request).price(names[1], names[0])
    rows = swarm.listing(presets)
    for r in rows:
        r["estimate"]["usd"] = swarm.usd(r["estimate"], price)
    spend = await api_mod.llm_of(request).spend_status()
    return {"presets": rows, "errors": errors, "model": names[0], "spend": spend}


class _Stop(Exception):
    """Raised inside the route to refuse a run with a message (cost cap)."""


async def check_cost(request: Request, preset, subject: str, names: tuple[str, str], force: bool) -> dict | Response:
    """Rule: cost is shown before it is spent. Returns the estimate (with dollars when the model's price is known) or a refusal."""
    from . import swarm

    gateway = api_mod.llm_of(request)
    est = swarm.estimate(preset, subject)
    est["usd"] = swarm.usd(est, await gateway.price(names[1], names[0]))
    spend = await gateway.spend_status()
    left = spend["cap"] - spend["today"]
    est["cap_left"] = round(left, 4)
    if est["usd"] is not None and est["usd"] > left and not force:
        return http_util.error_response(402, "spend_cap", f"{preset.code} WORST CASE US${est['usd']:.2f} IS OVER THE US${left:.2f} LEFT OF TODAY'S CAP. "
                                      "RAISE THE CAP IN SETTINGS, OR SEND force:true TO RUN ANYWAY (THE CAP STILL STOPS A RUN THAT REACHES IT)")
    return est


@router.post("/swarm")
async def swarm_run(request: Request):
    from . import swarm

    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    presets, _errors = swarm.all_presets(user_presets_dir(request))
    preset = presets.get(str(body.get("preset") or "").upper())
    subject = body.get("subject") if isinstance(body.get("subject"), str) else ""
    if preset is None:
        return http_util.error_response(400, "bad_request", f"PRESET MUST BE ONE OF {', '.join(presets)}")
    if preset.coverage == "UNAVAILABLE":
        return http_util.error_response(400, "unavailable", f"{preset.code} IS UNAVAILABLE: {'; '.join(preset.limits)}")
    given = body.get("variables")
    if given is not None and not (isinstance(given, dict) and all(isinstance(k, str) and isinstance(v, str) and len(v) <= 300 for k, v in given.items())):
        return http_util.error_response(400, "bad_request", "variables MUST BE AN OBJECT OF SHORT STRINGS")
    if len(subject) > 300 or (preset.needs_subject and not subject.strip() and not given):
        return http_util.error_response(400, "bad_request", "SUBJECT IS REQUIRED (UP TO 300 CHARACTERS) FOR THIS PRESET. " + (preset.note or "SEND variables, E.G. {\"target\": \"AAPL\"}"))
    names = _models(body, await ai_settings(request))
    if names is None:
        return http_util.error_response(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    est = await check_cost(request, preset, subject, names, bool(body.get("force")))
    if isinstance(est, Response):
        return est
    client = (request.client.host, request.client.port)

    def runner_for(role) -> tools.ToolRunner:
        return tools.ToolRunner(request.app, client=client, tools=list(role.tools))

    subject = subject.strip()
    run_events = swarm.run(api_mod.llm_of(request), runner_for, preset, subject, model=names[0], provider=names[1], variables=given)

    async def with_estimate() -> AsyncIterator[dict]:
        # The estimate follows swarm_start, so the panel (and a replay of the stored run) shows what the run could have cost.
        async with aclosing(run_events) as stream:
            async for ev in stream:
                yield ev
                if ev["type"] == "swarm_start":
                    yield {"type": "estimate", **est}

    inner = with_estimate()
    events = save_events(request, inner, "swarm", f"{preset.code} {subject}"[:120], subject_symbol(subject), "swarm_done")
    role_tools = sorted({t for r in preset.roles for t in r.tools})
    # The ledger keeps a hash of the question. `SWARM MYDESK TARGET=AAPL` sends the ticker only as a variable (no subject), so the variables
    # must be part of the question or two different runs of one desk would look identical in the audit log.
    asked = f"{preset.code} {subject}" + "".join(f" {k}={v}" for k, v in sorted((given or {}).items()))
    events = audit(request, events, "swarm", swarm.prompt_text(preset), asked, role_tools, names[0], names[1])
    return _stream(request, t0, events)


@router.post("/auto")
async def auto(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    hypothesis = body.get("hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > MAX_QUESTION:
        return http_util.error_response(400, "bad_request", f"HYPOTHESIS MUST BE 1-{MAX_QUESTION} CHARACTERS")
    names = _models(body, await ai_settings(request))
    if names is None:
        return http_util.error_response(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
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
        async with aclosing(inner) as stream:
            async for ev in stream:
                if ev["type"] == "done":
                    yield {"type": "evidence", "runs": runs, "tested": bool(runs),
                           "note": "HISTORICAL SIMULATION, NOT A FORECAST" if runs else "NO BACKTEST WAS RUN: THIS REPORT HAS NO BACKTEST EVIDENCE"}
                yield ev

    events = save_events(request, with_evidence(), "auto", hypothesis.strip(), None, "done")
    events = audit(request, events, "ai_auto", AUTO_SYSTEM, hypothesis.strip(), AUTO_TOOLS, names[0], names[1])
    return _stream(request, t0, events, runner)


@router.get("/ledger")
async def ledger_list(request: Request, limit: int = 50):
    from .audit import audit_of

    return {"entries": await audit_of(request.app, http_util.user(request).db).entries(limit)}


@router.get("/ledger/verify")
async def ledger_verify(request: Request):
    from .audit import audit_of

    return await audit_of(request.app, http_util.user(request).db).verify()


@router.get("/runs")
async def runs_list(request: Request, kind: str | None = None):
    return {"runs": await _store(request).runs(kind if kind in ("swarm", "auto") else None)}


@router.get("/runs/{run_id}")
async def run_get(request: Request, run_id: str):
    run = await _store(request).run(run_id)
    return run if run is not None else http_util.error_response(404, "not_found", f"NO STORED RUN {run_id[:20]}")


@router.post("/runs/{run_id}/replay")
async def run_replay(request: Request, run_id: str):
    """Replays a stored run as SSE with no model call and no spend; the first event says it is a replay."""
    t0 = time.perf_counter()
    run = await _store(request).run(run_id)
    if run is None:
        return http_util.error_response(404, "not_found", f"NO STORED RUN {run_id[:20]}")

    async def events() -> AsyncIterator[dict]:
        yield {"type": "replay", "run_id": run["id"], "kind": run["kind"], "title": run["title"], "created_at": run["created_at"]}
        for ev in run["events"]:
            yield ev

    return _stream(request, t0, events())


# --- THESIS ------------------------------------------------------------------------------------------------------------------------
theses_router = APIRouter(prefix="/api/theses", route_class=OrjsonRoute)


@theses_router.get("")
async def theses_list(request: Request, symbol: str | None = None):
    return {"theses": await _store(request).theses(symbol if symbol and AI_SYMBOL_RE.match(symbol) else None)}


@theses_router.post("")
async def thesis_add(request: Request):
    from .store import StoreError

    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        return {"thesis": await _store(request).add_thesis(body)}
    except StoreError as e:
        return http_util.error_response(400, e.kind, str(e))


@theses_router.patch("/{tid}")
async def thesis_update(request: Request, tid: int):
    from .store import StoreError

    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        t = await _store(request).update_thesis(tid, body)
    except StoreError as e:
        return http_util.error_response(400, e.kind, str(e))
    return {"thesis": t} if t is not None else http_util.error_response(404, "not_found", f"NO THESIS {tid}")


@theses_router.delete("/{tid}")
async def thesis_delete(request: Request, tid: int):
    if not http_util.loopback(request):
        return http_util.error_response(403, "forbidden", "THESES CAN ONLY BE CHANGED FROM THIS MACHINE")
    return {"deleted": tid} if await _store(request).delete_thesis(tid) else http_util.error_response(404, "not_found", f"NO THESIS {tid}")
