"""AI routes: POST /api/ai/chat, /api/ai/bt and /api/ai/chart (SSE) and GET /api/ai/tools.

Loopback only: the agent can spend money and read the user's portfolio. `bt` drafts a backtest rule and never runs it; `chart` sends
one chart image to a vision model with no tools.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Callable

import orjson
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from .. import api as api_mod
from .. import perf
from ..responses import Orjson
from . import agent, tools

router = APIRouter(prefix="/api/ai")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{1,80}$")
MAX_QUESTION = 2000
MAX_IMAGE = 4_000_000  # characters of data URL (about 3 MB of PNG)
IMAGE_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$")
VISION_MODEL = "deepseek/deepseek-v4.1-flash"
DRAFT_RE = re.compile(r"^BT_DRAFT\s+(\{.*\})\s*$", re.MULTILINE)
BT_TOOLS = ["history", "quote", "profile", "skill", "strategy_check"]

BT_SYSTEM = """You turn a trading idea into one backtest rule for OpenTerm's BT engine. Today is {today}.
Method: look at the symbol with the history tool if the idea depends on price behaviour; write the rule; ALWAYS check it with strategy_check and fix it until it is valid.
Rule grammar: terms CLOSE OPEN HIGH LOW VOLUME, SMA<n> EMA<n> RSI<n> HIGH<n> LOW<n> RET<n> (n bars), numbers; operators > < >= <= CROSS> CROSS<; combine with AND OR.
Example rules: "SMA20 CROSS> SMA50", "RSI14 < 30", "CLOSE > HIGH50 AND VOLUME > 1000000".
Finish with one short paragraph of rationale and then, on its own last line, exactly:
BT_DRAFT {{"symbols": ["AAPL"], "rule": "SMA20 CROSS> SMA50", "range": "5Y", "interval": "1D", "rationale": "one sentence"}}
symbols: 1 to 10 tickers; range like 5Y 10Y 2Y; interval 1D or 1W. You cannot run the backtest: the user reads your rule and runs it. A backtest is a historical simulation, not a forecast."""

CHART_SYSTEM = """You describe a price chart image from a market terminal. Say what is visible: the trend, the range, the visible indicators and any gaps or spikes.
Read prices only where the axis labels are legible and say that they are read off the image. Make no prediction and give no investment advice.
You have no data tools: everything you say comes from the image alone."""


def _err(status: int, kind: str, message: str) -> Response:
    return Orjson({"error": message, "kind": kind}, status_code=status)


async def ai_settings(request: Request) -> dict:
    from ..settings_store import SettingsStore

    doc = await SettingsStore(api_mod.user(request).db).get()
    ai = (doc.get("settings") or {}).get("ai")
    return ai if isinstance(ai, dict) else {}


def sse(event: dict) -> bytes:
    return b"data: " + orjson.dumps(event) + b"\n\n"


async def _body(request: Request) -> dict | Response:
    if not api_mod.loopback(request):
        return _err(403, "forbidden", "THE AI CAN ONLY BE USED FROM THIS MACHINE")
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        body = None
    return body if isinstance(body, dict) else _err(400, "bad_request", "BODY MUST BE A JSON OBJECT")


def _models(body: dict, cfg: dict, field: str = "model", default: str = agent.DEFAULT_MODEL) -> tuple[str, str] | None:
    model = body.get("model") or cfg.get(field) or default
    provider = body.get("provider") or cfg.get("provider") or "openrouter"
    ok = isinstance(model, str) and MODEL_RE.match(model) and isinstance(provider, str) and re.match(r"^[a-z]{3,12}$", provider)
    return (model, provider) if ok else None


def _stream(request: Request, t0: float, events: AsyncIterator[dict], runner: tools.ToolRunner | None = None,
            tap: Callable[[dict], list[dict]] | None = None) -> StreamingResponse:
    """SSE response over agent-style events. `tap` may add events before one (the BT draft goes out before `done`)."""

    async def gen():
        first = True
        try:
            async for ev in events:
                if first:  # request in to the first event out: what this server controls (the model's own latency is not ours)
                    first = False
                    perf.record("/api/ai/first_event", (time.perf_counter() - t0) * 1000)
                if ev["type"] in ("start", "swarm_start"):
                    ev["fixtures"] = bool(request.app.state.settings.openterm_fixtures)  # the panel says RECORDED when the model is a recording
                for extra in tap(ev) if tap else []:
                    yield sse(extra)
                yield sse(ev)
        finally:
            await events.aclose()
            if runner:
                await runner.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/tools")
async def list_tools():
    return {"tools": [{"name": t.name, "description": t.description, "parameters": t.parameters, "writes": t.method != "GET"}
                      for t in tools.REGISTRY.values()]}


@router.post("/chat")
async def chat(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    question = body.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
        return _err(400, "bad_request", f"QUESTION MUST BE 1-{MAX_QUESTION} CHARACTERS")
    names = _models(body, await ai_settings(request))
    if names is None:
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    history = body.get("history") if isinstance(body.get("history"), list) else []
    runner = tools.ToolRunner(request.app, client=(request.client.host, request.client.port))
    events = agent.run(api_mod.llm_of(request), runner, question.strip(), history, model=names[0], provider=names[1])
    return _stream(request, t0, events, runner)


def parse_draft(answer: str) -> dict:
    """The model's BT_DRAFT line -> a validated draft with the BT command, or {"error": ...}. Nothing is run."""
    from ..bt import rules

    found = DRAFT_RE.findall(answer or "")
    if not found:
        return {"error": "THE MODEL DID NOT RETURN A BT_DRAFT LINE: ASK AGAIN OR WRITE THE RULE YOURSELF WITH BT"}
    try:
        d = json.loads(found[-1])
        symbols = d["symbols"]
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 10 or not all(isinstance(s, str) and re.match(r"^[A-Za-z0-9.^=\-]{1,12}$", s) for s in symbols):
            return {"error": "BT_DRAFT symbols MUST BE 1-10 TICKERS"}
        rule = str(d["rule"]).strip()
        interval = str(d.get("interval") or "1D").upper()
        rng = str(d.get("range") or "5Y").upper()
        cmd = rules.parse_command([",".join(s.upper() for s in symbols), *rule.split(), interval, rng])
        rules.parse(rule)
    except (ValueError, KeyError, TypeError, rules.RuleError) as e:
        return {"error": f"THE DRAFT RULE IS NOT VALID FOR BT: {str(e)[:120]}"}
    syms = [s.upper() for s in symbols]
    return {"symbols": syms, "rule": rule, "range": cmd.range, "interval": cmd.interval, "rationale": str(d.get("rationale") or "")[:400],
            "command": f"BT {','.join(syms)} {rule} {cmd.interval} {cmd.range}",
            "note": "HISTORICAL SIMULATION, NOT A FORECAST. DRAFTED BY A MODEL: READ THE RULE, THEN RUN THE COMMAND YOURSELF"}


@router.post("/bt")
async def bt(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    idea = body.get("idea")
    if not isinstance(idea, str) or not idea.strip() or len(idea) > MAX_QUESTION:
        return _err(400, "bad_request", f"IDEA MUST BE 1-{MAX_QUESTION} CHARACTERS")
    names = _models(body, await ai_settings(request))
    if names is None:
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    runner = tools.ToolRunner(request.app, client=(request.client.host, request.client.port), tools=BT_TOOLS)
    system = BT_SYSTEM.format(today=time.strftime("%Y-%m-%d", time.gmtime()))
    events = agent.run(api_mod.llm_of(request), runner, idea.strip(), [], model=names[0], provider=names[1], tools=BT_TOOLS, system=system, max_rounds=6)

    def tap(ev: dict) -> list[dict]:
        if ev["type"] != "done":
            return []
        d = parse_draft(ev["answer"])
        return [{"type": "draft_error", "text": d["error"]}] if "error" in d else [{"type": "draft", "draft": d}]

    return _stream(request, t0, events, runner, tap)


@router.post("/chart")
async def chart(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    image = body.get("image")
    if not isinstance(image, str) or len(image) > MAX_IMAGE or not IMAGE_RE.match(image):
        return _err(400, "bad_request", "IMAGE MUST BE A PNG, JPEG OR WEBP DATA URL UNDER 3 MB")
    names = _models(body, await ai_settings(request), "visionModel", VISION_MODEL)
    if names is None:
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    label = " ".join(str(body.get(k) or "") for k in ("symbol", "range")).strip()[:60]
    gateway = api_mod.llm_of(request)
    model, provider = names

    async def events() -> AsyncIterator[dict]:
        yield {"type": "start", "model": model, "provider": provider, "started": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}
        what = f" ({label})" if label else ""
        messages = [{"role": "system", "content": CHART_SYSTEM},
                    {"role": "user", "content": [{"type": "text", "text": f"Describe this chart{what}."}, {"type": "image_url", "image_url": {"url": image}}]}]
        parts: list[str] = []
        cost = 0.0
        async for ev in gateway.chat(messages, model, provider, None, 700, 0.2):
            if ev.type == "token":
                parts.append(ev.text)
                yield {"type": "token", "text": ev.text}
            elif ev.type == "usage":
                cost += ev.cost or 0.0
                yield {"type": "usage", "prompt_tokens": ev.prompt_tokens, "completion_tokens": ev.completion_tokens, "cost": ev.cost}
            elif ev.type == "error":
                yield {"type": "error", "kind": ev.kind, "text": ev.text}
                return
        yield {"type": "done", "answer": "".join(parts), "grounded": False, "label": "CHART IMAGE ONLY", "unsourced": [], "tool_calls": 0, "cost": cost, "stopped": None}

    return _stream(request, t0, events())


# --- AI DOC ------------------------------------------------------------------------------------------------------------------------
NAME_RE = re.compile(r"^[\w.\- ()]{1,100}$")
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^=\-]{1,12}$")
DOC_SYSTEM = """You answer questions about ONE document: "{name}" ({kind}, {chunks} chunks). Today is {today}.
Rules:
- Find passages with the doc_search tool (try different words if the first search finds nothing). Chunks come back labelled C1, C2...
- Answer only from the chunks you retrieved. Cite the chunk in parentheses after each fact, like (C3), and the tool call as [T1].
- If the document does not contain the answer, say so plainly. Never fill a gap with outside knowledge; figures you state must appear in a retrieved chunk.
- Quote numbers exactly as written in the document. Be brief."""


def doc_store(request: Request):
    from .doc import DocStore

    st = getattr(request.app.state, "ai_docs", None)
    if st is None:
        st = request.app.state.ai_docs = DocStore()
    return st


@router.post("/doc/upload")
async def doc_upload(request: Request, name: str = ""):
    from . import doc

    if not api_mod.loopback(request):
        return _err(403, "forbidden", "THE AI CAN ONLY BE USED FROM THIS MACHINE")
    if not NAME_RE.match(name) or ".." in name:
        return _err(400, "bad_request", "FILE NAME MUST BE 1-100 PLAIN CHARACTERS WITH AN EXTENSION")
    data = await request.body()
    if len(data) > doc.MAX_BYTES:
        return _err(413, "too_large", f"FILE OVER {doc.MAX_BYTES // 1024 // 1024} MB")
    try:
        kind, text = doc.extract_text(name, data)
    except ValueError as e:
        return _err(400, "bad_request", str(e))
    return {"doc": doc_store(request).add(name, kind, doc.chunk(text)).card()}


@router.post("/doc/filing")
async def doc_filing(request: Request):
    from ..providers.base import ProviderError
    from . import doc

    body = await _body(request)
    if isinstance(body, Response):
        return body
    symbol, form = str(body.get("symbol") or ""), str(body.get("form") or "10-K").upper()
    if not SYMBOL_RE.match(symbol) or not re.match(r"^[A-Z0-9/\-]{1,12}$", form):
        return _err(400, "bad_request", "SYMBOL OR FORM IS NOT VALID")
    sec = api_mod.svc(request).router.providers["sec"]
    try:
        filings = (await sec.filings(symbol.upper())).get("filings") or []
        hit = next((f for f in filings if f.get("form") == form and f.get("doc_url")), None)
        if hit is None:
            return _err(404, "not_found", f"NO {form} FILING WITH A DOCUMENT FOR {symbol.upper()} IN THE LATEST SEC LIST")
        raw = await sec.get_bytes(hit["doc_url"])
    except ProviderError as e:
        return _err(502, "provider", f"SEC: {str(e)[:120]}")
    if len(raw) > doc.MAX_BYTES:
        return _err(413, "too_large", "THE FILING DOCUMENT IS OVER 10 MB")
    try:
        _, text = doc.extract_text("filing.htm", raw)
    except ValueError as e:
        return _err(400, "bad_request", str(e))
    name = f"{symbol.upper()} {form} {hit.get('filed') or ''}".strip()
    return {"doc": doc_store(request).add(name, "filing", doc.chunk(text)).card(), "url": hit.get("url") or hit["doc_url"]}


@router.post("/doc/ask")
async def doc_ask(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    question = body.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION or not isinstance(body.get("doc_id"), str):
        return _err(400, "bad_request", f"NEEDS doc_id AND A QUESTION OF 1-{MAX_QUESTION} CHARACTERS")
    d = doc_store(request).get(body["doc_id"])
    if d is None:
        return _err(404, "not_found", "THAT DOCUMENT IS NO LONGER LOADED (THE LAST 5 ARE KEPT): LOAD IT AGAIN")
    names = _models(body, await ai_settings(request))
    if names is None:
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    history = body.get("history") if isinstance(body.get("history"), list) else []
    runner = tools.ToolRunner(request.app, client=(request.client.host, request.client.port), tools=["doc_search"], context={"doc": d})
    system = DOC_SYSTEM.format(name=d.name, kind=d.kind, chunks=len(d.chunks), today=time.strftime("%Y-%m-%d", time.gmtime()))
    events = agent.run(api_mod.llm_of(request), runner, question.strip(), history, model=names[0], provider=names[1], tools=["doc_search"], system=system, max_rounds=6)
    return _stream(request, t0, events, runner)
