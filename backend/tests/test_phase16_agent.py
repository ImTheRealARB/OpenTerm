"""Phase 16 step 1: the AI agent core (spec: docs/specs/PHASE_16.md). Written before the code.

Pure parts (loop guard, context budget, grounding check, agent loop) run on a scripted fake gateway; the recorded OpenRouter turns
(fixtures/llm_tool_turn1.txt and llm_tool_turn2.txt, made with the real key by scripts/record_phase16.py) run through the REAL Gateway over a mock
transport. The route tests run inside the app so tools hit the app's own routes in-process. Nothing here touches the network.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from openterm.llm.events import Event

FIX = Path(__file__).parent / "fixtures"
SECRET = "sk-or-test-0123456789abcdefSECRET"
FORBIDDEN = ("order", "kite", "gtt", "margin", "holding", "trade", "buy", "sell")


# --- scripted gateway -----------------------------------------------------------------------------------------------------------------
class FakeGateway:
    """Each `chat()` call plays the next script entry (a list of Events). `calls` keeps what the agent sent."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def chat(self, messages, model, provider="openrouter", tools=None, max_tokens=1024, temperature=None):
        self.calls.append({"messages": json.loads(json.dumps(messages)), "model": model, "tools": tools})
        events = self.script.pop(0) if self.script else [Event("error", kind="provider", text="SCRIPT EXHAUSTED")]
        for e in events:
            yield e


def text(*parts, cost=0.001):
    return [*(Event("token", text=p) for p in parts), Event("usage", prompt_tokens=100, completion_tokens=20, cost=cost), Event("done")]


def call(name, args, cid="c1", cost=0.001):
    return [Event("tool_call", id=cid, name=name, args=args), Event("usage", prompt_tokens=100, completion_tokens=10, cost=cost), Event("done")]


class Tools:
    """Injected tool backend: returns the scripted ToolResult per call."""

    def __init__(self, *results):
        from openterm.ai.tools import ToolResult

        self.results = list(results)
        self.seen: list[tuple[str, dict]] = []
        self.make = ToolResult

    async def __call__(self, name, args):
        self.seen.append((name, args))
        return self.results.pop(0) if self.results else self.make(ok=True, text=json.dumps({"n": len(self.seen)}))


def ok(data, source="test:fixture", age=1.0):
    from openterm.ai.tools import ToolResult

    return ToolResult(ok=True, text=json.dumps(data), source=source, age_s=age)


def bad(msg="HTTP 500"):
    from openterm.ai.tools import ToolResult

    return ToolResult(ok=False, text=msg, error=msg)


def empty():
    from openterm.ai.tools import ToolResult

    return ToolResult(ok=True, text="{}", empty=True)


async def collect(gw, tools, question="q?", history=None, **kw):
    from openterm.ai import agent

    return [e async for e in agent.run(gw, tools, question, history or [], model="deepseek/deepseek-v4-pro", **kw)]


def run(coro):
    return asyncio.run(coro)


def types(events):
    return [e["type"] for e in events]


# --- tool registry ---------------------------------------------------------------------------------------------------------------------
def test_registry_is_read_only_with_schemas():
    from openterm.ai import tools

    assert {"quote", "history", "profile", "fa", "filings", "news", "screener", "research", "options_chain", "rates", "macro", "portfolio",
            "backtest_run", "backtest_get", "quant"} <= set(tools.REGISTRY)
    for name, t in tools.REGISTRY.items():
        assert t.description and t.parameters["type"] == "object"
        assert not any(w in name.lower() for w in FORBIDDEN), name
        assert t.method in ("GET", "POST") and (t.path.startswith("/api/") or t.local is not None)
        assert not any(w in t.path.lower() for w in FORBIDDEN), t.path
    specs = tools.openai_tools()
    assert all(s["type"] == "function" and s["function"]["parameters"]["type"] == "object" for s in specs)
    assert [s["function"]["name"] for s in tools.openai_tools(["quote"])] == ["quote"]


def test_validate_rejects_unknown_tools_missing_and_extra_args():
    from openterm.ai import tools

    assert tools.validate("quote", {"symbols": "AAPL"}) is None
    assert "UNKNOWN TOOL" in tools.validate("place_order", {})
    assert "symbols" in tools.validate("quote", {})
    assert "zzz" in tools.validate("quote", {"symbols": "AAPL", "zzz": 1})
    assert tools.validate("research", {"fn": "ee", "symbol": "AAPL"}) is None
    assert "fn" in tools.validate("research", {"fn": "omon", "symbol": "AAPL"})  # only the research allow-list


def test_shaping_keeps_history_small_and_numeric():
    from openterm.ai import tools

    n = 300
    env = {"data": {"symbol": "AAPL", "t": list(range(1_700_000_000, 1_700_000_000 + 86400 * n, 86400)), "c": [100.0 + i for i in range(n)],
                    "h": [101.0 + i for i in range(n)], "l": [99.0 + i for i in range(n)], "v": [1000] * n, "currency": "USD"},
           "source": "yahoo:fixture", "as_of": 1.0, "age_s": 2.5, "stale": False, "fallback_from": []}
    out = tools.REGISTRY["history"].shape(env, {"symbol": "AAPL", "range": "1y"})
    assert out["n_bars"] == 300 and out["last"]["close"] == 399.0 and out["first"]["close"] == 100.0
    assert out["high"] == 400.0 and out["low"] == 99.0 and abs(out["period_return_pct"] - 299.0) < 1e-6
    assert len(out["recent"]) == 10 and len(json.dumps(out)) < 3000


# --- loop guard ------------------------------------------------------------------------------------------------------------------------
def test_loop_guard_stops_after_three_failures_in_a_row_and_resets_on_success():
    from openterm.ai.guard import LoopGuard

    g = LoopGuard()
    assert g.after(ok=False, empty=False) is None and g.after(ok=True, empty=True) is None
    assert "3" in g.after(ok=False, empty=False)  # failed, empty, failed
    g = LoopGuard()
    g.after(ok=False, empty=False)
    g.after(ok=False, empty=False)
    assert g.after(ok=True, empty=False) is None  # a good result resets the count
    assert g.after(ok=False, empty=False) is None


def test_loop_guard_blocks_the_third_identical_call_whatever_the_key_order():
    from openterm.ai.guard import LoopGuard

    g = LoopGuard()
    assert g.before("quote", {"symbols": "AAPL", "x": 1}) is None
    assert g.before("quote", {"x": 1, "symbols": "AAPL"}) is None
    assert "REPEATED" in g.before("quote", {"symbols": "AAPL", "x": 1})
    assert g.before("quote", {"symbols": "MSFT"}) is None


# --- context budget --------------------------------------------------------------------------------------------------------------------
def test_truncate_keeps_head_and_tail_and_says_how_much_was_cut():
    from openterm.ai.context import truncate_text

    short = "x" * 100
    assert truncate_text(short, 6000) == short
    long = "H" * 4000 + "M" * 20000 + "T" * 4000
    out = truncate_text(long, 6000)
    assert len(out) <= 6200 and out.startswith("HHH") and out.endswith("TTT") and "CHARACTERS OMITTED" in out


def test_fit_drops_old_tool_results_first_then_old_turns_and_keeps_system_and_last_user():
    from openterm.ai.context import estimate_tokens, fit

    big = "z" * 40000
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "quote", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": big},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "b", "type": "function", "function": {"name": "quote", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "b", "content": "y" * 8000}]
    out = fit(msgs, budget=3000)
    assert estimate_tokens(out) <= 3000
    assert out[0]["content"] == "SYS" and any(m.get("content") == "second question" for m in out)
    tool_ids = {m["tool_call_id"] for m in out if m["role"] == "tool"}
    call_ids = {c["id"] for m in out for c in (m.get("tool_calls") or [])}
    assert tool_ids <= call_ids  # never a tool result without its call
    assert fit(msgs[:2], budget=3000) == msgs[:2]


# --- grounding -------------------------------------------------------------------------------------------------------------------------
def test_grounding_accepts_numbers_found_in_tool_results_in_any_common_form():
    from openterm.ai.ground import check

    results = [json.dumps({"price": 343.46, "change_pct": 0.4269, "ratio": 0.0123, "mcap": 4991209560000, "volume": 39767602})]
    answer = ("AAPL trades at $343.46 [T1], up 0.43% on the day, volume 39,767,602 and market cap about $4.99T. A 1.23% ratio. "
              "Filed 2026-10-16 in FY2025, see the 3 items.")
    assert check(answer, results) == []


def test_grounding_flags_numbers_no_tool_returned():
    from openterm.ai.ground import check

    out = check("AAPL is at 343.46 and will hit 512.80 by June, a 49.3% gain.", [json.dumps({"price": 343.46})])
    assert out == ["512.80", "49.3%"]


def test_grounding_ignores_citation_markers_years_and_small_counts():
    from openterm.ai.ground import check

    assert check("In 2024 and 2025, [T1] and [T2] show 2 rows, ranked 1. first.", [json.dumps({"a": 1})]) == []


# --- agent loop ------------------------------------------------------------------------------------------------------------------------
def test_no_tool_call_is_ungrounded_and_streams_tokens():
    gw = FakeGateway(text("Bonds ", "yield ", "is a rate."))
    ev = run(collect(gw, Tools()))
    assert types(ev)[0] == "start" and "token" in types(ev)
    done = ev[-1]
    assert done["type"] == "done" and done["grounded"] is False and done["label"] == "UNGROUNDED" and done["answer"] == "Bonds yield is a rate."
    assert done["tool_calls"] == 0 and done["cost"] == pytest.approx(0.001)
    assert ev[0]["model"] == "deepseek/deepseek-v4-pro" and gw.calls[0]["tools"]  # tools offered to the model


def test_tool_round_then_answer_is_grounded_and_costs_add_up():
    gw = FakeGateway(call("quote", {"symbols": "AAPL"}), text("AAPL is at 123.45 [T1]."))
    tools = Tools(ok({"price": 123.45}))
    ev = run(collect(gw, tools))
    tc = next(e for e in ev if e["type"] == "tool_call")
    tr = next(e for e in ev if e["type"] == "tool_result")
    assert tc["id"] == "T1" and tc["name"] == "quote" and tc["args"] == {"symbols": "AAPL"}
    assert tr["id"] == "T1" and tr["ok"] is True and tr["source"] == "test:fixture" and tr["age_s"] == 1.0
    done = ev[-1]
    assert done["grounded"] is True and done["label"] is None and done["unsourced"] == [] and done["tool_calls"] == 1
    assert done["cost"] == pytest.approx(0.002)
    sent = gw.calls[1]["messages"]  # the second round carries the assistant tool call and the tool result
    assert sent[-2]["tool_calls"][0]["id"] == "c1" and sent[-1] == {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"price": 123.45})}


def test_answer_with_an_invented_number_lists_it_as_unsourced():
    gw = FakeGateway(call("quote", {"symbols": "AAPL"}), text("AAPL is at 123.45 and targets 999.99."))
    done = run(collect(gw, Tools(ok({"price": 123.45}))))[-1]
    assert done["grounded"] is True and done["unsourced"] == ["999.99"]


def test_failed_tool_result_is_given_to_the_model_not_hidden():
    gw = FakeGateway(call("quote", {"symbols": "ZZZZ"}), text("No data came back."))
    ev = run(collect(gw, Tools(bad("NO DATA FOR ZZZZ"))))
    assert next(e for e in ev if e["type"] == "tool_result")["ok"] is False
    assert "NO DATA FOR ZZZZ" in gw.calls[1]["messages"][-1]["content"]


def test_loop_guard_stops_after_three_bad_calls_and_asks_for_a_final_answer_without_tools():
    gw = FakeGateway(call("quote", {"symbols": "A"}, "c1"), call("quote", {"symbols": "B"}, "c2"), call("quote", {"symbols": "C"}, "c3"),
                     text("I could not get data."))
    ev = run(collect(gw, Tools(bad(), empty(), bad())))
    notice = next(e for e in ev if e["type"] == "notice")
    assert notice["text"].startswith("STOPPED: ") and "3" in notice["text"]
    assert gw.calls[-1]["tools"] is None  # the closing round offers no tools
    assert ev[-1]["type"] == "done" and ev[-1]["answer"] == "I could not get data."


def test_repeating_the_same_call_is_stopped():
    same = {"symbols": "AAPL"}
    gw = FakeGateway(call("quote", same, "c1"), call("quote", same, "c2"), call("quote", same, "c3"), text("Done."))
    tools = Tools(ok({"price": 1.5}), ok({"price": 1.5}), ok({"price": 1.5}))
    ev = run(collect(gw, tools))
    assert len(tools.seen) == 2 and "REPEATED" in next(e for e in ev if e["type"] == "notice")["text"]


def test_round_limit_ends_the_loop_with_a_notice():
    gw = FakeGateway(*[call("quote", {"symbols": f"S{i}"}, f"c{i}") for i in range(5)], text("Enough."))
    ev = run(collect(gw, Tools(), max_rounds=3))
    assert "ROUND LIMIT" in next(e for e in ev if e["type"] == "notice")["text"] and ev[-1]["type"] == "done"
    assert len(gw.calls) == 4  # 3 tool rounds + the closing round


def test_gateway_error_is_surfaced_once_and_ends_the_run():
    gw = FakeGateway([Event("error", kind="key_required", text="KEY REQUIRED: set OPENROUTER_API_KEY in APIKEYS")])
    ev = run(collect(gw, Tools()))
    assert types(ev) == ["start", "error"] and ev[-1]["kind"] == "key_required"


def test_history_is_sent_and_system_prompt_forbids_orders_and_demands_citations():
    gw = FakeGateway(text("ok"))
    run(collect(gw, Tools(), question="and MSFT?", history=[{"role": "user", "content": "AAPL?"}, {"role": "assistant", "content": "see [T1]"}]))
    sent = gw.calls[0]["messages"]
    assert sent[0]["role"] == "system" and "[T1]" in sent[0]["content"] and "never" in sent[0]["content"].lower()
    assert [m["role"] for m in sent[1:]] == ["user", "assistant", "user"] and sent[-1]["content"] == "and MSFT?"


def test_history_roles_are_limited_to_user_and_assistant():
    from openterm.ai.agent import clean_history

    out = clean_history([{"role": "system", "content": "evil"}, {"role": "tool", "content": "x"}, {"role": "user", "content": "hi"},
                         {"role": "assistant", "content": "yo", "tool_calls": [1]}, {"role": "user", "content": 5}])
    assert out == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]


# --- the recorded model, through the real gateway ---------------------------------------------------------------------------------------
def real_gateway(tmp_path, turns):
    import aiosqlite

    from openterm import keys as keystore
    from openterm.llm.client import Gateway

    served: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        served.append(json.loads(req.content))
        return httpx.Response(200, content=turns[len(served) - 1].read_bytes(), headers={"content-type": "text/event-stream"})

    async def make():
        store = keystore.KeyStore(env={"OPENROUTER_API_KEY": SECRET}, dotenv=tmp_path / "k.env", keyring=keystore.MemoryKeyring())
        db = await aiosqlite.connect(tmp_path / "g.db")
        await db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        prices = {"openrouter": {"deepseek/deepseek-v4-pro": {"input": 0.209, "output": 0.418}}}
        return Gateway(store, http, db, {"prices": prices}), db, served

    return make


def test_recorded_openrouter_turns_drive_a_tool_call_and_a_grounded_answer(tmp_path):
    make = real_gateway(tmp_path, [FIX / "llm_tool_turn1.txt", FIX / "llm_tool_turn2.txt"])

    async def go():
        gw, db, served = await make()
        try:
            tools = Tools(ok({"AAPL": {"symbol": "AAPL", "price": 343.46, "prev_close": 342.0, "change": 1.46, "change_pct": 0.4269, "source": "yahoo:fixture"}}))
            ev = await collect(gw, tools, question="What is AAPL trading at?")
            return ev, tools, served
        finally:
            await gw.http.aclose()
            await db.close()

    ev, tools, served = run(go())
    assert tools.seen[0] == ("quote", {"symbols": "AAPL"})
    done = ev[-1]
    assert done["type"] == "done" and done["tool_calls"] == 1 and "343.46" in done["answer"] and done["unsourced"] == []
    assert done["cost"] > 0 and served[1]["messages"][-1]["role"] == "tool"
    assert SECRET not in json.dumps(ev) and SECRET not in json.dumps(served)


# --- the route (inside the app: tools call the app's own routes in-process) -------------------------------------------------------------
def sse(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def test_chat_route_without_a_key_says_key_required(client):
    r = client.post("/api/ai/chat", json={"question": "hi"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = sse(r)
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == "key_required" and "KEY REQUIRED" in ev[-1]["text"] and "OPENROUTER" in ev[-1]["text"]


def test_chat_route_runs_a_real_tool_against_the_app_and_never_leaks_the_key(client):
    client.app.state.llm = FakeGateway(call("quote", {"symbols": "AAPL"}), text("AAPL is at 343.46 [T1]."))
    client.put("/api/keys/openrouter", json={"fields": {"OPENROUTER_API_KEY": SECRET}})
    r = client.post("/api/ai/chat", json={"question": "AAPL?"})
    ev = sse(r)
    tr = next(e for e in ev if e["type"] == "tool_result")
    assert tr["ok"] is True and tr["source"].startswith("yahoo") and tr["age_s"] is not None
    done = ev[-1]
    assert done["type"] == "done" and done["grounded"] is True and done["unsourced"] == []
    assert SECRET not in r.text
    sent = json.dumps(client.app.state.llm.calls)
    assert "343.46" in sent  # the shaped quote reached the model


def test_chat_route_rejects_bad_bodies_and_non_loopback(client):
    assert client.post("/api/ai/chat", json={"question": ""}).status_code == 400
    assert client.post("/api/ai/chat", json={"question": "x" * 5000}).status_code == 400
    assert client.post("/api/ai/chat", json={"question": "hi", "model": "bad model!"}).status_code == 400
    from fastapi.testclient import TestClient

    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.post("/api/ai/chat", json={"question": "hi"}).status_code == 403


def test_tools_route_lists_the_registry_without_order_tools(client):
    r = client.get("/api/ai/tools")
    names = [t["name"] for t in r.json()["tools"]]
    assert "quote" in names and "quant" in names
    assert not any(w in n for n in names for w in FORBIDDEN)


def test_every_tool_runs_against_the_app_in_fixture_mode(client):
    """One scripted model calls each tool once; every call must reach the app's own route and come back shaped and small."""
    plan = [("quote", {"symbols": "AAPL,MSFT"}), ("history", {"symbol": "AAPL", "range": "1y"}), ("profile", {"symbol": "AAPL"}),
            ("fa", {"symbol": "AAPL"}), ("filings", {"symbol": "AAPL", "form": "10-K"}), ("news", {"symbol": "AAPL"}),
            ("screener", {"sector": "Tech", "limit": 5}), ("research", {"fn": "ee", "symbol": "AAPL"}), ("options_chain", {"symbol": "AAPL"}),
            ("rates", {}), ("macro", {"q": "cpi"}), ("portfolio", {}),
            ("backtest_run", {"symbols": ["SYN0001"], "rule": "SMA20>SMA50", "range": "2Y"}), ("quant", {"fn": "fact", "args": {"symbol": "AAPL"}})]
    one_round = [Event("tool_call", id=f"c{i}", name=n, args=a) for i, (n, a) in enumerate(plan)] + [Event("done")]
    client.app.state.llm = FakeGateway(one_round, text("done"))
    ev = sse(client.post("/api/ai/chat", json={"question": "tour"}))
    results = {e["name"]: e for e in ev if e["type"] == "tool_result"}
    assert set(results) == {n for n, _ in plan}, [e for e in ev if e["type"] in ("notice", "error")]
    bad_calls = {n: r["summary"] for n, r in results.items() if not r["ok"]}
    assert not bad_calls, bad_calls
    assert all(r["bytes"] <= 6300 for r in results.values())
    sent = client.app.state.llm.calls[-1]["messages"]
    assert [m for m in sent if m["role"] == "tool"], "tool results reach the model"
