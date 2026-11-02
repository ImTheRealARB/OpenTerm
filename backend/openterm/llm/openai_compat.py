"""OpenAI-compatible chat streams: OpenRouter, OpenAI, Ollama (`/v1/chat/completions`).

`OpenAIStream` maps SSE payloads to gateway events. Tool calls arrive as deltas keyed by `index` (the id and name in
the first delta, the JSON arguments split across later ones); they are emitted whole when the choice finishes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import orjson

from .events import Event

BASES = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    # Hosted OpenAI-compatible providers (all speak `/chat/completions`, Bearer key, SSE stream).
    "opencodego": "https://opencode.ai/inference/go/openai/v1",  # OpenCode Go subscription, OpenAI-style models only
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}
# Keyed providers that use the OpenAI-compatible request/stream code (everything in BASES except local Ollama).
HOSTED = tuple(p for p in BASES if p != "ollama")


class OpenAIStream:
    def __init__(self) -> None:
        self._calls: dict[int, dict] = {}  # slot (order of arrival) -> call
        self._slot: dict[int, int] = {}  # the provider's `index` -> the slot it fills now
        self.finished = False

    def _flush_calls(self) -> list[Event]:
        out = []
        for _, c in sorted(self._calls.items()):
            raw = c["args"].strip()
            try:
                args = orjson.loads(raw) if raw else {}
            except orjson.JSONDecodeError:
                out.append(Event("error", kind="bad_output", text=f"TOOL CALL {c['name']}: ARGUMENTS ARE NOT JSON"))
                continue
            out.append(Event("tool_call", id=c["id"], name=c["name"], args=args if isinstance(args, dict) else {}))
        self._calls.clear()
        self._slot.clear()
        return out

    def feed(self, payload: str) -> list[Event]:
        if payload.strip() == "[DONE]":
            return self.finish()
        try:
            msg = orjson.loads(payload)
        except orjson.JSONDecodeError:
            return [Event("error", kind="bad_output", text="STREAM CHUNK IS NOT JSON")]
        if not isinstance(msg, dict):
            return []
        if err := msg.get("error"):
            text = err.get("message") if isinstance(err, dict) else str(err)
            return [Event("error", kind="provider", text=str(text or "PROVIDER ERROR")[:300])]
        out: list[Event] = []
        for choice in msg.get("choices") or []:
            delta = choice.get("delta") or {}
            if text := delta.get("content"):
                out.append(Event("token", text=text))
            for tc in delta.get("tool_calls") or []:
                index = tc.get("index", 0)
                slot = self._slot.get(index)
                if slot is not None and tc.get("id") and self._calls[slot]["id"] not in (None, tc["id"]):
                    slot = None  # some providers number every parallel call 0 and tell them apart by id only
                if slot is None:
                    slot = self._slot[index] = len(self._calls)
                    self._calls[slot] = {"id": None, "name": None, "args": ""}
                c = self._calls[slot]
                fn = tc.get("function") or {}
                c["id"] = tc.get("id") or c["id"]
                c["name"] = fn.get("name") or c["name"]
                c["args"] += fn.get("arguments") or ""
            if choice.get("finish_reason"):
                out += self._flush_calls()
        if usage := msg.get("usage"):
            cost = usage.get("cost")
            out.append(Event("usage", prompt_tokens=int(usage.get("prompt_tokens") or 0),
                             completion_tokens=int(usage.get("completion_tokens") or 0),
                             cost=float(cost) if cost is not None else None))
        return out

    def finish(self) -> list[Event]:
        if self.finished:
            return []
        self.finished = True
        return [*self._flush_calls(), Event("done")]


def events_from_payloads(payloads: Iterable[str]) -> Iterator[Event]:
    s = OpenAIStream()
    for p in payloads:
        yield from s.feed(p)
    yield from s.finish()


def request(provider: str, key: str | None, messages: list[dict], model: str, tools: list[dict] | None,
            max_tokens: int, temperature: float | None, base: str | None = None) -> tuple[str, dict, dict]:
    """-> (url, headers, json body) for a streamed chat completion."""
    body: dict = {"model": model, "messages": messages, "stream": True, "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools
    if provider == "openrouter":
        body["usage"] = {"include": True}  # OpenRouter usage accounting: tokens and cost in the last chunk
    else:
        body["stream_options"] = {"include_usage": True}
    headers = {"Accept": "text/event-stream"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return f"{base or BASES[provider]}/chat/completions", headers, body
