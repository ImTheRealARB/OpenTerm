"""Guards for the structural clean-up: the fixture route table, the explicit fixture flag, the shared HTTP helpers and the error kinds.

None of these test new behaviour; they pin the places where the old code relied on definition order or on string matching."""

import asyncio
import inspect

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from openterm import errkinds as K
from openterm import http_util
from openterm.errors import DataError
from openterm.keys import TESTS
from openterm.providers import ADAPTERS, fixtures
from openterm.providers.base import Provider


def test_route_table_ends_with_the_catch_all_and_every_checker_is_a_function():
    # The last checker must always answer, or _route would have nothing to return for an unknown path.
    assert fixtures.ROUTE_TABLE[-1] is fixtures._route_base
    assert len(set(fixtures.ROUTE_TABLE)) == len(fixtures.ROUTE_TABLE)
    resp = fixtures._route(httpx.Request("GET", "https://nowhere.invalid/x"))
    assert resp.status_code == 200 and resp.json()["data"] is None  # Nasdaq's "no data" answer, never invented data


def test_earlier_checkers_win_over_later_ones():
    # openrouter.ai/api/v1/key is a key test; the LLM checker sits above it but must hand that one request down.
    ok = fixtures._route(httpx.Request("GET", "https://openrouter.ai/api/v1/key"))
    assert ok.status_code == 200
    # ...while any other request to an LLM host is "not recorded", because the LLM checker answers before the key-test one.
    other = fixtures._route(httpx.Request("GET", "https://api.openai.com/v1/other"))
    assert other.status_code == 404


def test_key_test_routes_match_the_urls_keys_py_really_calls():
    # KEY_TESTS is derived from keys.TESTS, so it cannot drift; this pins that each entry is the URL the APIKEYS test button uses.
    for key_name in fixtures._KEY_TEST_FILES:
        url = httpx.URL(TESTS[key_name](dict.fromkeys(["FINNHUB_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"], "k"))[1])
        assert (url.host, url.path) in fixtures.KEY_TESTS


def test_build_marks_every_fixture_provider_and_only_those():
    from openterm.config import Settings
    from openterm.providers import build

    built = build(Settings(), httpx.AsyncClient(), fixtures=True)
    assert built and all(p.fixture for p in built.values())
    assert all(p.source.endswith(":fixture") or p.fixture for p in built.values())  # the text on screen is unchanged
    live = build(Settings(), httpx.AsyncClient(), fixtures=False)
    assert not any(p.fixture for p in live.values())
    # no adapter guesses from the text of `source` any more
    for cls in ADAPTERS.values():
        assert ':fixture"' not in inspect.getsource(cls)


def test_provider_fixture_flag_is_not_inferred_from_the_source_text():
    p = Provider(httpx.AsyncClient(), source="x:fixture")
    assert p.fixture is False and p.source == "x:fixture"


def test_data_errors_decorator_keeps_signature_and_error_envelope():
    async def route(request: Request, symbol: str = "AAPL"):
        raise DataError(K.NOT_FOUND, "NO DATA", detail="why")

    wrapped = http_util.data_errors(route)
    assert inspect.signature(wrapped) == inspect.signature(route) and inspect.iscoroutinefunction(wrapped)
    app = FastAPI()
    app.get("/x")(wrapped)
    r = TestClient(app).get("/x")
    assert r.status_code == 404 and r.json() == {"error": "NO DATA", "kind": "not_found", "detail": "why"}

    def sync_route():
        raise DataError(K.KEY_REQUIRED, "KEY REQUIRED", key="FRED_API_KEY")

    app.get("/y")(http_util.data_errors(sync_route))
    r = TestClient(app).get("/y")
    assert r.status_code == 424 and r.json()["detail"] == "KEY REQUIRED: set FRED_API_KEY in APIKEYS"


def test_data_errors_lets_other_exceptions_through():
    @http_util.data_errors
    async def boom():
        raise ValueError("not a DataError")

    with pytest.raises(ValueError):
        asyncio.run(boom())


def test_error_builders_share_one_body_shape():
    assert http_util.error_response(502, "provider", "SEC: down").status_code == 502
    assert http_util.key_error("env_locked", "SET IN ENV").status_code == 409
    assert http_util.key_error("nope", "x").status_code == 500
    assert http_util.bt_error(DataError("nope", "x")).status_code == 400  # BT: an unknown kind is the user's input
    assert http_util.error(DataError("nope", "x")).status_code == 500


def test_error_kinds_match_the_strings_the_status_map_and_breaker_use():
    assert set(http_util.STATUS) == {"bad_request", "not_found", "too_large", "unavailable", "key_required", "login_required", "login_expired"}
    assert set(K.NOT_AN_OUTAGE) == {"not_found", "unsupported", "depth", "login_expired"}
    assert set(K.NEEDS_USER_ACTION) == {"key_required", "login_expired"}
