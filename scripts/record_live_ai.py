"""Records one LIVE run each of AI, AI AUTO, SWARM and AI BT CODE through a running OpenTerm backend (release check).

Why this exists: the other recorders (record_llm.py, record_phase16.py) call OpenRouter directly. This one sends the
same requests the panels send (`functions/AI.tsx`, `functions/SWARM.tsx`) to the app's own routes, so the recording is
the app's real event stream: tool calls, grounding, evidence, the BT code draft and the final `done` event.

Run from backend/ while the app runs on port 8000 (`.\\scripts\\start.ps1 -NoBrowser`):
    uv run python ../scripts/record_live_ai.py ai auto swarm btcode     # any subset, in that order

It uses the provider and model in the app's settings (set with `SETTINGS AI PROVIDER ...` / `SETTINGS AI MODEL ...`)
and refuses to run unless the provider is the one named by --provider (default opencodego), so a run never spends a
different provider's quota by accident.

Output: docs/live-runs/<date>-<provider>/<fn>.sse.txt. Each file is valid SSE: its first lines are SSE comments
(lines starting with ":") that label it LIVE, with provider, model, route, request body and timings. A recording that
contains the API key is discarded (the key is read from the key store only for that check; it is never printed).
These files are evidence for HANDOFF/CHANGELOG, NOT test fixtures: tests never read them.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from openterm.config import get_settings
from openterm.keys import KEY_SPECS, from_settings

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"  # 127.0.0.1, not localhost: uvicorn listens on IPv4 only

# One prompt per function. Kept small so each run spends as little quota as the function allows.
RUNS = {
    "ai": ("/api/ai/chat", lambda m, p: {"question": "What is AAPL trading at, and how much did it move today?", "history": [], "model": m, "provider": p}),
    "auto": ("/api/ai/auto", lambda m, p: {"hypothesis": "Holding SPY only while it closes above its 200-day moving average beat buy-and-hold over the last 10 years.",
                                          "model": m, "provider": p}),
    "swarm": ("/api/ai/swarm", lambda m, p: {"preset": "COMMITTEE", "subject": "AAPL", "model": m, "provider": p}),
    "btcode": ("/api/ai/bt_code", lambda m, p: {"idea": "Buy when the 20-day SMA crosses above the 50-day SMA; sell when it crosses back below.",
                                               "model": m, "provider": p}),
}


def secrets_for(provider: str) -> list[str]:
    """The provider's key values, only to make sure none of them landed in a recording. Never printed."""
    values = from_settings(get_settings()).get(provider) or {}
    return [v for f in KEY_SPECS[provider].fields if (v := values.get(f))]


def summarize(events: list[dict]) -> dict:
    """Counts and the facts HANDOFF needs: did it finish, was it grounded, which tools ran, any error."""
    types: dict[str, int] = {}
    tools: list[str] = []
    for e in events:
        types[e.get("type", "?")] = types.get(e.get("type", "?"), 0) + 1
        name = e.get("name") or e.get("tool")
        if e.get("type") in ("tool_call", "tool") and name:
            tools.append(name)
    done = next((e for e in reversed(events) if e.get("type") in ("done", "swarm_done")), None)
    err = next((e for e in events if e.get("type") == "error"), None)
    return {"types": types, "tools": tools, "finished": done is not None,
            "grounded": done.get("grounded") if done else None, "label": done.get("label") if done else None,
            "error": err.get("text") if err else None,
            "answer_start": ((done or {}).get("answer") or "")[:160]}


async def record(http: httpx.AsyncClient, fn: str, model: str, provider: str, out_dir: Path, secrets: list[str]) -> bool:
    route, make = RUNS[fn]
    body = make(model, provider)
    t0 = time.perf_counter()
    raw = b""
    first_ms = None
    async with http.stream("POST", BASE + route, json=body) as r:
        async for chunk in r.aiter_bytes():
            if first_ms is None:
                first_ms = (time.perf_counter() - t0) * 1000
            raw += chunk
    total_s = time.perf_counter() - t0
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if any(s in text for s in secrets):
        print(f"{fn}: the key appeared in the stream; nothing written")
        return False
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    summary = summarize(events)
    label = [
        f": LIVE RECORDING (not a fixture, not synthetic) of OpenTerm {fn.upper()} on {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f": provider {provider} | model {model} | route POST {route} | HTTP {r.status_code}",
        f": request body {json.dumps(body)}",
        f": first byte {first_ms or 0:.0f} ms | total {total_s:.1f} s | events {len(events)} | finished {summary['finished']} | error {summary['error']}",
        ": recorded by scripts/record_live_ai.py; model output is model output, not data",
        "",
    ]
    out = out_dir / f"{fn}.sse.txt"
    out.write_bytes(("\n".join(label) + "\n" + text).encode("utf-8"))
    print(f"{fn}: HTTP {r.status_code}, {total_s:.1f} s, {json.dumps(summary)}")
    print(f"   -> {out.relative_to(ROOT)}")
    return r.status_code == 200 and summary["finished"] and not summary["error"]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fns", nargs="+", choices=list(RUNS))
    ap.add_argument("--provider", default="opencodego", help="the provider the app's settings must name")
    a = ap.parse_args()
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0)) as http:
        ai = ((await http.get(BASE + "/api/settings")).json().get("settings") or {}).get("ai") or {}
        model, provider = ai.get("model"), ai.get("provider")
        if provider != a.provider:
            print(f"the app's AI provider is {provider!r}, not {a.provider!r}: run `SETTINGS AI PROVIDER {a.provider.upper()}` first")
            return 1
        secrets = secrets_for(provider)
        if not secrets:
            print(f"no key for {provider} in the key store: type it in APIKEYS first")
            return 1
        out_dir = ROOT / "docs" / "live-runs" / f"{time.strftime('%Y-%m-%d')}-{provider}"
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = [await record(http, fn, model, provider, out_dir, secrets) for fn in a.fns]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
