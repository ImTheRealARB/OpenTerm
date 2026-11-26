"""TradingView scanner: the keyless second source behind EQS (screener) and MOV (movers) when Nasdaq is down.

Fixtures are real answers recorded 2026-11-26 by scripts/record_tradingview.py (the screener trimmed to 445 rows).
"""

import json

import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.fixtures import FIXTURES, _route, fixture_transport
from openterm.providers.nasdaq import MOVER_TABLES
from openterm.providers.screener import COLUMNS
from openterm.providers.tradingview import (
    MOVER_SCANS,
    URL,
    TradingViewProvider,
    movers_from_scans,
    nasdaq_style,
    screener_from_scan,
)
from openterm.quantjobs.sectors import SPDR, TRADINGVIEW_TO_SECTOR, from_tradingview


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


def raw(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]


def row(data: dict, symbol: str) -> dict:
    return dict(zip(COLUMNS, next(x for x in data["rows"] if x[0] == symbol), strict=True))


def scans() -> dict:
    return {tab: raw(f"tv_movers_{tab.lower()}") for tab in MOVER_SCANS}


# --- symbols ---------------------------------------------------------------------------------
@pytest.mark.parametrize(("tv", "nasdaq"), [
    ("AAPL", "AAPL"), ("BRK.B", "BRK/B"), ("WSO.B", "WSO/B"),  # class shares
    ("PCG/PB", "PCG^B"), ("BAC/PN", "BAC^N"), ("PHXE/P", "PHXE^"),  # preferred series, as Nasdaq spells them
    (" spy ", "SPY"),
])
def test_nasdaq_style(tv, nasdaq):
    assert nasdaq_style(tv) == nasdaq


# --- screener --------------------------------------------------------------------------------
def test_screener_parses_recorded_scan():
    data = screener_from_scan(raw("tv_screener_trimmed"), "tradingview", 1.0)
    # Exactly the payload Nasdaq's parser builds, so EQS and COMP work unchanged.
    assert set(data) == {"columns", "rows", "sectors", "industries", "countries", "count", "as_of_text", "market",
                         "source", "as_of"}
    assert data["columns"] == COLUMNS and data["market"] == "US" and data["count"] == len(data["rows"]) == 445
    aapl = row(data, "AAPL")
    assert aapl["name"] == "Apple Inc." and aapl["last"] == 355.58 and aapl["volume"] == 54285151
    assert round(aapl["pct"], 2) == 0.43 and round(aapl["chg"], 2) == 1.51 and aapl["mcap"] > 5e12
    assert aapl["ipo"] is None  # not in the scanner: left empty, never guessed
    assert data["sectors"][aapl["sector"]] == "Technology"  # TradingView's "Electronic Technology", in Nasdaq's names
    assert data["industries"][aapl["industry"]] == "Telecommunications Equipment"  # industries stay TradingView's
    assert data["countries"][aapl["country"]] == "United States"
    assert row(data, "BRK/B")["name"] == "Berkshire Hathaway Inc. Class B"
    assert data["sectors"][0] == data["industries"][0] == data["countries"][0] == ""


def test_every_recorded_sector_maps_onto_a_nasdaq_sector():
    # A TradingView sector missing from the map would land rows in the blank sector: every recorded one must be known.
    recorded = {r["d"][8] for r in raw("tv_screener_trimmed")["data"]}
    assert len(recorded) >= 19 and recorded <= set(TRADINGVIEW_TO_SECTOR)
    assert set(TRADINGVIEW_TO_SECTOR.values()) <= set(SPDR) | {"Miscellaneous"}
    data = screener_from_scan(raw("tv_screener_trimmed"), "tradingview", 1.0)
    assert set(data["sectors"]) <= set(SPDR) | {"Miscellaneous", ""}
    # Industry overrides: REITs are "Finance" at TradingView, Real Estate at Nasdaq.
    assert from_tradingview("Finance", "Real Estate Investment Trusts") == "Real Estate"
    assert from_tradingview("Industrial Services", "Oilfield Services/Equipment") == "Energy"
    assert from_tradingview("Something New", "Whatever") == ""  # unknown: blank, never a guess


def test_preferreds_carry_no_market_cap():
    data = screener_from_scan(raw("tv_screener_trimmed"), "tradingview", 1.0)
    prefs = [dict(zip(COLUMNS, r, strict=True)) for r in data["rows"] if "^" in r[0]]
    assert prefs and all(p["mcap"] is None for p in prefs)  # the issuer's cap is not the series' own


def test_screener_errors_fail_loudly():
    with pytest.raises(ProviderError) as e:
        screener_from_scan({"totalCount": 0, "data": []}, "s", 1.0)
    assert e.value.kind == "not_found"
    for body in ({"error": "Unknown field \"nope\""}, None, "bot check"):
        with pytest.raises(ProviderError) as e:
            screener_from_scan(body, "s", 1.0)
        assert e.value.kind == "unavailable"


# --- movers ----------------------------------------------------------------------------------
def test_movers_parse_recorded_scans():
    m = movers_from_scans(scans(), "tradingview", 1.0)
    assert set(m.tables) == set(MOVER_TABLES.values())  # the same five MOV tabs Nasdaq fills
    assert all(len(rows) == 10 for rows in m.tables.values())
    gainers, losers = m.tables["GAINERS"], m.tables["LOSERS"]
    assert gainers[0].symbol == "BGLC" and gainers[0].change_pct > 100 and gainers[0].volume == 55338884
    assert [g.change_pct for g in gainers] == sorted((g.change_pct for g in gainers), reverse=True)
    assert all(lo.change_pct < 0 for lo in losers)
    assert m.tables["DOLLAR"][0].symbol == "NVDA"
    # Nasdaq-100: the ten members that moved most either way.
    ndx = m.tables["NDX100"]
    assert [x.symbol for x in ndx[:3]] == ["AXON", "ADI", "LRCX"]
    assert [abs(x.change_pct) for x in ndx] == sorted((abs(x.change_pct) for x in ndx), reverse=True)
    assert m.as_of_text is None and m.table_as_of == dict.fromkeys(m.tables)  # no "data as of" text from TradingView


def test_movers_all_empty_is_not_found():
    with pytest.raises(ProviderError) as e:
        movers_from_scans({tab: {"totalCount": 0, "data": []} for tab in MOVER_SCANS}, "s", 1.0)
    assert e.value.kind == "not_found"


# --- provider over the fixture transport -----------------------------------------------------
async def test_provider_replays_recordings(http):
    p = TradingViewProvider(http)
    assert (await p.screener())["count"] == 445
    assert (await p.movers()).source == "tradingview"
    await p.probe()


async def test_unrecorded_scan_is_404(http):
    r = await http.post(URL, json={"columns": ["name"], "range": [0, 7]})
    assert r.status_code == 404  # fixture mode never answers a query nobody recorded


# --- API: Nasdaq down -> TradingView answers, and the envelope says so -----------------------
@pytest.fixture
def nasdaq_down(monkeypatch):
    import openterm.providers.fixtures as fx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.nasdaq.com":
            return httpx.Response(503, text="down")
        return _route(request)

    monkeypatch.setattr(fx, "_route", handler)


def test_api_screener_falls_back(client, nasdaq_down):
    env = client.get("/api/screener").json()
    assert env["source"] == "tradingview:fixture" and "nasdaq_screener" in env["fallback_from"]
    assert env["data"]["count"] == 445 and env["data"]["columns"] == COLUMNS


def test_api_movers_falls_back(client, nasdaq_down):
    env = client.get("/api/movers").json()
    assert env["source"] == "tradingview:fixture" and "nasdaq" in env["fallback_from"]
    assert env["data"]["tables"]["GAINERS"][0]["symbol"] == "BGLC"


def test_api_movers_reach_yahoo_when_tradingview_is_down_too(client, monkeypatch):
    import openterm.providers.fixtures as fx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("api.nasdaq.com", "scanner.tradingview.com"):
            return httpx.Response(503, text="down")
        return _route(request)

    monkeypatch.setattr(fx, "_route", handler)
    env = client.get("/api/movers").json()
    assert env["source"] == "yahoo_movers:fixture"
    assert {"nasdaq", "tradingview"} <= set(env["fallback_from"])
    assert set(env["data"]["tables"]) == {"GAINERS", "LOSERS", "ACTIVE"}  # Yahoo's three tabs


def test_api_screener_prefers_nasdaq(client):
    assert client.get("/api/screener").json()["source"] == "nasdaq_screener:fixture"  # order unchanged when Nasdaq is up
