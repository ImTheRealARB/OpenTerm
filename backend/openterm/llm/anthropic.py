"""Anthropic Messages API adapter: OpenAI-shaped messages and tools in, the gateway's events out.

Stream events: `message_start` (input tokens), `content_block_start/delta/stop` (text, or a `tool_use` block whose
JSON input arrives as `input_json_delta` pieces), `message_delta` (output tokens), `message_stop`. Anthropic does not
return a cost, so `usage.cost` is None and the client prices it from config.yaml.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import orjson

from .events import Event

BASE = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"


class AnthropicStream:
    def __init__(self) -> None:
        self._blocks: dict[int, dict] = {}
        self._prompt = 0
        self._completion = 0
        self.finished = False

    def feed(self, payload: str) -> list[Event]:
        try:
            msg = orjson.loads(payload)
        except orjson.JSONDecodeError:
            return [Event("error", kind="bad_output", text="STREAM CHUNK IS NOT JSON")]
        kind = msg.get("type") if isinstance(msg, dict) else None
        if kind == "message_start":
            usage = (msg.get("message") or {}).get("usage") or {}
            self._prompt = int(usage.get("input_tokens") or 0)
            self._completion = int(usage.get("output_tokens") or 0)
        elif kind == "content_block_start":
            block = msg.get("content_block") or {}
            if block.get("type") == "tool_use":
                self._blocks[msg.get("index", 0)] = {"id": block.get("id"), "name": block.get("name"), "json": ""}
            elif text := block.get("text"):
                return [Event("token", text=text)]
        elif kind == "content_block_delta":
            delta = msg.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [Event("token", text=delta["text"])]
            if delta.get("type") == "input_json_delta" and (b := self._blocks.get(msg.get("index", 0))):
                b["json"] += delta.get("partial_json") or ""
        elif kind == "content_block_stop":
            if (b := self._blocks.pop(msg.get("index", 0), None)) is not None:
                try:
                    args = orjson.loads(b["json"]) if b["json"].strip() else {}
                except orjson.JSONDecodeError:
                    return [Event("error", kind="bad_output", text=f"TOOL CALL {b['name']}: ARGUMENTS ARE NOT JSON")]
                return [Event("tool_call", id=b["id"], name=b["name"], args=args if isinstance(args, dict) else {})]
        elif kind == "message_delta":
            usage = msg.get("usage") or {}
            self._completion = int(usage.get("output_tokens") or self._completion)
        elif kind == "message_stop":
            return self.finish()
        elif kind == "error":
            err = msg.get("error") or {}
            return [Event("error", kind="provider", text=str(err.get("message") or "PROVIDER ERROR")[:300])]
        return []

    def finish(self) -> list[Event]:
        if self.finished:
            return []
        self.finished = True
        return [Event("usage", prompt_tokens=self._prompt, completion_tokens=self._completion, cost=None),
                Event("done")]


def events_from_payloads(payloads: Iterable[str]) -> Iterator[Event]:
    s = AnthropicStream()
    for p in payloads:
        yield from s.feed(p)
    yield from s.finish()


def _content(m: dict) -> list[dict] | str:
    if m["role"] == "tool":
        return [{"type": "tool_result", "tool_use_id": m.get("tool_call_id"), "content": str(m.get("content") or "")}]
    blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        blocks.append({"type": "tool_use", "id": tc.get("id"), "name": fn.get("name"),
                       "input": orjson.loads(raw) if isinstance(raw, str) else raw})
    return blocks if len(blocks) != 1 or blocks[0]["type"] != "text" else blocks[0]["text"]


def convert(messages: list[dict], tools: list[dict] | None) -> tuple[str | None, list[dict], list[dict] | None]:
    """OpenAI shape -> (system, messages, tools) in the Messages API shape. Tool results become user turns."""
    system = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system") or None
    out: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            continue
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = _content(m)
        if out and out[-1]["role"] == role and role == "user" and isinstance(content, list):
            prev = out[-1]["content"]
            out[-1]["content"] = (prev if isinstance(prev, list) else [{"type": "text", "text": prev}]) + content
        else:
            out.append({"role": role, "content": content})
    conv = [{"name": (t.get("function") or t)["name"], "description": (t.get("function") or t).get("description", ""),
             "input_schema": (t.get("function") or t).get("parameters") or {"type": "object", "properties": {}}}
            for t in tools or []] or None
    return system, out, conv


def request(key: str, messages: list[dict], model: str, tools: list[dict] | None, max_tokens: int,
            temperature: float | None) -> tuple[str, dict, dict]:
    system, msgs, conv = convert(messages, tools)
    body: dict = {"model": model, "messages": msgs, "max_tokens": max_tokens, "stream": True}
    if system:
        body["system"] = system
    if conv:
        body["tools"] = conv
    if temperature is not None:
        body["temperature"] = temperature
    headers = {"x-api-key": key, "anthropic-version": VERSION, "Accept": "text/event-stream"}
    return f"{BASE}/messages", headers, body
