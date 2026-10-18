"""AI routes: POST /api/ai/chat (SSE) and GET /api/ai/tools. Loopback only: the agent can spend money and read the user's portfolio."""

from __future__ import annotations

import re
import time

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


def _err(status: int, kind: str, message: str) -> Response:
    return Orjson({"error": message, "kind": kind}, status_code=status)


async def ai_settings(request: Request) -> dict:
    from ..settings_store import SettingsStore

    doc = await SettingsStore(api_mod.user(request).db).get()
    ai = (doc.get("settings") or {}).get("ai")
    return ai if isinstance(ai, dict) else {}


def sse(event: dict) -> bytes:
    return b"data: " + orjson.dumps(event) + b"\n\n"


@router.get("/tools")
async def list_tools():
    return {"tools": [{"name": t.name, "description": t.description, "parameters": t.parameters, "writes": t.method != "GET"}
                      for t in tools.REGISTRY.values()]}


@router.post("/chat")
async def chat(request: Request):
    t0 = time.perf_counter()
    if not api_mod.loopback(request):
        return _err(403, "forbidden", "THE AI CAN ONLY BE USED FROM THIS MACHINE")
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        body = None
    if not isinstance(body, dict):
        return _err(400, "bad_request", "BODY MUST BE A JSON OBJECT")
    question = body.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
        return _err(400, "bad_request", f"QUESTION MUST BE 1-{MAX_QUESTION} CHARACTERS")
    cfg = await ai_settings(request)
    model = body.get("model") or cfg.get("model") or agent.DEFAULT_MODEL
    provider = body.get("provider") or cfg.get("provider") or "openrouter"
    if not isinstance(model, str) or not MODEL_RE.match(model) or not isinstance(provider, str) or not re.match(r"^[a-z]{3,12}$", provider):
        return _err(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    history = body.get("history") if isinstance(body.get("history"), list) else []
    gateway = api_mod.llm_of(request)
    runner = tools.ToolRunner(request.app, client=(request.client.host, request.client.port))

    async def stream():
        events = agent.run(gateway, runner, question.strip(), history, model=model, provider=provider)
        first = True
        try:
            async for ev in events:
                if first:  # request in to the first event out: what this server controls (the model's own latency is not ours)
                    first = False
                    perf.record("/api/ai/first_event", (time.perf_counter() - t0) * 1000)
                if ev["type"] == "start":
                    ev["fixtures"] = bool(request.app.state.settings.openterm_fixtures)  # the panel says RECORDED when the model is a recording
                yield sse(ev)
        finally:
            await events.aclose()
            await runner.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
