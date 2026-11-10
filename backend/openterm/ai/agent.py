"""The agent loop: model round -> tool calls -> results back to the model, until it answers or a guard stops it.

Yields plain dict events (the SSE route sends them as they are): start, token, tool_call, tool_result, usage, notice, error, done.
`done` carries the grounding verdict: UNGROUNDED when no tool returned data, and the numbers in the answer no tool result contains.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime

from . import ground
from . import tools as toolbox
from .context import fit, truncate_text
from .guard import LoopGuard

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
MAX_ROUNDS = 8
MAX_CALLS = 24
MAX_HISTORY = 12
MAX_MESSAGE = 4000

SYSTEM = """You are the research assistant inside OpenTerm, a keyboard-first market terminal. Today is {today}.
Rules:
- Get every market figure from a tool. Never answer a price, ratio, date or statistic from memory; if no tool can supply it, say so.
- Tool calls are numbered in the order you make them in this question: the first is [T1], the second [T2]. Cite the call after each figure, like "343.46 [T1]". Ignore citations in earlier answers.
- Quote a tool's numbers as returned. If a result is marked stale, empty or failed, say that plainly. Do not repeat a failed call unchanged.
- Backtests are historical simulations, not forecasts. You give analysis, not personalised investment advice.
- You can only read data. There are no order, trading or account tools, and you must never suggest placing an order through this terminal.
- Be brief: short paragraphs or a compact list. Plain text, no markdown tables."""

CLOSING = ("Tool use has stopped ({why}). Answer now using only the data already gathered above. Say clearly what is missing or could not be "
           "retrieved. Do not call tools.")

GateCall = Callable[[str, dict], Awaitable[toolbox.ToolResult]]


def clean_history(history: list) -> list[dict]:
    """Only user and assistant text from the browser is trusted as history: no system, tool or tool_calls parts."""
    out = []
    for m in history or []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip():
            out.append({"role": m["role"], "content": m["content"][:MAX_MESSAGE]})
    return out[-MAX_HISTORY:]


def _usage(ev) -> dict:
    return {"type": "usage", "prompt_tokens": ev.prompt_tokens, "completion_tokens": ev.completion_tokens, "cost": ev.cost}


async def run(gateway, call_tool: GateCall, question: str, history: list, *, model: str = DEFAULT_MODEL, provider: str = "openrouter",
              tools: list[str] | None = None, max_rounds: int = MAX_ROUNDS, max_calls: int = MAX_CALLS, max_tokens: int = 1500,
              system: str | None = None) -> AsyncIterator[dict]:
    now = datetime.now(UTC)
    yield {"type": "start", "model": model, "provider": provider, "started": now.isoformat(timespec="seconds")}
    messages: list[dict] = [{"role": "system", "content": (system or SYSTEM.format(today=now.strftime("%Y-%m-%d"))) + toolbox.external_rule(tools)},
                            *clean_history(history), {"role": "user", "content": question}]
    offered = toolbox.openai_tools(tools)
    guard = LoopGuard()
    results: list[str] = []
    good = executed = rounds = 0
    cost = 0.0
    answer = ""
    why: str | None = None

    while rounds < max_rounds and why is None:
        rounds += 1
        text_parts: list[str] = []
        calls: list = []
        async with aclosing(gateway.chat(fit(messages), model, provider, offered, max_tokens, 0.2)) as stream:  # closed at once if we are closed
            async for ev in stream:
                if ev.type == "token":
                    text_parts.append(ev.text)
                    yield {"type": "token", "text": ev.text}
                elif ev.type == "tool_call":
                    calls.append(ev)
                elif ev.type == "usage":
                    cost += ev.cost or 0.0
                    yield _usage(ev)
                elif ev.type == "error":
                    yield {"type": "error", "kind": ev.kind, "text": ev.text}
                    return
        text = "".join(text_parts)
        if not calls:
            answer = text
            break
        for i, c in enumerate(calls):
            c.id = c.id or f"call_{rounds}_{i}"  # a provider that sends no id would leave the tool message unmatched
        messages.append({"role": "assistant", "content": text or None,
                         "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}} for c in calls]})
        for c in calls:
            c.name = toolbox.from_wire(c.name)  # a third-party tool is `server__tool` to the model, `server.tool` everywhere else
            if why is None and executed >= max_calls:
                why = f"TOOL CALL LIMIT {max_calls} REACHED"
            if why is None:
                why = guard.before(c.name, c.args)
            if why is not None:  # every tool call in the assistant message needs a tool message, run or not
                messages.append({"role": "tool", "tool_call_id": c.id, "content": f"NOT RUN: {why}"})
                continue
            executed += 1
            tid = f"T{executed}"
            yield {"type": "tool_call", "id": tid, "name": c.name, "args": c.args}
            try:
                res = await call_tool(c.name, c.args)
            except Exception as e:  # noqa: BLE001 - one broken tool must not end the stream; the type only, never the message (it may hold a secret)
                res = toolbox.ToolResult(ok=False, text=f"TOOL ERROR {type(e).__name__}", error=f"TOOL ERROR {type(e).__name__}")
            if res.ok and not res.empty:
                good += 1
                results.append(res.text)
            yield {"type": "tool_result", "id": tid, "name": c.name, "ok": res.ok, "empty": res.empty, "source": res.source, "age_s": res.age_s,
                   "stale": res.stale, "bytes": len(res.text), "summary": (res.error or res.text)[:200]}
            messages.append({"role": "tool", "tool_call_id": c.id, "content": truncate_text(res.text)})
            why = guard.after(res.ok, res.empty) or why
    else:
        why = why or f"ROUND LIMIT {max_rounds} REACHED"

    if not answer:
        why = why or "NO ANSWER"
        yield {"type": "notice", "text": f"STOPPED: {why}"}
        messages.append({"role": "user", "content": CLOSING.format(why=why.lower())})
        parts: list[str] = []
        async with aclosing(gateway.chat(fit(messages), model, provider, None, max_tokens, 0.2)) as stream:
            async for ev in stream:
                if ev.type == "token":
                    parts.append(ev.text)
                    yield {"type": "token", "text": ev.text}
                elif ev.type == "usage":
                    cost += ev.cost or 0.0
                    yield _usage(ev)
                elif ev.type == "error":
                    yield {"type": "error", "kind": ev.kind, "text": ev.text}
                    return
        answer = "".join(parts)

    grounded = good > 0
    yield {"type": "done", "answer": answer, "grounded": grounded, "label": None if grounded else "UNGROUNDED",
           "unsourced": ground.check(answer, results) if grounded else [], "tool_calls": executed, "cost": cost, "stopped": why}
