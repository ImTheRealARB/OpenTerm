"""FMP as the last, keyed backup for DES (`profile`) and DVD / CACS / EVT (`dividends`) (2026-11-28): parsing the two recorded
AAPL answers, the place in each order, the key hint when no key is set and a refused key. Fixtures are REAL recordings made
with the owner's free key (scripts/record_fmp_research.py)."""

from __future__ import annotations

import json

import httpx
import pytest

from openterm.providers.base import PROFILE, ProviderError
from openterm.providers.fixtures import FIXTURES, fixture_transport
from openterm.providers.fmp import FmpProvider, dividends_from_body, error_for, profile_from_body
from openterm.providers.hierarchy import DEFAULT_ORDER
from openterm.providers.research_nasdaq import DIVIDENDS
from openterm.research import corp_parse as cp
from openterm.router import AllFailed, Router

DOCSHAPE_KEY = "docshape-test"  # the fixture FMP host answers only keys that start with "docshape"


def recorded(name: str) -> list:
    return json.loads((FIXTURES / f"fmp_real_{name}_AAPL.json").read_text(encoding="utf-8"))["body"]


def test_fmp_is_last_in_both_orders_and_serves_both_capabilities():
    assert DEFAULT_ORDER["profile"] == ["yahoo", "nasdaq", "fmp"]
    assert DEFAULT_ORDER["dividends"] == ["nasdaq_research", "yahoo_research", "fmp"]
    assert {PROFILE, DIVIDENDS} <= FmpProvider.capabilities


def test_profile_maps_the_recorded_answer_and_leaves_what_fmp_does_not_send_empty():
    raw = recorded("profile")[0]
    p = profile_from_body("AAPL", recorded("profile"), "fmp", 1.0)
    assert (p.symbol, p.name, p.source) == ("AAPL", raw["companyName"], "fmp")
    assert (p.sector, p.industry, p.country, p.website) == (raw["sector"], raw["industry"], raw["country"], raw["website"])
    assert p.market_cap == raw["marketCap"] and p.beta == raw["beta"] and p.avg_volume == raw["averageVolume"]
    assert p.employees == int(raw["fullTimeEmployees"]) and p.exchange == raw["exchange"] and p.currency == "USD"
    low, high = (float(x) for x in raw["range"].split("-"))
    assert (p.low_52w, p.high_52w) == (low, high)
    # Never guessed: FMP's profile has no P/E, EPS, share counts, enterprise value or yield, and AAPL is not an ETF.
    assert all(getattr(p, f) is None for f in ("pe", "forward_pe", "eps", "forward_eps", "dividend_yield", "shares_out",
                                               "float_shares", "enterprise_value", "price_to_book", "quote_type", "delay_min"))


def test_profile_text_fields_that_are_empty_stay_none_and_an_etf_is_named():
    p = profile_from_body("SPY", [{"companyName": "SPDR S&P 500", "sector": "", "range": "n/a", "isEtf": True,
                                   "fullTimeEmployees": ""}], "fmp", 1.0)
    assert p.sector is None and p.low_52w is None and p.high_52w is None and p.employees is None and p.quote_type == "ETF"


def test_profile_fails_loudly_on_an_empty_or_odd_answer():
    for bad in ([], None, {"Error Message": "x"}, [{"symbol": "ZZZ"}]):
        with pytest.raises(ProviderError):
            profile_from_body("ZZZ", bad, "fmp", 1.0)


def test_dividends_map_the_recorded_rows_into_the_payload_the_other_sources_feed():
    rows = recorded("dividends")
    raw = dividends_from_body(rows, "fmp")
    assert len(raw["rows"]) == len(rows) == 5
    first = raw["rows"][0]
    assert first == {"ex_date": rows[0]["date"], "amount": rows[0]["dividend"], "type": None, "declared": rows[0]["declarationDate"],
                     "record": rows[0]["recordDate"], "pay": rows[0]["paymentDate"]}
    # FMP's `yield` is one payment's and it sends no yearly total: both stay empty, never computed.
    assert raw["annual"] is None and raw["yield"] is None and raw["source"] == "fmp"
    payload = cp.dvd_payload("AAPL", raw)  # the DVD panel's own builder accepts it
    assert payload["source"] == "fmp"


def test_dividends_fail_loudly_on_a_non_list_or_no_dated_rows():
    with pytest.raises(ProviderError):
        dividends_from_body({"Error Message": "x"}, "fmp")
    with pytest.raises(ProviderError):
        dividends_from_body([{"symbol": "AAPL", "date": "", "dividend": 0.2}], "fmp")


async def test_adapter_reads_both_endpoints_through_the_fixture_host():
    async with httpx.AsyncClient(transport=fixture_transport()) as http:
        p = FmpProvider(http, fixture=True)
        p.set_keys({"FMP_API_KEY": DOCSHAPE_KEY})
        prof = await p.profile("AAPL")
        dvd = await p.dividends("AAPL")
    assert prof.name == recorded("profile")[0]["companyName"] and prof.source == "fmp"
    assert len(dvd["rows"]) == 5 and dvd["rows"][0]["ex_date"] == recorded("dividends")[0]["date"]


async def test_non_us_symbols_are_not_requested():
    async with httpx.AsyncClient() as http:
        p = FmpProvider(http)
        p.set_keys({"FMP_API_KEY": DOCSHAPE_KEY})
        assert not p.supports(PROFILE, "TCS.NS") and not p.supports(DIVIDENDS, "TCS.NS")
        with pytest.raises(ProviderError):
            await p.profile("TCS.NS")
        with pytest.raises(ProviderError):
            await p.dividends("TCS.NS")


async def test_without_a_key_fmp_is_skipped_and_named_as_the_unlock():
    async with httpx.AsyncClient() as http:
        fmp = FmpProvider(http)  # no key
        for cap in (PROFILE, DIVIDENDS):
            assert not fmp.supports(cap, "AAPL")
            router = Router({"fmp": fmp}, {cap: ["fmp"]})
            with pytest.raises(AllFailed) as e:
                await router.call(cap, lambda p: p.profile("AAPL"), "AAPL")
            assert e.value.unlock == ["FMP_API_KEY"]


async def test_a_refused_key_is_classified_as_key_required_and_a_paid_symbol_as_key_plan():
    async with httpx.AsyncClient(transport=fixture_transport()) as http:
        p = FmpProvider(http, fixture=True)
        p.set_keys({"FMP_API_KEY": "not-a-docshape-key"})  # the fixture host answers its recorded 401 to this
        with pytest.raises(ProviderError) as e:
            await p.profile("AAPL")
    assert e.value.kind == "key_required"
    plan = error_for(402, {"Error Message": "Premium Query Parameter: 'Special Endpoint'"})
    assert plan is not None and plan.kind == "unsupported" and "KEY PLAN" in str(plan)
