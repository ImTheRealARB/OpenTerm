"""Review sprint, area backend-ai: one test per bug found in openterm/llm, openterm/ai and openterm/kite. Nothing touches the network."""

import asyncio
import json

import httpx
import pytest
from test_phase16_agent import FakeGateway, Tools, call, collect, ok, run, text

from openterm import redact
from openterm.llm.events import Event

SECRET = "zzkeyvalue0123456789abcdef"


# --- tool registry: the allow-list must hold -----------------------------------------------------------------------------------------------
def _recording_app(paths, body=None):
    payload = json.dumps(body or {"data": {}}).encode()

    async def app(scope, receive, send):
        paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload})

    return app


def _call_tool(app, name, args):
    from openterm.ai.tools import ToolRunner

    async def go():
        runner = ToolRunner(app)
        try:
            return await runner.call(name, args)
        finally:
            await runner.aclose()

    return asyncio.run(go())


@pytest.mark.parametrize("name,args", [("backtest_get", {"run_id": "../../keys"}), ("backtest_get", {"run_id": "abc/../../keys"}),
                                       ("portfolio", {"name": "../keys"}), ("portfolio", {"name": "a/b"}), ("portfolio", {"name": "a?x=1"})])
def test_a_path_argument_cannot_walk_out_of_its_route(name, args):
    paths: list[str] = []
    res = _call_tool(_recording_app(paths), name, args)
    assert not res.ok and paths == [], "the model reached a route that is not in the tool allow-list"


def test_normal_path_arguments_still_work():
    paths: list[str] = []
    assert _call_tool(_recording_app(paths), "backtest_get", {"run_id": "0123456789abcdef"}).ok
    assert _call_tool(_recording_app(paths), "portfolio", {"name": "MY_PORT-1.2"}).ok
    assert paths == ["/api/bt/runs/0123456789abcdef", "/api/portfolios/MY_PORT-1.2"]


@pytest.mark.parametrize("name,args", [("filings", {"symbol": "AAPL", "form": 5}), ("rates", {"ccy": 5}), ("quote", {"symbols": ["AAPL"]}),
                                       ("history", {"symbol": {"a": 1}}), ("screener", {"limit": "many"})])
def test_a_wrongly_typed_argument_is_a_tool_error_not_a_crash(name, args):
    app = _recording_app([], {"data": {"filings": [{"form": "10-K"}], "columns": ["symbol"], "rows": []}})
    res = _call_tool(app, name, args)
    assert res.ok is False and res.error


# --- agent loop ----------------------------------------------------------------------------------------------------------------------------
def test_a_tool_runner_that_raises_does_not_end_the_stream():
    class Boom:
        async def __call__(self, name, args):
            raise RuntimeError(f"secret detail {SECRET}")

    gw = FakeGateway(call("quote", {"symbols": "AAPL"}), text("sorry, the tool failed"))
    ev = run(collect(gw, Boom()))
    res = next(e for e in ev if e["type"] == "tool_result")
    assert res["ok"] is False and SECRET not in json.dumps(ev)
    assert ev[-1]["type"] == "done" and ev[-1]["answer"] == "sorry, the tool failed"


def test_a_tool_call_without_an_id_still_gets_a_matching_tool_message():
    gw = FakeGateway([Event("tool_call", id=None, name="quote", args={"symbols": "AAPL"}), Event("done")], text("done"))
    ev = run(collect(gw, Tools(ok({"price": 1.5}))))
    second = gw.calls[1]["messages"]
    asst = next(m for m in second if m.get("tool_calls"))
    tool = next(m for m in second if m["role"] == "tool")
    assert asst["tool_calls"][0]["id"] and tool["tool_call_id"] == asst["tool_calls"][0]["id"]
    assert ev[-1]["type"] == "done"


class ClosableGateway(FakeGateway):
    """Records when a chat() stream is closed (its finally block ran)."""

    closed = 0

    async def chat(self, *a, **kw):
        try:
            async for e in super().chat(*a, **kw):
                yield e
        finally:
            ClosableGateway.closed += 1


def test_closing_the_agent_closes_the_gateway_stream_at_once():
    from openterm.ai import agent

    async def go():
        ClosableGateway.closed = 0
        gw = ClosableGateway(text("a", "b", "c"))
        events = agent.run(gw, Tools(), "q", [], model="m")
        assert (await events.__anext__())["type"] == "start"
        assert (await events.__anext__())["type"] == "token"
        await events.aclose()
        return ClosableGateway.closed  # no yield to the loop in between: a stream left to the garbage collector would not be closed yet

    assert asyncio.run(go()) == 1


def test_closing_the_audit_and_save_wrappers_closes_what_they_wrap():
    from openterm.ai import audit, routes_run

    async def inner(flag):
        try:
            yield {"type": "start"}
            yield {"type": "token", "text": "x"}
            yield {"type": "done", "answer": "x", "cost": 0.0}
        finally:
            flag.append(1)

    async def go():
        flag: list[int] = []
        wrapped = audit.audited(None, inner(flag), "chat", {"model": "m"}, "q")
        await wrapped.__anext__()
        await wrapped.aclose()
        flag2: list[int] = []
        saved = routes_run.save_events(None, inner(flag2), "swarm", "t", None, "done")
        await saved.__anext__()
        await saved.aclose()
        return flag, flag2

    a, b = asyncio.run(go())
    assert a == [1] and b == [1]


def test_a_run_store_failure_does_not_cut_the_answer(monkeypatch):
    from openterm.ai import routes_run

    class BadStore:
        async def save_run(self, *a):
            raise RuntimeError("disk full")

    monkeypatch.setattr(routes_run, "_store", lambda request: BadStore())

    async def inner():
        yield {"type": "start"}
        yield {"type": "done", "answer": "the answer", "cost": 0.0}

    async def go():
        return [e async for e in routes_run.save_events(None, inner(), "auto", "t", None, "done")]

    ev = asyncio.run(go())
    assert [e["type"] for e in ev] == ["start", "done"] and ev[-1]["answer"] == "the answer"


def test_a_generator_that_raises_ends_the_sse_stream_with_an_error_event():
    from openterm.ai.routes import _stream

    async def boom():
        yield {"type": "token", "text": "x"}
        raise RuntimeError(f"db exploded {SECRET}")

    async def go():
        resp = _stream(None, 0.0, boom())
        return b"".join([c async for c in resp.body_iterator])

    redact.register([SECRET])
    try:
        out = asyncio.run(go()).decode()
    finally:
        redact.unregister([SECRET])
    assert '"type":"error"' in out and SECRET not in out


# --- swarm ---------------------------------------------------------------------------------------------------------------------------------
def _swarm(gw, preset="COMMITTEE"):
    from test_phase16_swarm import RoleTools

    from openterm.ai import swarm

    async def go():
        return [e async for e in swarm.run(gw, lambda role: RoleTools(), swarm.PRESETS[preset], "AAPL")]

    return run(go())


@pytest.mark.parametrize("kind", ["spend_cap", "price_unknown", "invalid"])
def test_a_swarm_does_not_retry_or_continue_after_an_error_every_role_would_hit(kind):
    gw = FakeGateway([Event("error", kind=kind, text="NOPE")])
    ev = _swarm(gw)
    assert len(gw.calls) == 1 and not any(e["type"] == "role_retry" for e in ev)
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == kind and not any(e["type"] == "swarm_done" for e in ev)


def test_swarm_cost_counts_a_failed_attempt():
    failing = [Event("usage", prompt_tokens=10, completion_tokens=5, cost=0.5), Event("error", kind="provider", text="PROVIDER DOWN")]
    gw = FakeGateway(text("fund", cost=0.001), failing, text("tech", cost=0.001), text("risk", cost=0.001), text("chair", cost=0.001))
    ev = _swarm(gw)
    assert ev[-1]["cost"] == pytest.approx(0.504)


# --- gateway and stream parsers ------------------------------------------------------------------------------------------------------------
def test_parallel_tool_calls_that_all_say_index_zero_stay_separate_calls():
    from openterm.llm import openai_compat

    def chunk(delta, finish=None):
        return json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]})

    payloads = [
        chunk({"tool_calls": [{"index": 0, "id": "a", "function": {"name": "quote", "arguments": '{"symbols":"AAPL"}'}}]}),
        chunk({"tool_calls": [{"index": 0, "id": "b", "function": {"name": "quote", "arguments": '{"symbols":"MSFT"}'}}]}),
        chunk({}, "tool_calls"), "[DONE]"]
    calls = [e for e in openai_compat.events_from_payloads(payloads) if e.type == "tool_call"]
    assert [(c.id, c.args) for c in calls] == [("a", {"symbols": "AAPL"}), ("b", {"symbols": "MSFT"})]


def test_split_arguments_of_one_call_still_join():
    from openterm.llm import openai_compat

    def chunk(delta, finish=None):
        return json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]})

    payloads = [chunk({"tool_calls": [{"index": 0, "id": "a", "function": {"name": "quote", "arguments": '{"symb'}}]}),
                chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'ols":"AAPL"}'}}]}), chunk({}, "tool_calls")]
    calls = [e for e in openai_compat.events_from_payloads(payloads) if e.type == "tool_call"]
    assert [(c.id, c.args) for c in calls] == [("a", {"symbols": "AAPL"})]


def test_a_provider_error_in_the_middle_of_a_stream_is_redacted(tmp_path):
    from test_phase11 import _collect, _gateway, _run

    body = ("data: " + json.dumps({"error": {"message": f"Incorrect API key provided: {SECRET}"}}) + "\n\n").encode()
    make = _gateway(tmp_path, lambda r: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}),
                    keys_env={"OPENAI_API_KEY": SECRET})
    events = _run(make, lambda gw, db: _collect(gw, model="gpt-test", provider="openai", max_tokens=100))
    errs = [e for e in events if e.type == "error"]
    assert errs and all(SECRET not in e.text for e in errs)


# --- AI DOC --------------------------------------------------------------------------------------------------------------------------------
def test_doc_search_through_the_cached_index_gives_the_same_hits():
    from openterm.ai import doc

    chunks = [f"chunk {i} revenue grew {i} percent in segment {i % 7}\nrisk factors and litigation {i % 3}" for i in range(200)]
    d = doc.DocStore().add("x.txt", "text", chunks)
    for q in ("revenue growth segment 3", "litigation risk", "nothing matches zzzz", "the of and"):
        want = [(f"C{i + 1}", round(s, 3)) for i, s in doc.search(chunks, q, 5)]
        got = [(m["chunk"], m["score"]) for m in doc.doc_search(d, q, 5)["matches"]]
        assert got == want, q
    d.chunks.append("late addition about zebras")  # an edited chunk list must not serve a stale index
    assert doc.doc_search(d, "zebras", 1)["matches"][0]["chunk"] == "C201"


# --- Kite ----------------------------------------------------------------------------------------------------------------------------------
def test_kite_answer_that_is_not_a_json_object_is_a_data_error():
    from openterm.kite.client import KiteClient
    from openterm.service import DataError

    r = httpx.Response(200, json=["not", "an", "object"])
    with pytest.raises(DataError):
        KiteClient._json(r)


def test_a_swarm_fatal_error_after_earlier_roles_still_ends_with_swarm_done():
    gw = FakeGateway(text("fund", cost=0.001), [Event("error", kind="spend_cap", text="CAP")])
    ev = _swarm(gw)
    assert len(gw.calls) == 2 and not any(e["type"] == "role_retry" for e in ev)
    last = ev[-1]
    assert last["type"] == "swarm_done" and last["failed"] and last["roles"][0]["ok"] is True
    assert any(e["type"] == "role_error" and e["kind"] == "spend_cap" for e in ev)


def test_path_arguments_reject_a_trailing_newline_and_integers_accept_whole_floats():
    from openterm.ai import tools

    assert tools.PATH_ARGS["run_id"].match("abc123")
    assert not tools.PATH_ARGS["run_id"].match("abc123\n") and not tools.PATH_ARGS["name"].match("mine\n")
    assert not tools._wrong_type({"type": "integer"}, 10.0)
    assert tools._wrong_type({"type": "integer"}, 10.5)
