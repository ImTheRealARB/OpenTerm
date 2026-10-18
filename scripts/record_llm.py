"""Records one real streamed OpenRouter answer for the gateway test (Phase 11 step 5).

Run from backend/:  uv run python ../scripts/record_llm.py [model]
The key comes from the key store (env > OS keyring > .env, as set in APIKEYS) and is never printed or written.
Without a model argument the first free (`:free`, US$0) model on OpenRouter's list is used.
"""

import asyncio
import sys
from pathlib import Path

import httpx

from openterm.config import get_settings
from openterm.keys import from_settings

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "llm_openrouter_stream.txt"
PROMPT = "In one short sentence: what does a bond's yield measure?"


async def main() -> int:
    values = from_settings(get_settings()).get("openrouter")
    if not values:
        print("OPENROUTER key is not set: add it in APIKEYS or as OPENROUTER_API_KEY in .env")
        return 1
    key = values["OPENROUTER_API_KEY"]
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as http:
        model = sys.argv[1] if len(sys.argv) > 1 else None
        if model is None:
            models = (await http.get("https://openrouter.ai/api/v1/models")).json().get("data") or []
            model = next((m["id"] for m in models if m.get("id", "").endswith(":free")), None)
            if model is None:
                print("no :free model listed; pass a model id")
                return 1
        body = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "stream": True,
                "max_tokens": 600, "usage": {"include": True}}
        raw = b""
        async with http.stream("POST", "https://openrouter.ai/api/v1/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {key}"}) as r:
            async for chunk in r.aiter_bytes():
                raw += chunk
        text = raw.decode("utf-8", errors="replace")
        if r.status_code != 200:
            print(f"HTTP {r.status_code}; nothing written")
            return 1
        if key in text:
            print("the key appeared in the answer; nothing written")
            return 1
        OUT.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
        print(f"recorded {model}: {len(raw)} bytes -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
