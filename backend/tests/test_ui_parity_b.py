"""UI parity pass, items 5 and 6: the `rowNumbers` setting and the board 2DAY sparkline data (`/api/sparks`)."""

import httpx
import pytest

from openterm.providers.fixtures import fixture_transport
from openterm.providers.yahoo import SPARK_CHUNK, SPARK_POINTS, YahooProvider, spark_closes

# --- the `rowNumbers` setting -------------------------------------------------------------------


@pytest.mark.parametrize("value", ["auto", "on", "off"])
def test_settings_row_numbers_roundtrip(client, value):
    """The row-number gutter: `auto` (Terminal on, GUI off), `on`, `off`. Anything else is refused."""
    assert client.put("/api/settings", json={"settings": {"rowNumbers": value}}).status_code == 200
    assert client.get("/api/settings").json()["settings"] == {"rowNumbers": value}


@pytest.mark.parametrize("bad", ["yes", "ON", True, 1, None, ["on"]])
def test_settings_row_numbers_rejects(client, bad):
    r = client.put("/api/settings", json={"settings": {"rowNumbers": bad}})
    assert r.status_code == 400, r.text
    assert "rowNumbers" in r.text


# --- spark_closes (pure) ------------------------------------------------------------------------


def test_spark_closes_drops_gaps_and_keeps_order():
    resp = {"indicators": {"quote": [{"close": [1.0, None, 2, 3.5, None]}]}}
    assert spark_closes(resp) == [1.0, 2.0, 3.5]


def test_spark_closes_empty_when_yahoo_sends_nothing():
    assert spark_closes({}) == []
    assert spark_closes({"indicators": {"quote": [{}]}}) == []
    assert spark_closes({"indicators": {"quote": [{"close": [None, None]}]}}) == []


def test_spark_closes_thins_but_keeps_first_and_last():
    closes = [float(i) for i in range(500)]
    out = spark_closes({"indicators": {"quote": [{"close": closes}]}})
    assert len(out) == SPARK_POINTS
    assert out[0] == 0.0 and out[-1] == 499.0
    assert out == sorted(out)  # still in time order


# --- Yahoo adapter against the recorded fixture -------------------------------------------------


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


async def test_yahoo_sparks_from_a_real_recording(http):
    got = await YahooProvider(http).sparks(["AAPL", "^GSPC", "NOPE"])
    assert {"AAPL", "^GSPC"} <= set(got)
    assert "NOPE" not in got  # unknown symbol: blank, never invented
    assert 10 < len(got["AAPL"]) <= SPARK_POINTS
    assert all(isinstance(v, float) for v in got["AAPL"])


async def test_yahoo_quotes_still_use_the_one_day_range(http):
    """The quote's change must keep coming from the 1d call: a 2d range moves chartPreviousClose to the close before the window."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("range", ""))
        return await fixture_transport().handle_async_request(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        (q,) = await YahooProvider(c).quotes(["AAPL"])
    assert seen == ["1d"] and q.prev_close


async def test_sparks_make_one_request_per_chunk_not_per_symbol():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(request.url.params["symbols"].split(",")))
        return httpx.Response(200, json={"spark": {"result": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        got = await YahooProvider(c).sparks([f"S{i}" for i in range(SPARK_CHUNK * 2 + 5)])
    assert got == {}
    assert sorted(calls) == [5, SPARK_CHUNK, SPARK_CHUNK]


# --- the route ----------------------------------------------------------------------------------


def test_api_sparks_envelope(client):
    r = client.get("/api/sparks", params={"symbols": "AAPL,^GSPC,NOPE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] and body["stale"] is False
    assert set(body["data"]) == {"AAPL", "^GSPC"}  # NOPE has no points: left out
    assert len(body["data"]["AAPL"]) > 10


def test_api_sparks_needs_symbols(client):
    assert client.get("/api/sparks", params={"symbols": " , "}).status_code == 400
    assert client.get("/api/sparks").status_code == 422
