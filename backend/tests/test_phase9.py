"""Phase 9: the Nasdaq screener universe (EQS) and peer lists (COMP), with their envelopes and fallbacks."""

import json

import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.fixtures import FIXTURES, _route, fixture_transport
from openterm.providers.screener import (
    COLUMNS,
    NasdaqScreenerProvider,
    YahooPeersProvider,
    peers_from_body,
    screener_from_body,
)


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


def raw(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]


def row(data: dict, symbol: str) -> dict:
    r = next(x for x in data["rows"] if x[0] == symbol)
    return dict(zip(COLUMNS, r, strict=True))


# --- screener: parsing -----------------------------------------------------------------------
def test_screener_parses_trimmed_fixture():
    data = screener_from_body(raw("nasdaq_screener_trimmed"), "nasdaq_screener", 1.0)
    assert data["count"] == len(data["rows"]) == 476  # the fixture is the real answer trimmed to 476 rows
    assert data["columns"] == COLUMNS and data["market"] == "US"
    aapl = row(data, "AAPL")
    assert aapl["name"] == "Apple Inc. Common Stock"
    assert aapl["last"] == 342.0 and aapl["chg"] == -0.96 and aapl["pct"] == -0.28
    assert aapl["volume"] == 39767602 and aapl["mcap"] == 4991209560000.0 and aapl["ipo"] == 1980
    assert data["sectors"][aapl["sector"]] == "Technology"
    assert data["industries"][aapl["industry"]] == "Computer Manufacturing"
    assert data["countries"][aapl["country"]] == "United States"
    # Index 0 of every lookup table is the empty value (Nasdaq leaves sector/country blank for funds etc.).
    assert data["sectors"][0] == data["industries"][0] == data["countries"][0] == ""
    assert len(set(data["sectors"])) == len(data["sectors"])


def test_screener_blank_cap_and_names():
    body = {"data": {"rows": [
        {"symbol": "zz ", "name": "Odd   Name  Fund ", "lastsale": "$1.50", "netchange": "UNCH", "pctchange": "",
         "volume": "", "marketCap": "0.00", "country": "", "ipoyear": "", "industry": "", "sector": ""},
        {"symbol": "", "name": "no symbol"},
    ]}}
    data = screener_from_body(body, "s", 1.0)
    assert data["rows"] == [["ZZ", "Odd Name Fund", 1.5, None, None, None, None, 0, None, 0, 0]]


def test_screener_empty_is_not_found():
    for body in ({"data": {"rows": []}}, {"data": None}, None, "bot check"):
        with pytest.raises(ProviderError) as e:
            screener_from_body(body, "s", 1.0)
        assert e.value.kind == "not_found"


async def test_screener_provider(http):
    data = await NasdaqScreenerProvider(http).screener()
    assert data["count"] == 476 and data["source"] == "nasdaq_screener"
    await NasdaqScreenerProvider(http).probe()


async def test_screener_provider_down():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Access Denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(ProviderError) as e:
            await NasdaqScreenerProvider(c).screener()
    assert e.value.kind == "unavailable"


# --- peers -----------------------------------------------------------------------------------
def test_peers_from_body():
    assert [p["symbol"] for p in peers_from_body(raw("yahoo_recs_aapl"), "aapl")] == [
        "AMZN", "TSLA", "GOOG", "META", "MSFT",
    ]
    assert peers_from_body(raw("yahoo_recs_aapl"), "MSFT") == []  # result for another symbol is ignored
    assert peers_from_body(raw("yahoo_recs_empty"), "ZZZZNOPE") == []
    assert peers_from_body(None, "X") == []


async def test_peers_provider(http):
    out = await YahooPeersProvider(http).peers("AAPL")
    assert out["source"] == "yahoo_peers" and out["peers"][0] == {"symbol": "AMZN", "score": 0.181705}
    with pytest.raises(ProviderError) as e:
        await YahooPeersProvider(http).peers("ZZZZNOPE")
    assert e.value.kind == "not_found"


# --- API envelopes ---------------------------------------------------------------------------
def test_api_screener_envelope(client):
    r = client.get("/api/screener")
    assert r.status_code == 200
    env = r.json()
    assert set(env) == {"data", "source", "as_of", "age_s", "stale", "fallback_from"}
    assert env["source"] == "nasdaq_screener:fixture" and env["stale"] is False
    assert env["data"]["count"] == 476 and env["data"]["columns"] == COLUMNS
    assert client.get("/api/screener").json()["as_of"] == env["as_of"]  # served from cache


def test_api_peers_yahoo_with_screener_details(client):
    env = client.get("/api/peers", params={"symbol": "aapl"}).json()
    d = env["data"]
    assert env["source"] == "yahoo_peers:fixture" and d["basis"] == "yahoo"
    assert d["symbol"] == "AAPL" and d["self"]["industry"] == "Computer Manufacturing"
    assert [p["symbol"] for p in d["peers"]] == ["AMZN", "TSLA", "GOOG", "META", "MSFT"]
    msft = d["peers"][-1]
    assert msft["name"] == "Microsoft Corporation Common Stock" and msft["market_cap"] > 1e12


def test_api_peers_falls_back_to_industry(client, monkeypatch):
    import openterm.providers.fixtures as fx

    # Yahoo down: peers come from the same industry in the screener, largest first.
    def handler(request: httpx.Request) -> httpx.Response:
        if "recommendationsbysymbol" in request.url.path:
            return httpx.Response(503, text="down")
        return _route(request)

    monkeypatch.setattr(fx, "_route", handler)
    env = client.get("/api/peers", params={"symbol": "DELL"}).json()
    assert env["data"]["basis"] == "industry"
    assert env["source"] == "nasdaq_screener:fixture:industry" and "yahoo_peers" in env["fallback_from"]
    assert [p["symbol"] for p in env["data"]["peers"]] == ["AAPL", "IBM"]


def test_api_peers_not_found(client):
    r = client.get("/api/peers", params={"symbol": "ZZZZNOPE"})
    assert r.status_code == 404 and r.json()["error"] == "NO PEERS FOUND"


# --- HIST: adjusted close travels with the bars ----------------------------------------------
def test_history_carries_adjusted_close(client):
    d = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "D"}).json()["data"]
    assert len(d["adj"]) == len(d["t"]) == len(d["c"]) == 251
    assert d["adj"][0] == 251.36148071289062 and d["c"][0] == 252.2899932861328  # recorded Yahoo values


def test_nasdaq_bars_have_no_adjusted_close():
    from openterm.providers.nasdaq import bars_from_rows

    rows = [{"date": "10/16/2026", "open": "$1", "high": "$2", "low": "$0.5", "close": "$1.5", "volume": "10"}]
    assert bars_from_rows("X", rows, "1y", "nasdaq", 1.0).model_dump()["adj"] is None
