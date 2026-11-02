"""LLM gateway: one `chat()` over OpenRouter, OpenAI, Ollama (OpenAI-compatible) and Anthropic (Messages API).

Every call checks the key (KEY REQUIRED), the price and the daily spend cap before any network call, then streams
`Event`s and adds the real cost to today's spend. Prompts and outputs are never logged; error text is redacted.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import aiosqlite
import httpx

from .. import keys as keystore
from ..redact import redact
from . import anthropic, openai_compat, spend
from .events import Event
from .sse import SSEParser

KEYED = (*openai_compat.HOSTED[:2], "anthropic", *openai_compat.HOSTED[2:])  # keeps the old order, new ones after
PROVIDERS = (*KEYED, "ollama")
OLLAMA = "http://127.0.0.1:11434"
TIMEOUT = httpx.Timeout(60.0, connect=5.0)  # read: 60 s between chunks
MODELS_TTL = 3600.0
OLLAMA_TTL = 10.0


def _clean(ev: Event) -> Event:
    """A provider's own error text (it can echo the key it was sent) goes through redact() like every other error text."""
    if ev.type == "error":
        ev.text = redact(ev.text)
    return ev


class Gateway:
    def __init__(self, keys: keystore.KeyStore, http: httpx.AsyncClient, db: aiosqlite.Connection,
                 config: dict | None = None):
        config = config or {}
        self.keys = keys
        self.http = http
        self.db = db
        self.prices: dict = config.get("prices") or {}
        self.ollama = str(config.get("ollama_url") or OLLAMA).rstrip("/")
        self._or_prices: dict[str, dict] = {}
        self._or_at = 0.0
        self._ollama: tuple[float, str, str | None] = (0.0, "DOWN", None)

    # --- prices ---
    async def _openrouter_prices(self) -> dict[str, dict]:
        if time.monotonic() - self._or_at < MODELS_TTL and self._or_prices:
            return self._or_prices
        try:
            r = await self.http.get("https://openrouter.ai/api/v1/models", timeout=10.0)
            r.raise_for_status()
            out = {}
            for m in r.json().get("data") or []:
                p = m.get("pricing") or {}
                try:
                    inp, outp = float(p["prompt"]), float(p["completion"])
                except (KeyError, TypeError, ValueError):
                    continue
                if inp >= 0 and outp >= 0:  # -1 marks a router whose price depends on the model it picks
                    out[m.get("id")] = {"input": inp * 1e6, "output": outp * 1e6}
            self._or_prices, self._or_at = out, time.monotonic()
        except (httpx.HTTPError, ValueError):
            pass  # keep the last list; an unknown model is then refused under the cap
        return self._or_prices

    async def price(self, provider: str, model: str) -> dict | None:
        """US$ per million tokens {input, output}; None = unknown. Ollama is local and free."""
        if provider == "ollama":
            return {"input": 0.0, "output": 0.0}
        if model.endswith(":free") and provider == "openrouter":
            return {"input": 0.0, "output": 0.0}
        if (p := (self.prices.get(provider) or {}).get(model)) is not None:
            return {"input": float(p.get("input", 0.0)), "output": float(p.get("output", 0.0))}
        if provider == "openrouter":
            return (await self._openrouter_prices()).get(model)
        return None

    # --- chat ---
    async def chat(self, messages: list[dict], model: str, provider: str = "openrouter", tools: list[dict] | None = None,
                   max_tokens: int = 1024, temperature: float | None = None) -> AsyncIterator[Event]:
        if provider not in PROVIDERS:
            yield Event("error", kind="provider", text=f"UNKNOWN LLM PROVIDER {provider.upper()}")
            return
        key = None
        if provider in KEYED:
            values = await asyncio.to_thread(self.keys.get, provider)
            if values is None:
                label = keystore.KEY_SPECS[provider].label
                yield Event("error", kind="key_required", text=f"KEY REQUIRED: set {label} in APIKEYS")
                return
            key = next(iter(values.values()))
        local = provider == "ollama"
        price = await self.price(provider, model)
        spent, cap = await spend.today(self.db), await spend.get_cap(self.db)
        if refusal := spend.check(spent, cap, max_tokens, price, local):
            yield Event("error", kind="spend_cap" if refusal == "SPEND CAP REACHED" else "price_unknown",
                        text=f"{refusal}: US${spent:.2f} of US${cap:.2f} today" if refusal == "SPEND CAP REACHED"
                        else f"{refusal}: {provider}/{model} has no price in config.yaml llm.prices")
            return

        if provider == "anthropic":
            url, headers, body = anthropic.request(key, messages, model, tools, max_tokens, temperature)
            stream = anthropic.AnthropicStream()
        else:
            url, headers, body = openai_compat.request(provider, key, messages, model, tools, max_tokens, temperature,
                                                       base=f"{self.ollama}/v1" if local else None)
            stream = openai_compat.OpenAIStream()

        charged = streaming = False
        try:
            async with self.http.stream("POST", url, headers=headers, json=body, timeout=TIMEOUT) as r:
                if r.status_code != 200:
                    text = (await r.aread()).decode("utf-8", errors="replace")
                    state = keystore.classify(r.status_code, text)
                    yield Event("error", kind={"INVALID": "invalid", "QUOTA": "quota"}.get(state, "provider"),
                                text=redact(f"{provider.upper()} HTTP {r.status_code}: {text[:200]}"))
                    return
                streaming = True
                parser = SSEParser()
                async for chunk in r.aiter_bytes():
                    for payload in parser.feed(chunk):
                        for ev in stream.feed(payload):
                            if ev.type == "usage":
                                ev = await self._charge(ev, price)
                                charged = True
                            yield _clean(ev)
                for payload in parser.close():
                    for ev in stream.feed(payload):
                        yield _clean(ev)
            for ev in stream.finish():
                if ev.type == "usage" and not charged:
                    ev = await self._charge(ev, price)
                    charged = True
                yield _clean(ev)
        except httpx.HTTPError as e:
            yield Event("error", kind="provider", text=f"{provider.upper()} {type(e).__name__}")
        finally:
            if streaming and not charged and not local and price is not None:
                # No usage arrived (cut off or stopped early): charge the worst case so the cap holds.
                await spend.add(self.db, max_tokens * price["output"] / 1e6)

    async def _charge(self, ev: Event, price: dict | None) -> Event:
        if ev.cost is None and price is not None:
            ev.cost = spend.cost(ev.prompt_tokens, ev.completion_tokens, price)
        await spend.add(self.db, ev.cost or 0.0)
        return ev

    # --- health ---
    async def ollama_status(self) -> tuple[str, str | None]:
        at, state, detail = self._ollama
        if time.monotonic() - at < OLLAMA_TTL:
            return state, detail
        try:
            r = await self.http.get(f"{self.ollama}/api/tags", timeout=0.3)
            r.raise_for_status()
            n = len(r.json().get("models") or [])
            state, detail = "OK", f"{n} MODEL{'S' if n != 1 else ''} AT {self.ollama}"
        except (httpx.HTTPError, ValueError):
            state, detail = "DOWN", f"NOTHING ANSWERS AT {self.ollama} (start Ollama to use local models)"
        self._ollama = (time.monotonic(), state, detail)
        return state, detail

    async def spend_status(self) -> dict:
        return {"today": round(await spend.today(self.db), 6), "cap": await spend.get_cap(self.db)}

    async def health(self) -> dict:
        rows = []
        for name in KEYED:
            st = await asyncio.to_thread(self.keys.status, name)
            rows.append({"name": name, "state": st["state"] if st["present"] else "KEY REQUIRED",
                         "detail": st["detail"] if st["present"] else
                         f"Set {keystore.KEY_SPECS[name].label} in APIKEYS"})
        state, detail = await self.ollama_status()
        rows.append({"name": "ollama", "state": state, "detail": detail})
        return {"providers": rows, "spend": await self.spend_status()}
