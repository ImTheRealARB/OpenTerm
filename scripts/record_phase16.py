"""Records two real streamed OpenRouter turns for the Phase 16 agent tests (tool call, then the answer after the tool result).

Run from backend/:  uv run python ../scripts/record_phase16.py [model]
The key comes from the key store (as set in APIKEYS) and is never printed or written; a recording that contains it is discarded.
Writes tests/fixtures/llm_tool_turn1.txt (the model asks for the `quote` tool) and llm_tool_turn2.txt (the answer that uses the result).
The tool result in turn 2 is a fixed, labelled test payload, not market data.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

from openterm.config import get_settings
from openterm.keys import from_settings
from openterm.llm import openai_compat

FIX = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
SYSTEM = "You are a research assistant inside a market terminal. Use the tools for any market number. Cite tool results as [T1]."
USER = "What is AAPL trading at? Use the quote tool."
TOOLS = [{"type": "function", "function": {
    "name": "quote", "description": "Latest quote for one ticker.",
    "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}]
RESULT = {"symbol": "AAPL", "price": 123.45, "change_pct": 1.23, "source": "TEST FIXTURE"}


async def stream(http: httpx.AsyncClient, key: str, messages: list[dict], model: str, tools) -> str:
    url, headers, body = openai_compat.request("openrouter", key, messages, model, tools, 400, 0.0)
    raw = b""
    async with http.stream("POST", url, headers=headers, json=body) as r:
        async for chunk in r.aiter_bytes():
            raw += chunk
    if r.status_code != 200:
        raise SystemExit(f"HTTP {r.status_code}; nothing written")
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if key in text:
        raise SystemExit("the key appeared in the answer; nothing written")
    return text


def tool_call_from(text: str) -> dict:
    calls: dict[int, dict] = {}
    for line in text.splitlines():
        if not line.startswith("data: ") or line.endswith("[DONE]"):
            continue
        for tc in (json.loads(line[6:]).get("choices") or [{}])[0].get("delta", {}).get("tool_calls") or []:
            c = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
            c["id"] = tc.get("id") or c["id"]
            fn = tc.get("function") or {}
            c["name"] += fn.get("name") or ""
            c["arguments"] += fn.get("arguments") or ""
    if not calls:
        raise SystemExit("the model did not call the tool; nothing written")
    return calls[min(calls)]


async def main() -> int:
    values = from_settings(get_settings()).get("openrouter")
    if not values:
        print("OPENROUTER key is not set: add it in APIKEYS")
        return 1
    key = values["OPENROUTER_API_KEY"]
    model = sys.argv[1] if len(sys.argv) > 1 else "deepseek/deepseek-v4-pro"
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as http:
        t1 = await stream(http, key, msgs, model, TOOLS)
        call = tool_call_from(t1)
        msgs += [{"role": "assistant", "content": None, "tool_calls": [{"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": call["arguments"]}}]},
                 {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(RESULT)}]
        t2 = await stream(http, key, msgs, model, TOOLS)
    (FIX / "llm_tool_turn1.txt").write_bytes(t1.encode("utf-8"))
    (FIX / "llm_tool_turn2.txt").write_bytes(t2.encode("utf-8"))
    print(f"recorded {model}: call {call['name']}({call['arguments']}), turn 1 {len(t1)} bytes, turn 2 {len(t2)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
