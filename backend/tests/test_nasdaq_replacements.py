"""The sources that stand in for Nasdaq while api.nasdaq.com blocks OpenTerm (2026-11-26, docs/DATA_LIMITS.md).

Fixtures are REAL recordings, trimmed (scripts/record_nasdaq_replacements.py): Yahoo screener + predefined screens, Finnhub
earnings / IPO calendars, FMP earnings dates. No test touches the network.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from openterm.errors import DataError
from openterm.providers.base import ProviderError
from openterm.providers.finnhub import FinnhubProvider
from openterm.providers.fixtures import FIXTURES, fixture_transport
from openterm.providers.fmp import FmpProvider
from openterm.providers.hierarchy import DEFAULT_ORDER
from openterm.providers.keyed import KeyedProvider
from openterm.providers.screener import COLUMNS
from openterm.providers.yahoo_screens import (
    PAGE,
    YahooMoversProvider,
    YahooScreenerProvider,
    industry_query,
    screener_symbol,
)
from openterm.quantjobs.sectors import SPDR, from_yahoo_name
from openterm.research import calendars_parse as cal
from openterm.research import corp_parse as cp
from openterm.router import AllFailed, Router
from openterm.service import DataService

DOCSHAPE_KEY = "docshape-test"  # the fixture FMP host answers only keys that start with "docshape"


def fx_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=fixture_transport())


def body(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]


# --- order: Nasdaq stays first, the replacements answer when it is down -----------------------------------------------------
def test_each_nasdaq_only_capability_has_a_second_source_after_nasdaq():
    for cap, nasdaq, other in [("earnings", "nasdaq_earnings", "finnhub"), ("ipo", "nasdaq_research", "finnhub"),
                               ("earnings_history", "nasdaq_research", "fmp")]:
        assert DEFAULT_ORDER[cap][:2] == [nasdaq, other], cap
    # Screener and movers have two keyless stand-ins: TradingView (one call, all five MOV tabs), then the Yahoo screens.
    assert DEFAULT_ORDER["screener"] == ["nasdaq_screener", "tradingview", "yahoo_screener"]
    assert DEFAULT_ORDER["movers"] == ["nasdaq", "tradingview", "yahoo_movers", "fmp"]  # FMP: keyed backup, last


# --- Yahoo screener ------------------------------------------------------------------------------------------------------------
def test_screener_symbol_turns_yahoo_spelling_into_screener_spelling():
    assert screener_symbol("BRK-B") == "BRK/B"
    assert screener_symbol("BAC-PL") == "BAC^L"  # a preferred series, which the company search never offers
    assert screener_symbol("aapl") == "AAPL"
    assert screener_symbol("ABC-UN") == "ABC-UN"  # units stay as Yahoo writes them


def test_yahoo_sector_names_map_onto_the_canonical_nasdaq_names():
    yahoo = ["Basic Materials", "Consumer Cyclical", "Financial Services", "Real Estate", "Consumer Defensive", "Healthcare",
             "Utilities", "Communication Services", "Energy", "Industrials", "Technology"]  # the 11 labels Yahoo listed 2026-11-26
    assert {from_yahoo_name(s) for s in yahoo} == set(SPDR)
    assert from_yahoo_name("Something New") == ""


async def test_yahoo_screener_builds_the_nasdaq_shaped_universe_from_the_recorded_industries():
    async with fx_http() as http:
        out = await YahooScreenerProvider(http, fixture=True).screener()
    assert out["columns"] == COLUMNS and out["market"] == "US" and out["countries"] == [""]
    assert out["count"] == len(out["rows"]) == 36  # 12 recorded rows in each of the 3 recorded industries
    by = {r[0]: r for r in out["rows"]}
    aapl = by["AAPL"]
    assert out["sectors"][aapl[9]] == "Technology" and out["industries"][aapl[10]] == "Consumer Electronics"
    assert aapl[6] > 1e12 and aapl[5] > 0 and aapl[8] == 1980  # market cap, volume, first trading year
    assert out["industries"][by["MSFT"][10]] == "Software—Infrastructure"
    caps = [r[6] or 0 for r in out["rows"]]
    assert caps == sorted(caps, reverse=True)  # largest first
    assert all(r[7] == 0 for r in out["rows"])  # Yahoo has no headquarters country


def _screen_answer(total: int, n: int, start: int) -> dict:
    quotes = [{"symbol": f"T{start + i}", "longName": f"Test {start + i}", "marketCap": 1000 - start - i} for i in range(n)]
    return {"finance": {"result": [{"total": total, "count": n, "quotes": quotes}], "error": None}}


async def test_yahoo_screener_pages_through_an_industry_bigger_than_one_page():
    offsets = []

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.url.host == "fc.yahoo.com":
            return httpx.Response(404)
        if p == "/v1/test/getcrumb":
            return httpx.Response(200, text="crumb")
        if p.endswith("/fields"):
            labels = [{"displayName": "Big", "criteria": {"operator": "EQ", "operands": ["industry", "Big"]}, "dependentFilterLabel": "Energy"}]
            return httpx.Response(200, json={"finance": {"result": [{"fields": {"industry": {"labels": labels}}}]}})
        off = json.loads(request.content)["offset"]
        offsets.append(off)
        return httpx.Response(200, json=_screen_answer(PAGE + 10, PAGE if off == 0 else 10, off))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        out = await YahooScreenerProvider(http).screener()
    assert sorted(offsets) == [0, PAGE]
    assert out["count"] == PAGE + 10 and out["sectors"] == ["", "Energy"]


async def test_one_failed_industry_fails_the_whole_refresh_instead_of_a_smaller_market():
    async with fx_http() as http:
        p = YahooScreenerProvider(http, fixture=True)
        real = p._post

        async def flaky(q):
            if q["query"]["operands"][2]["operands"][1] == "Semiconductors":
                raise ProviderError("unavailable", "HTTP 500")
            return await real(q)

        p._post = flaky
        with pytest.raises(ProviderError):
            await p.screener()


def test_industry_query_restricts_to_us_listings_and_one_industry():
    q = industry_query("Semiconductors", 250)
    assert q["offset"] == 250 and q["size"] == PAGE
    region, exchanges, industry = q["query"]["operands"]
    assert region["operands"] == ["region", "us"] and industry["operands"] == ["industry", "Semiconductors"]
    assert {o["operands"][1] for o in exchanges["operands"]} >= {"NMS", "NYQ", "ASE"}


# --- Yahoo movers ------------------------------------------------------------------------------------------------------------
async def test_yahoo_movers_fill_the_three_tabs_yahoo_has():
    async with fx_http() as http:
        m = await YahooMoversProvider(http, fixture=True).movers()
    assert set(m.tables) == {"GAINERS", "LOSERS", "ACTIVE"}  # no $-volume or Nasdaq-100 table at Yahoo
    assert all(len(v) == 12 for v in m.tables.values())
    assert all((r.change_pct or 0) > 0 for r in m.tables["GAINERS"])
    assert all((r.change_pct or 0) < 0 for r in m.tables["LOSERS"])
    assert m.market_time and m.source == "yahoo_movers"


# --- Finnhub calendars -------------------------------------------------------------------------------------------------------
def finnhub(http: httpx.AsyncClient, key: str = "test-key") -> FinnhubProvider:
    return FinnhubProvider(http, api_key=key, fixture=True)


async def test_finnhub_earnings_day_maps_hours_and_surprises():
    async with fx_http() as http:
        out = await finnhub(http).earnings(date(2026, 11, 24))
    rows = out["rows"]
    assert out["date"] == "2026-11-24" and len(rows) == 54
    adi = next(r for r in rows if r["symbol"] == "ADI")
    assert adi["time"] == "PRE" and adi["fiscal_quarter"] == "Q4 2026" and adi["eps"] == 4.06
    assert adi["surprise_pct"] == round((4.06 - 3.9221) / 3.9221 * 100, 2)
    assert {r["time"] for r in rows} == {"PRE", "POST", None}
    assert all(r["name"] is None and r["market_cap"] is None for r in rows)  # Finnhub has neither


async def test_finnhub_unrecorded_day_is_a_404_never_invented_rows():
    async with fx_http() as http:
        with pytest.raises(ProviderError):
            await finnhub(http).earnings(date(2026, 11, 20))


async def test_finnhub_ipo_month_fills_the_panel_sections():
    async with fx_http() as http:
        raw = await finnhub(http).ipo("2026-11")
    assert {k: len(v) for k, v in raw["rows"].items()} == {"upcoming": 2, "priced": 5, "filed": 16, "withdrawn": 7}
    page = cp.ipo_payload("2026-11", raw)
    assert [s["id"] for s in page["sections"]] == ["upcoming", "priced", "filed", "withdrawn"]
    assert page["notes"] == [raw["note"]] and "FINNHUB" in raw["note"]


def test_finnhub_ipo_price_range_keeps_the_text_and_has_no_single_price():
    raw = cal.finnhub_ipo({"ipoCalendar": [{"status": "expected", "price": "4.00-5.00", "symbol": "NEW", "date": "2026-12-01"},
                                           {"status": "priced", "price": "10.00", "symbol": "OLD", "date": "2026-11-01"},
                                           {"status": "rumoured", "symbol": "X"}]}, "finnhub")
    assert raw["rows"]["upcoming"][0]["price"] is None and raw["rows"]["upcoming"][0]["range"] == "4.00-5.00"
    assert raw["rows"]["priced"][0]["price"] == 10.0
    assert sum(len(v) for v in raw["rows"].values()) == 2  # an unknown status is dropped


async def test_finnhub_calendars_are_inert_without_a_key():
    async with fx_http() as http:
        p = finnhub(http, key="")
    assert not p.supports("earnings") and not p.supports("ipo")


def test_nasdaq_ipo_rows_are_normalised_by_its_own_parser():
    raw = cp.ipo_tables(body("nasdaq_ipo_2026-10"), "nasdaq_research")
    assert set(raw["rows"]) == {"upcoming", "priced", "filed", "withdrawn"} and "NASDAQ" in raw["note"]
    assert any(raw["rows"].values())


# --- FMP earnings dates (GP markers) ----------------------------------------------------------------------------------------
def test_fmp_earnings_history_keeps_only_reported_quarters():
    out = cal.fmp_earnings_history(body("fmp_real_earnings_aapl"), "2026-11-26", "fmp")
    assert [r["date"] for r in out["rows"]] == ["2026-11-02", "2026-07-30", "2026-04-30", "2026-01-29"]  # 2027-02-04 not reported yet
    first = out["rows"][0]
    assert first["eps"] == 2.05 and first["surprise_pct"] == round((2.05 - 1.99) / 1.99 * 100, 2)
    with pytest.raises(ProviderError):
        cal.fmp_earnings_history([{"date": "2027-01-01", "epsActual": None}], "2026-11-26", "fmp")


async def test_fmp_earnings_history_through_the_adapter():
    async with fx_http() as http:
        p = FmpProvider(http, fixture=True)
        p.set_keys({"FMP_API_KEY": DOCSHAPE_KEY})
        out = await p.earnings_history("AAPL")
        assert out["rows"] and out["source"] == "fmp"
        with pytest.raises(ProviderError) as e:
            await p.earnings_history("RELIANCE.NS")
        assert e.value.kind == "unsupported"


# --- service: names for Finnhub's rows, and the key hint when Nasdaq is down --------------------------------------------------
class _FakeService:
    def __init__(self, uni: dict | None):
        self.uni = uni

    async def screener(self) -> dict:
        if self.uni is None:
            raise DataError("unavailable", "PROVIDER DOWN")
        return {"data": self.uni}


async def test_finnhub_earnings_rows_get_names_and_caps_from_the_screener_and_sort_largest_first():
    uni = {"columns": COLUMNS, "source": "yahoo_screener",
           "rows": [["BRK/B", "Berkshire Hathaway Inc.", 1, 0, 0, 1, 1.0e12, 0, None, 0, 0],
                    ["ADI", "Analog Devices, Inc.", 1, 0, 0, 1, 1.2e11, 0, None, 0, 0]]}
    out = {"date": "d", "rows": [{"symbol": "ADI", "name": None, "market_cap": None}, {"symbol": "BRK.B", "name": None, "market_cap": None},
                                 {"symbol": "ZZZ", "name": None, "market_cap": None}], "source": "finnhub"}
    got = await DataService._earnings_names(_FakeService(uni), out)
    assert [r["symbol"] for r in got["rows"]] == ["BRK.B", "ADI", "ZZZ"]
    assert got["rows"][0]["name"] == "Berkshire Hathaway Inc." and got["rows"][2]["name"] is None
    assert got["source"] == "finnhub + yahoo_screener (names, market caps)"


async def test_earnings_rows_stay_as_given_when_the_screener_is_down_too():
    out = {"rows": [{"symbol": "ADI", "name": None, "market_cap": None}], "source": "finnhub"}
    assert await DataService._earnings_names(_FakeService(None), out) == out


class _Down(KeyedProvider):
    """Stands in for the blocked Nasdaq calendar."""

    name = "nasdaq_earnings"
    key_name = ""
    capabilities = frozenset({"earnings"})

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities

    async def earnings(self, day):
        raise ProviderError("unavailable", "403 (blocked or needs auth)")


async def test_router_names_the_key_that_would_unlock_another_source():
    async with httpx.AsyncClient() as http:
        providers = {"nasdaq_earnings": _Down(http), "finnhub": FinnhubProvider(http, api_key="")}
        router = Router(providers, {"earnings": ["nasdaq_earnings", "finnhub"]})
        with pytest.raises(AllFailed) as e:
            await router.call("earnings", lambda p: p.earnings(date(2026, 11, 24)))
    assert e.value.kind == "unavailable" and e.value.unlock == ["FINNHUB_API_KEY"]
