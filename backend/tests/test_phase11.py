"""Phase 11: key store + redaction + KEY REQUIRED, job runner, LLM gateway (spec: docs/specs/PHASE_11.md).

Written before the code; every build step has landed and the strict-xfail markers are gone.
Modules are imported inside the tests so a missing module fails one test, not the whole collection.
"""

import asyncio
import importlib
import logging
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

SECRET = "sk-test-0123456789abcdefSECRET"
SPEC_NAMES = {"openrouter", "openai", "anthropic", "finnhub", "alpaca", "fmp", "fred", "eia", "openfigi", "tradier",
              "telegram", "smtp", "kite"}


def mod(name: str):
    return importlib.import_module(name)


def make_client(monkeypatch, tmp_path, **env) -> TestClient:
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_SYNTHETIC", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "p11.db"))
    monkeypatch.setenv("OPENTERM_KEYRING", "memory")
    monkeypatch.setenv("OPENTERM_DOTENV_PATH", str(tmp_path / "keys.env"))
    monkeypatch.setenv("OPENTERM_JOB_WORKERS", "2")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from openterm.config import get_settings

    get_settings.cache_clear()
    from openterm.main import app

    return TestClient(app, client=("127.0.0.1", 50000))


# --- 1. Key store -----------------------------------------------------------------------------------------------

def test_key_specs_cover_the_roadmap_table():
    keys = mod("openterm.keys")
    assert set(keys.KEY_SPECS) == SPEC_NAMES
    assert keys.KEY_SPECS["alpaca"].fields == ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY")
    assert keys.KEY_SPECS["fred"].fields == ("FRED_API_KEY",)  # Phase 7's env name keeps working
    for spec in keys.KEY_SPECS.values():
        assert spec.purpose and spec.phase >= 11 or spec.name == "fred"
        assert spec.signup.startswith("https://")


def test_lookup_order_env_then_keyring_then_dotenv(tmp_path):
    keys = mod("openterm.keys")
    dotenv = tmp_path / "keys.env"
    dotenv.write_bytes(b"# mine\nFINNHUB_API_KEY=from-dotenv-123456\nOTHER=1\n")
    ring = keys.MemoryKeyring()
    store = keys.KeyStore(env={}, dotenv=dotenv, keyring=ring)
    assert store.get("finnhub") == {"FINNHUB_API_KEY": "from-dotenv-123456"}
    assert store.status("finnhub")["source"] == "dotenv"

    store.set("finnhub", {"FINNHUB_API_KEY": "from-keyring-123456"})
    assert store.get("finnhub") == {"FINNHUB_API_KEY": "from-keyring-123456"}
    assert store.status("finnhub")["source"] == "keyring"

    env_store = keys.KeyStore(env={"FINNHUB_API_KEY": "from-env-123456"}, dotenv=dotenv, keyring=ring)
    assert env_store.get("finnhub") == {"FINNHUB_API_KEY": "from-env-123456"}
    assert env_store.status("finnhub")["source"] == "env"


def test_status_never_contains_the_value(tmp_path):
    keys = mod("openterm.keys")
    store = keys.KeyStore(env={}, dotenv=tmp_path / "k.env", keyring=keys.MemoryKeyring())
    assert store.status("openrouter")["state"] == "MISSING" and store.status("openrouter")["present"] is False
    store.set("openrouter", {"OPENROUTER_API_KEY": SECRET})
    st = store.status("openrouter")
    assert st["present"] is True and st["state"] == "UNTESTED"
    assert SECRET not in repr(st) and SECRET[-4:] not in repr(st)
    assert SECRET in store.secrets()


def test_env_keys_are_locked(tmp_path):
    keys = mod("openterm.keys")
    store = keys.KeyStore(env={"FRED_API_KEY": "env-value-123456"}, dotenv=tmp_path / "k.env",
                          keyring=keys.MemoryKeyring())
    for action in (lambda: store.set("fred", {"FRED_API_KEY": "x" * 12}), lambda: store.delete("fred")):
        with pytest.raises(keys.KeyStoreError) as e:
            action()
        assert e.value.kind == "env_locked"
    with pytest.raises(keys.KeyStoreError) as e:
        store.set("nope", {"X": "y" * 12})
    assert e.value.kind == "unknown_provider"
    with pytest.raises(keys.KeyStoreError) as e:
        store.set("finnhub", {"WRONG_FIELD": "y" * 12})
    assert e.value.kind == "bad_request"


def test_no_keyring_backend_writes_dotenv_keeping_other_lines(tmp_path):
    keys = mod("openterm.keys")
    dotenv = tmp_path / "k.env"
    dotenv.write_bytes(b"# comment\nSEC_USER_AGENT=me\nFMP_API_KEY=old-value-123\n")
    store = keys.KeyStore(env={}, dotenv=dotenv, keyring=None)
    store.set("fmp", {"FMP_API_KEY": "new-value-123"})
    store.set("eia", {"EIA_API_KEY": "eia-value-123"})
    assert dotenv.read_bytes() == b"# comment\nSEC_USER_AGENT=me\nFMP_API_KEY=new-value-123\nEIA_API_KEY=eia-value-123\n"
    store.delete("fmp")
    assert dotenv.read_bytes() == b"# comment\nSEC_USER_AGENT=me\nEIA_API_KEY=eia-value-123\n"
    assert store.status("eia")["source"] == "dotenv"


@pytest.mark.parametrize("status, body, state", [
    (200, '{"data": {}}', "OK"),
    (401, '{"error": "Invalid API key"}', "INVALID"),
    (403, "Forbidden", "INVALID"),
    (429, '{"error": "API limit reached"}', "QUOTA"),
    (200, '{"Error Message": "Limit Reach. Please upgrade your plan"}', "QUOTA"),
    (500, "oops", "ERROR"),
])
def test_classify_test_responses(status, body, state):
    assert mod("openterm.keys").classify(status, body) == state


def test_keyring_is_not_imported_at_startup(monkeypatch, tmp_path):
    import sys

    monkeypatch.delitem(sys.modules, "keyring", raising=False)
    with make_client(monkeypatch, tmp_path, OPENTERM_KEYRING="auto") as c:
        assert c.get("/api/health").status_code == 200
        assert "keyring" not in sys.modules


# --- Redaction --------------------------------------------------------------------------------------------------

def test_redact_known_secrets_and_common_shapes():
    redact = mod("openterm.redact").redact
    assert redact(f"GET https://x/q?symbol=A&token={SECRET} 401", {SECRET}) == "GET https://x/q?symbol=A&token=*** 401"
    assert SECRET not in redact(f"failed: {SECRET}", {SECRET})
    assert redact("Authorization: Bearer abcdefgh12345678", set()) == "Authorization: Bearer ***"
    assert redact("https://h/p?apikey=zz9988776655&x=1", set()) == "https://h/p?apikey=***&x=1"
    assert redact("https://h/p?api_key=zz9988776655", set()) == "https://h/p?api_key=***"
    assert redact("key sk-or-v1-abcdef0123456789 used", set()) == "key *** used"
    assert redact("short ab12 stays", {"ab12"}) == "short ab12 stays"  # < 8 chars is never treated as a secret


# --- /api/keys --------------------------------------------------------------------------------------------------

def test_api_keys_roundtrip_without_values(client):
    r = client.get("/api/keys")
    assert r.status_code == 200
    rows = {row["name"]: row for row in r.json()["keys"]}
    assert set(rows) == SPEC_NAMES and rows["finnhub"]["state"] == "MISSING"

    r = client.put("/api/keys/finnhub", json={"fields": {"FINNHUB_API_KEY": SECRET}})
    assert r.status_code == 200, r.text
    # Fixture mode replays Finnhub's real 401 body for an unknown key.
    assert r.json()["state"] == "INVALID" and r.json()["source"] == "keyring"
    assert r.json()["checked_at"] > 0
    assert SECRET not in r.text

    r = client.post("/api/keys/finnhub/test")
    assert r.status_code == 200 and r.json()["state"] == "INVALID" and SECRET not in r.text
    assert client.get("/api/keys").json()["keys"] and SECRET not in client.get("/api/keys").text

    assert client.delete("/api/keys/finnhub").status_code == 200
    rows = {row["name"]: row for row in client.get("/api/keys").json()["keys"]}
    assert rows["finnhub"]["state"] == "MISSING"


def test_api_keys_openrouter_ok_from_doc_shaped_fixture(client):
    r = client.put("/api/keys/openrouter", json={"fields": {"OPENROUTER_API_KEY": SECRET}})
    assert r.status_code == 200 and r.json()["state"] == "OK", r.text


def test_api_keys_errors(client):
    assert client.put("/api/keys/nope", json={"fields": {"X": "y" * 12}}).status_code == 404
    assert client.put("/api/keys/finnhub", json={"fields": {"WRONG": "y" * 12}}).status_code == 400
    assert client.put("/api/keys/finnhub", json={"nope": 1}).status_code == 400


def test_env_key_cannot_be_changed_from_the_api(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path, FRED_API_KEY="env-fred-0123456789") as c:
        rows = {row["name"]: row for row in c.get("/api/keys").json()["keys"]}
        assert rows["fred"]["source"] == "env" and rows["fred"]["present"] is True
        r = c.put("/api/keys/fred", json={"fields": {"FRED_API_KEY": "x" * 16}})
        assert r.status_code == 409 and r.json()["kind"] == "env_locked"
        assert "env-fred-0123456789" not in c.get("/api/keys").text


def test_key_writes_only_from_loopback(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as c:
        remote = TestClient(c.app, client=("10.1.2.3", 40000))
        assert remote.get("/api/keys").status_code == 200
        assert remote.put("/api/keys/fmp", json={"fields": {"FMP_API_KEY": SECRET}}).status_code == 403
        assert remote.delete("/api/keys/fmp").status_code == 403


def test_secret_never_leaks_into_logs_perf_sources_or_errors(client):
    assert client.put("/api/keys/finnhub", json={"fields": {"FINNHUB_API_KEY": SECRET}}).status_code == 200
    logging.getLogger("openterm.test").warning("calling https://finnhub.io/api/v1/quote?token=%s", SECRET)
    logging.getLogger("httpx").info("HTTP Request: GET https://finnhub.io/api/v1/quote?token=%s", SECRET)

    yahoo = client.app.state.service.router.providers["yahoo"]

    async def boom(*_a, **_k):
        raise mod("openterm.providers.base").ProviderError("unavailable", f"GET https://x/?token={SECRET} failed")

    yahoo.history = boom
    client.app.state.service.router.providers["nasdaq"].history = boom
    err = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y"})
    assert err.status_code >= 400

    for body in (err.text, client.get("/api/log").text, client.get("/api/perf").text,
                 client.get("/api/sources").text, client.get("/api/keys").text):
        assert SECRET not in body


# --- KEY REQUIRED -----------------------------------------------------------------------------------------------

class _Keyed(mod("openterm.providers.base").Provider):
    name = "keyedonly"
    key_name = "FINNHUB"
    capabilities = frozenset({"estimates"})

    async def estimates(self, symbol):
        raise mod("openterm.providers.base").ProviderError("key_required", "FINNHUB_API_KEY is not set")


class _Keyless(mod("openterm.providers.base").Provider):
    name = "keyless"
    capabilities = frozenset({"estimates"})

    async def estimates(self, symbol):
        return {"symbol": symbol}


def _router(*providers):
    router = mod("openterm.router")
    http = httpx.AsyncClient()
    ps = {p.name: p(http) for p in providers}
    return router.Router(ps, {"estimates": [p.name for p in providers]}), router


def test_router_reports_key_required_when_only_keyed_providers_exist():
    r, router = _router(_Keyed)
    with pytest.raises(router.AllFailed) as e:
        asyncio.run(r.call("estimates", lambda p: p.estimates("AAPL")))
    assert e.value.kind == "key_required" and str(e.value) == "KEY REQUIRED" and e.value.key == "FINNHUB"


def test_router_falls_through_to_keyless_provider():
    r, _ = _router(_Keyed, _Keyless)
    for _ in range(5):
        result, failed = asyncio.run(r.call("estimates", lambda p: p.estimates("AAPL")))
    assert result == {"symbol": "AAPL"} and failed == ["keyedonly"]
    assert not r.health["keyedonly"].down  # a missing key is not an outage: no circuit-breaker strike


def test_key_required_envelope_is_424():
    import orjson

    from openterm.api import error
    from openterm.service import DataError

    resp = error(DataError("key_required", "KEY REQUIRED", key="FINNHUB"))
    assert resp.status_code == 424
    assert orjson.loads(resp.body) == {"error": "KEY REQUIRED", "kind": "key_required", "key": "FINNHUB",
                                      "detail": "KEY REQUIRED: set FINNHUB in APIKEYS"}


def test_sources_keyed_rows_come_from_the_key_store(client):
    keyed = {k["name"]: k for k in client.get("/api/sources").json()["keyed"]}
    assert keyed["openrouter"]["status"] == "KEY REQUIRED" and "APIKEYS" in keyed["openrouter"]["note"]
    assert keyed["stooq"]["status"] == "RETIRED"
    client.put("/api/keys/finnhub", json={"fields": {"FINNHUB_API_KEY": SECRET}})
    keyed = {k["name"]: k for k in client.get("/api/sources").json()["keyed"]}
    assert keyed["finnhub"]["status"] == "INVALID"


# --- 2. Jobs ----------------------------------------------------------------------------------------------------

def _wait(client, job_id, states=("done", "error", "cancelled"), timeout=30.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in states:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


def test_job_hash_is_stable_and_order_free():
    h = mod("openterm.jobs").job_hash
    assert h("sleep", "1", {"a": 1, "b": [1, 2]}) == h("sleep", "1", {"b": [1, 2], "a": 1})
    assert h("sleep", "1", {"a": 1}) != h("sleep", "2", {"a": 1})
    assert h("sleep", "1", {"a": 1}, "fp1") != h("sleep", "1", {"a": 1}, "fp2")


def test_dummy_job_streams_progress_and_caches(client):
    with client.websocket_connect("/ws") as ws:
        r = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 5, "step_ms": 20}})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["kind"] == "sleep" and job["state"] in ("queued", "running") and job["cached"] is False
        progress, final = [], None
        for _ in range(200):
            frame = ws.receive_json()
            if frame[0] == "J" and frame[1]["id"] == job["id"]:
                progress.append(frame[1]["progress"])
                if frame[1]["state"] == "done":
                    final = frame[1]
                    break
        assert final is not None and progress == sorted(progress) and progress[-1] == 1.0
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["state"] == "done" and done["result"]["steps"] == 5 and done["label"] == "TEST JOB"

    t0 = time.perf_counter()
    again = client.post("/api/jobs", json={"kind": "sleep", "params": {"step_ms": 20, "steps": 5}}).json()
    assert (time.perf_counter() - t0) < 0.2  # bench gates the 20 ms server-side budget; this only catches a rerun
    assert again["cached"] is True and again["state"] == "done" and again["result"]["steps"] == 5


def test_identical_running_jobs_coalesce(client):
    a = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 20, "step_ms": 50}}).json()
    b = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 20, "step_ms": 50}}).json()
    assert a["id"] == b["id"]
    client.delete(f"/api/jobs/{a['id']}")


def test_cooperative_cancel(client):
    job = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 400, "step_ms": 50}}).json()
    _wait(client, job["id"], states=("running",))
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert _wait(client, job["id"], timeout=5)["state"] == "cancelled"


def test_hard_cancel_kills_and_respawns_the_worker(client):
    job = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 1, "step_ms": 60000,
                                                                     "ignore_cancel": True}}).json()
    _wait(client, job["id"], states=("running",))
    t0 = time.monotonic()
    client.delete(f"/api/jobs/{job['id']}")
    assert _wait(client, job["id"], timeout=8)["state"] == "cancelled"
    assert time.monotonic() - t0 >= 1.5  # waited for the cooperative stop first
    nxt = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 2, "step_ms": 10, "tag": "after"}}).json()
    assert _wait(client, nxt["id"])["state"] == "done"


def test_failing_and_crashing_jobs(client):
    fail = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 5, "step_ms": 5, "fail_at": 2}}).json()
    got = _wait(client, fail["id"])
    assert got["state"] == "error" and "fail_at" in got["error"]

    crash = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 5, "step_ms": 5, "crash_at": 1}}).json()
    got = _wait(client, crash["id"])
    assert got["state"] == "error" and got["error"] == "WORKER DIED"
    ok = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 2, "step_ms": 5, "tag": "ok"}}).json()
    assert _wait(client, ok["id"])["state"] == "done"


def test_job_api_errors_and_listing(client):
    assert client.post("/api/jobs", json={"kind": "nope", "params": {}}).status_code == 400
    assert client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": "x"}}).status_code == 400
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    job = client.post("/api/jobs", json={"kind": "sleep", "params": {"steps": 1, "step_ms": 1, "tag": "list"}}).json()
    _wait(client, job["id"])
    rows = client.get("/api/jobs").json()["jobs"]
    assert any(r["id"] == job["id"] for r in rows) and all("result" not in r for r in rows)


def test_job_store_trims_to_200(tmp_path):
    from openterm.db import migrate, open_db

    JobStore = mod("openterm.jobs.store").JobStore

    async def go():
        db = await open_db(tmp_path / "j.db")
        await migrate(db)
        store = JobStore(db)
        for i in range(205):
            await store.save({"id": f"j{i}", "kind": "sleep", "hash": f"h{i}", "state": "done", "params": {},
                              "result": {"i": i}, "error": None, "created_at": i, "started_at": i, "finished_at": i})
        await store.trim(keep=200)
        n = await store.count()
        oldest = await store.get("j4")
        await db.close()
        return n, oldest

    n, oldest = asyncio.run(go())
    assert n == 200 and oldest is None


# --- 3. LLM gateway ---------------------------------------------------------------------------------------------

OPENAI_CHUNKS = [
    b'data: {"choices":[{"delta":{"role":"assistant","content":"Hel"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\ndata: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",',
    b'"type":"function","function":{"name":"quote","arguments":"{\\"sym"}}]}}]}\n\n',
    b': keep-alive comment\n\n',
    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"bol\\": \\"AAPL\\"}"}}]}}]}\n\n',
    (b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
     b'"usage":{"prompt_tokens":12,"completion_tokens":7,"cost":0.00042}}\n\n'),
    b"data: [DONE]\n\n",
]


def test_sse_parser_handles_split_chunks_and_comments():
    payloads = mod("openterm.llm.sse").parse_sse(OPENAI_CHUNKS)
    assert payloads[0].startswith('{"choices"') and payloads[-1] == "[DONE]" and len(payloads) == 6


def test_openai_compatible_events():
    llm = mod("openterm.llm.openai_compat")
    events = list(llm.events_from_payloads(mod("openterm.llm.sse").parse_sse(OPENAI_CHUNKS)))
    kinds = [e.type for e in events]
    assert "".join(e.text for e in events if e.type == "token") == "Hello"
    call = next(e for e in events if e.type == "tool_call")
    assert call.id == "c1" and call.name == "quote" and call.args == {"symbol": "AAPL"}
    usage = next(e for e in events if e.type == "usage")
    assert usage.prompt_tokens == 12 and usage.completion_tokens == 7 and usage.cost == pytest.approx(0.00042)
    assert kinds[-1] == "done"


ANTHROPIC_PAYLOADS = [
    '{"type":"message_start","message":{"usage":{"input_tokens":20,"output_tokens":1}}}',
    '{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
    '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}',
    '{"type":"content_block_stop","index":0}',
    '{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"t1","name":"quote","input":{}}}',
    '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"symbol\\":"}}',
    '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":" \\"MSFT\\"}"}}',
    '{"type":"content_block_stop","index":1}',
    '{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":15}}',
    '{"type":"message_stop"}',
]


def test_anthropic_events_map_to_the_same_shape():
    events = list(mod("openterm.llm.anthropic").events_from_payloads(ANTHROPIC_PAYLOADS))
    assert "".join(e.text for e in events if e.type == "token") == "Hi"
    call = next(e for e in events if e.type == "tool_call")
    assert call.id == "t1" and call.name == "quote" and call.args == {"symbol": "MSFT"}
    usage = next(e for e in events if e.type == "usage")
    assert usage.prompt_tokens == 20 and usage.completion_tokens == 15 and usage.cost is None
    assert events[-1].type == "done"


def test_recorded_openrouter_stream_gives_tokens_usage_and_cost():
    # One real streamed answer (raw SSE text), recorded in step 5 with the OpenRouter key.
    raw = (Path(__file__).parent / "fixtures" / "llm_openrouter_stream.txt").read_bytes().decode("utf-8")
    llm = mod("openterm.llm.openai_compat")
    events = list(llm.events_from_payloads(mod("openterm.llm.sse").parse_sse([raw.encode()])))
    assert any(e.type == "token" and e.text for e in events)
    usage = next(e for e in events if e.type == "usage")
    assert usage.completion_tokens > 0 and usage.cost is not None and events[-1].type == "done"


def test_spend_cap_and_cost():
    spend = mod("openterm.llm.spend")
    price = {"input": 3.0, "output": 15.0}  # US$ per million tokens
    assert spend.check(spent=0.0, cap=1.0, max_tokens=1000, price=price, local=False) is None
    assert spend.check(spent=0.995, cap=1.0, max_tokens=1000, price=price, local=False) == "SPEND CAP REACHED"
    assert spend.check(spent=0.0, cap=1.0, max_tokens=1000, price=None, local=False) == "PRICE UNKNOWN"
    assert spend.check(spent=5.0, cap=1.0, max_tokens=1000, price=None, local=True) is None
    assert spend.cost(prompt_tokens=1_000_000, completion_tokens=100_000, price=price) == pytest.approx(4.5)


def test_spend_is_stored_per_day(client):
    spend = mod("openterm.llm.spend")
    db = client.app.state.userdata.db

    async def go():
        await spend.add(db, 0.25, day="2026-10-18")
        await spend.add(db, 0.10, day="2026-10-18")
        return await spend.today(db, day="2026-10-18"), await spend.today(db, day="2026-10-19")

    today, tomorrow = client.portal.call(go)  # the db connection belongs to the app's event loop
    assert today == pytest.approx(0.35) and tomorrow == 0.0


def test_llm_health_without_keys(client):
    r = client.get("/api/llm/health")
    assert r.status_code == 200
    rows = {x["name"]: x for x in r.json()["providers"]}
    assert rows["openrouter"]["state"] == "KEY REQUIRED" and rows["anthropic"]["state"] == "KEY REQUIRED"
    assert rows["ollama"]["state"] == "DOWN"  # nothing listens on 127.0.0.1:11434 in fixture mode
    assert r.json()["spend"] == {"today": 0.0, "cap": 1.0}
    keyed = {k["name"]: k for k in client.get("/api/sources").json()["keyed"]}
    assert keyed["ollama"]["status"] == "DOWN"


# --- 3b. Gateway end to end (added in step 5; mocked transport, no network) ---

def _gateway(tmp_path, handler, keys_env=None):
    import aiosqlite

    client_mod, keys = mod("openterm.llm.client"), mod("openterm.keys")
    store = keys.KeyStore(env=keys_env or {}, dotenv=tmp_path / "k.env", keyring=keys.MemoryKeyring())

    async def make():
        db = await aiosqlite.connect(tmp_path / "g.db")
        await db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        prices = {"openai": {"gpt-test": {"input": 1.0, "output": 2.0}}}
        return client_mod.Gateway(store, http, db, {"prices": prices}), db

    return make


def _run(make, fn):
    async def go():
        gw, db = await make()
        try:
            return await fn(gw, db)
        finally:
            await gw.http.aclose()
            await db.close()

    return asyncio.run(go())


async def _collect(gw, **kw):
    return [e async for e in gw.chat([{"role": "user", "content": "hi"}], **kw)]


def test_gateway_key_required_before_any_call(tmp_path):
    calls = []
    make = _gateway(tmp_path, lambda r: calls.append(r) or httpx.Response(500))
    events = _run(make, lambda gw, db: _collect(gw, model="x/y"))
    assert [e.type for e in events] == ["error"] and events[0].kind == "key_required"
    assert "OPENROUTER" in events[0].text and calls == []


def test_gateway_streams_and_charges_the_real_cost(tmp_path):
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["auth"] = r.headers.get("authorization")
        seen["body"] = r.content
        return httpx.Response(200, content=b"".join(OPENAI_CHUNKS), headers={"content-type": "text/event-stream"})

    make = _gateway(tmp_path, handler, keys_env={"OPENAI_API_KEY": SECRET})

    async def fn(gw, db):
        events = await _collect(gw, model="gpt-test", provider="openai", max_tokens=100)
        return events, await mod("openterm.llm.spend").today(db)

    events, spent = _run(make, fn)
    assert "".join(e.text for e in events if e.type == "token") == "Hello" and events[-1].type == "done"
    assert seen["auth"] == f"Bearer {SECRET}" and b'"include_usage":true' in seen["body"]
    assert spent == pytest.approx(0.00042)  # the provider's own cost wins over the price table


def test_gateway_refuses_over_the_cap_and_maps_401(tmp_path):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(401, json={"error": {"message": f"bad key {SECRET}"}})

    make = _gateway(tmp_path, handler, keys_env={"OPENAI_API_KEY": SECRET})

    async def fn(gw, db):
        spend = mod("openterm.llm.spend")
        await spend.set_cap(db, 0.0)
        refused = await _collect(gw, model="gpt-test", provider="openai")
        unknown = await _collect(gw, model="gpt-unpriced", provider="openai")
        await spend.set_cap(db, 1.0)
        bad = await _collect(gw, model="gpt-test", provider="openai")
        return refused, unknown, bad, await spend.today(db)

    refused, unknown, bad, spent = _run(make, fn)
    assert refused[0].kind == "spend_cap" and unknown[0].kind == "price_unknown" and len(calls) == 1
    assert bad[0].kind == "invalid" and SECRET not in bad[0].text and spent == 0.0


def test_spend_cap_endpoint(client):
    assert client.put("/api/llm/cap", json={"cap": 2.5}).json() == {"today": 0.0, "cap": 2.5}
    assert client.get("/api/keys").json()["spend"] == {"today": 0.0, "cap": 2.5}
    assert client.put("/api/llm/cap", json={"cap": -1}).status_code == 400
    assert client.put("/api/llm/cap", json={"cap": "1"}).status_code == 400
