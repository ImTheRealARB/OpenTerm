"""Workstream 07: the four keyed market-data sources (Twelve Data, Alpha Vantage, Polygon / Massive, Financial Modeling Prep).

What is real and what is not (every fixture says so inside the file, and `test_fixture_labels` checks it):
  - twelvedata_real_*, alphavantage_real_* : REAL answers recorded with each service's public `demo` key (or a made-up key for the limit texts).
  - keytest_*_401 (twelvedata, polygon, fmp) : REAL answers to a made-up key.
  - polygon_docshape_*, fmp_docshape_*, alphavantage_docshape_* : built from the docs, NOT A RECORDING. These tests prove the plumbing and
    the parsers, not that the live services answer exactly this way.
Nothing here touches the network: every adapter runs over an httpx.MockTransport.
"""

import json
import logging
import sys
import time
from pathlib import Path

import httpx
import pytest

from openterm import providers, redact
from openterm.errkinds import DEPTH, KEY_REQUIRED, NOT_FOUND, RATE_LIMITED, UNSUPPORTED
from openterm.keys import KEY_SPECS, TESTS, classify
from openterm.providers.alphavantage import AlphaVantageProvider
from openterm.providers.base import ProviderError
from openterm.providers.fmp import FmpProvider
from openterm.providers.hierarchy import DEFAULT_ORDER, HIERARCHY, build_order, order_for
from openterm.providers.polygon import PolygonProvider
from openterm.providers.twelvedata import TwelveDataProvider
from openterm.ratelimit import TokenBucket
from openterm.router import Router

FIX = Path(__file__).parent / "fixtures"
KEY = "SECRETKEY1234567890"
NEW = ("twelvedata", "alphavantage", "polygon", "fmp")
FIELD = {"twelvedata": "TWELVEDATA_API_KEY", "alphavantage": "ALPHAVANTAGE_API_KEY", "polygon": "POLYGON_API_KEY", "fmp": "FMP_API_KEY"}


def rec(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def body(name: str):
    return rec(name)["body"]


def reply(name: str) -> httpx.Response:
    return httpx.Response(rec(name)["status"], json=body(name))


def make(cls, handler, key: str | None = KEY):
    p = cls(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    p.bucket = TokenBucket(1000, 1000)  # the real limits are not what these tests are about
    if key:
        p.set_keys({FIELD[p.name]: key})
    return p


async def err(coro) -> ProviderError:
    with pytest.raises(ProviderError) as e:
        await coro
    return e.value


# --- zero keys: nothing changes ----------------------------------------------------------------------------------------------

# The chain exactly as it was before these four sources existed.
BEFORE = {"quotes": ["kite", "yahoo", "frankfurter", "nasdaq"],
          "history": ["kite", "binance_klines", "yahoo", "coinbase", "kraken", "frankfurter", "nasdaq", "nse_archive"],
          "search": ["yahoo"], "fundamentals": ["sec"]}


def test_the_four_sources_are_registered_and_have_keys():
    for n in NEW:
        assert n in providers.ADAPTERS and n in KEY_SPECS and n in TESTS
        assert KEY_SPECS[n].fields == (FIELD[n],)


def test_with_no_keys_the_chains_without_the_four_are_exactly_the_old_ones():
    order = build_order({}, False)
    for cap, old in BEFORE.items():
        assert [n for n in order[cap] if n not in NEW] == old, cap


async def test_with_no_keys_the_router_never_offers_a_keyed_source():
    adapters = {n: cls(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))) for n, cls in providers.ADAPTERS.items()}
    router = Router(adapters, build_order({}, False))
    for cap, sym in (("quotes", "AAPL"), ("history", "AAPL"), ("search", None), ("fundamentals", "AAPL"), ("quotes", "RELIANCE.NS")):
        assert not [p.name for p in router.candidates(cap, sym) if p.name in NEW], (cap, sym)
    # the candidates that remain are what they were before, in the same order (those that exist as keyless adapters)
    for cap, old in BEFORE.items():
        assert [p.name for p in router.candidates(cap, "AAPL" if cap != "search" else None)] == [n for n in old if n in adapters and
                adapters[n].supports(cap, "AAPL" if cap != "search" else None)]


@pytest.mark.parametrize("name", NEW)
async def test_a_keyless_adapter_supports_nothing_and_never_calls_out(name):
    calls = []
    p = make(providers.ADAPTERS[name], lambda r: calls.append(r) or httpx.Response(500), key=None)
    assert not p.has_key and all(not p.supports(c, "AAPL") and not p.supports(c) for c in p.capabilities)
    for call in (p.quotes(["AAPL"]), p.history("AAPL", "1mo", "1d")):
        assert (await err(call)).kind == KEY_REQUIRED
    assert calls == []  # key_required is raised BEFORE any network call


@pytest.mark.parametrize("name", NEW)
async def test_a_key_set_later_works_without_a_restart(name):
    p = make(providers.ADAPTERS[name], lambda r: httpx.Response(500), key=None)
    assert not p.supports("quotes", "AAPL")
    p.set_keys({FIELD[name]: KEY})
    assert p.supports("quotes", "AAPL")
    p.set_keys(None)  # a key deleted in APIKEYS
    assert not p.supports("quotes", "AAPL")


def test_with_no_keys_the_api_answers_from_yahoo_and_never_calls_the_keyed_sources(client):
    r = client.get("/api/quote", params={"symbols": "AAPL"}).json()
    assert r["results"]["AAPL"]["source"] == "yahoo:fixture"
    rows = {p["name"]: p for p in client.get("/api/sources").json()["providers"]}
    for n in NEW:
        assert rows[n]["calls"] == 0, n


# --- hierarchy ranks ---------------------------------------------------------------------------------------------------------

def test_ranks_keep_yahoo_first_and_slot_the_keyed_sources_in_the_documented_order():
    q, h = order_for("quotes"), order_for("history")
    assert q.index("yahoo") < q.index("twelvedata") < q.index("fmp") < q.index("polygon") < q.index("alphavantage") < q.index("frankfurter")
    assert h.index("yahoo") < h.index("twelvedata") < h.index("polygon") < h.index("fmp") < h.index("alphavantage") < h.index("coinbase")
    assert h.index("kite") < h.index("yahoo")  # a real-time exchange source still beats a quota-limited key
    assert DEFAULT_ORDER["fundamentals"] == ["sec", "fmp", "alphavantage"]  # SEC stays first
    assert DEFAULT_ORDER["search"][0] == "yahoo"
    for cap in ("quotes", "history"):
        for r in HIERARCHY[cap]:
            if r.provider in NEW:
                assert "per provider docs" in r.limits or "(per provider docs)" in r.limits, r.provider  # limits are not verified here


# --- Twelve Data (real demo-key recordings) ------------------------------------------------------------------------------------

def td_handler(seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        if path == "/quote":
            return reply("twelvedata_real_quote_aapl")
        if path == "/time_series":
            return reply("twelvedata_real_series_aapl_5min" if req.url.params["interval"] == "5min" else "twelvedata_real_series_aapl_1day")
        if path == "/symbol_search":
            return reply("twelvedata_real_search_aapl")
        return httpx.Response(404)
    return handler


async def test_twelvedata_quote_parses_and_sends_the_key_in_a_header_only():
    seen: list = []
    p = make(TwelveDataProvider, td_handler(seen))
    [q] = await p.quotes(["AAPL"])
    assert (q.symbol, q.price, q.prev_close, q.currency, q.exchange, q.source) == ("AAPL", 347.16, 350.69, "USD", "NASDAQ", "twelvedata")
    assert q.high_52w == 355.38 and q.low_52w == 243.42 and q.market_time == 1794321000 and q.volume == 377853
    assert seen[0].headers["authorization"] == f"apikey {KEY}"
    assert KEY not in str(seen[0].url) and "apikey" not in str(seen[0].url).lower()


async def test_twelvedata_daily_and_intraday_bars():
    p = make(TwelveDataProvider, td_handler([]))
    d = await p.history("AAPL", "1mo", "1d")
    assert d.interval == "1d" and len(d.t) == 30  # the recording holds 30 daily rows
    assert d.t == sorted(d.t) and d.c[-1] == 347.16 and d.tz == "America/New_York"  # oldest first, newest 2026-11-10
    assert d.t[-1] == 1794268800  # 2026-11-10 00:00 UTC, like the other daily sources
    i = await p.history("AAPL", "1d", "5m")  # the last session only: 2026-11-10 14:30-15:15 UTC = 10 five-minute bars
    assert len(i.t) == 10 and i.t[-1] == 1794323700 and i.v[-1] == 17720
    five = await p.history("AAPL", "5d", "5m")
    assert len(five.t) == 60  # both sessions of the recording are inside five sessions


async def test_twelvedata_search_keeps_only_exchanges_with_a_known_suffix():
    p = make(TwelveDataProvider, td_handler([]))
    hits = await p.search("AAPL")
    assert [h.symbol for h in hits] == ["AAPL", "AAPL.TO"]  # BCBA / BVC / BMV have no Yahoo suffix: skipped, never mis-resolved


async def test_twelvedata_depth_and_non_us_symbols():
    seen: list = []
    p = make(TwelveDataProvider, td_handler(seen))
    assert (await err(p.history("AAPL", "1y", "1m"))).kind == DEPTH  # 5000 bars of 1-minute candles are about 17 days
    assert p.supports("quotes", "RELIANCE.NS") and p.supports("quotes", "EURUSD=X") and not p.supports("quotes", "RELIANCE.XX")
    assert not p.supports("quotes", "^GSPC") and not p.supports("quotes", "BTC-USD")
    await p.quotes(["RELIANCE.NS"])
    assert seen[-1].url.params["symbol"] == "RELIANCE" and seen[-1].url.params["mic_code"] == "XNSE"


@pytest.mark.parametrize(("status", "payload", "kind", "needle"), [
    (401, "keytest_twelvedata_401", KEY_REQUIRED, "Twelve Data"),
    (200, {"code": 429, "message": "You have run out of API credits for the current minute.", "status": "error"}, RATE_LIMITED, "minute"),
    (429, {"code": 429, "message": "You have run out of API credits for the day.", "status": "error"}, RATE_LIMITED, "day"),
    (200, {"code": 403, "message": "This symbol is available starting with the Pro plan.", "status": "error"}, UNSUPPORTED, "KEY PLAN"),
    (200, {"code": 400, "message": "**symbol** not found: ZZZZ", "status": "error"}, NOT_FOUND, "Twelve Data"),
])
async def test_twelvedata_errors_map_to_states_with_the_provider_name(status, payload, kind, needle):
    out = reply(payload) if isinstance(payload, str) else httpx.Response(status, json=payload)
    p = make(TwelveDataProvider, lambda r: out)
    e = await err(p.history("AAPL", "1mo", "1d"))
    assert e.kind == kind and needle in str(e) and KEY not in str(e)


# --- Alpha Vantage (real demo-key recordings; the daily and premium shapes are doc-shaped) ------------------------------------------

def av_handler(seen: list | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        fn = req.url.params["function"]
        name = {"GLOBAL_QUOTE": "alphavantage_real_quote_ibm", "TIME_SERIES_INTRADAY": "alphavantage_real_intraday_ibm",
                "TIME_SERIES_DAILY": "alphavantage_docshape_daily_ibm", "INCOME_STATEMENT": "alphavantage_real_income_ibm",
                "BALANCE_SHEET": "alphavantage_real_balance_ibm", "CASH_FLOW": "alphavantage_real_cashflow_ibm"}[fn]
        return reply(name)
    return handler


async def test_alphavantage_quote_is_labelled_with_its_date_only():
    seen: list = []
    p = make(AlphaVantageProvider, av_handler(seen))
    [q] = await p.quotes(["IBM"])
    assert (q.price, q.prev_close, q.change, q.volume, q.source) == (246.11, 245.0, 1.11, 4629816, "alphavantage")
    assert q.change_pct == pytest.approx(0.4531)
    assert q.market_time == 1794182400  # 2026-11-09 00:00 UTC: a date is all Alpha Vantage sends, so the age is never understated
    assert q.as_of > q.market_time  # when we fetched it vs. when it traded: both are on the quote
    assert seen[0].url.params["apikey"] == KEY  # the only place it accepts the key ...


async def test_alphavantage_daily_and_intraday_bars():
    p = make(AlphaVantageProvider, av_handler())
    d = await p.history("IBM", "1mo", "1d")
    assert len(d.t) == 5 and d.t == sorted(d.t) and d.tz is None
    i = await p.history("IBM", "1d", "5m")  # the real recording, cut to the last session
    assert i.tz == "US/Eastern" and len(i.t) == 100 and i.t == sorted(i.t)
    assert i.t[-1] == 1794272100  # 2026-11-09 19:55 US/Eastern (EST) = 2026-11-10 00:55 UTC: the answer's own zone is applied
    assert (await err(p.history("IBM", "5d", "5m"))).kind == DEPTH  # the compact answer holds 100 bars, about one session
    assert (await err(p.history("IBM", "1y", "1d"))).kind == DEPTH  # outputsize=full is premium
    assert (await err(p.history("IBM", "1d", "1wk"))).kind == UNSUPPORTED
    assert not p.supports("quotes", "RELIANCE.NS") and p.supports("fundamentals", "IBM")


async def test_alphavantage_fundamentals_in_the_sec_shape_from_the_real_statements():
    p = make(AlphaVantageProvider, av_handler())
    f = await p.fundamentals("IBM")
    assert f["source"] == "alphavantage" and f["currency"] == "USD" and set(f) >= {"A", "Q", "symbol", "as_of"}
    a = f["A"]
    assert a["periods"][0]["end"] == "2025-12-31" and len(a["periods"]) == 5 and len(f["Q"]["periods"]) == 8
    rows = {r["key"]: r for s in a["statements"].values() for r in s}
    assert rows["revenue"]["values"][0] == 67536000000.0 and rows["net_income"]["values"][0] == 10593000000.0
    assert rows["operating_cf"]["values"][0] == 13193000000.0 and rows["capex"]["values"][0] == 1091000000.0
    assert rows["fcf"]["values"][0] == 13193000000.0 - 1091000000.0 and rows["fcf"]["computed"] is True
    assert rows["eps_basic"]["values"] == [None] * 5  # not in Alpha Vantage's statements: blank, never estimated
    assert rows["current_debt"]["values"][0] is None  # "None" text from the API is a blank, not a zero
    assert a["periods"][0]["fy"] is None and a["periods"][0]["label"] == "2025-12-31"  # no fiscal year in the answer: named by its end date


@pytest.mark.parametrize(("payload", "kind", "needle"), [
    ("alphavantage_docshape_premium", UNSUPPORTED, "KEY PLAN"),
    ("alphavantage_real_burst_limit", RATE_LIMITED, "burst"),
    ("keytest_alphavantage_bad_key", RATE_LIMITED, "daily limit"),
    ({"Error Message": "Invalid API call. Please retry or visit the documentation (https://www.alphavantage.co/documentation/) for GLOBAL_QUOTE."}, NOT_FOUND, "no such symbol"),
    ({"Information": "The **demo** API key is for demo purposes only. Please claim your free API key at https://www.alphavantage.co/support/#api-key"}, KEY_REQUIRED, "demo"),
])
async def test_alphavantage_200_messages_map_to_states_with_the_provider_name(payload, kind, needle):
    out = reply(payload) if isinstance(payload, str) else httpx.Response(200, json=payload)
    p = make(AlphaVantageProvider, lambda r: out)
    e = await err(p.history("IBM", "1mo", "1d"))
    assert e.kind == kind and needle in str(e) and "Alpha Vantage" in str(e)


async def test_alphavantage_never_copies_the_body_which_echoes_the_key():
    echo = {"Information": f"We have detected your API key as {KEY} and our standard API rate limit is 25 requests per day."}
    p = make(AlphaVantageProvider, lambda r: httpx.Response(200, json=echo))
    e = await err(p.fundamentals("IBM"))
    assert e.kind == RATE_LIMITED and KEY not in str(e) and KEY not in repr(e)


# --- Polygon / Massive (doc-shaped successes, real 401) ------------------------------------------------------------------------------

def pg_handler(seen: list | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        p = req.url.path
        if p.endswith("/prev"):
            return reply("polygon_docshape_prev_aapl")
        if "/range/1/day/" in p:
            return reply("polygon_docshape_aggs_aapl_1d")
        if "/range/5/minute/" in p:
            return reply("polygon_docshape_aggs_aapl_5m")
        if p == "/v3/reference/tickers":
            return reply("polygon_docshape_tickers_search_apple")
        return httpx.Response(404, json={"status": "NOT_FOUND"})
    return handler


async def test_polygon_quote_is_the_previous_session_and_the_key_is_a_bearer_header():
    seen: list = []
    p = make(PolygonProvider, pg_handler(seen))
    [q] = await p.quotes(["AAPL"])
    assert (q.price, q.open, q.high, q.low, q.volume, q.source) == (347.5, 351.0, 353.0, 346.5, 52000000, "polygon")
    assert q.market_time == 1794200400 and q.prev_close is None and q.change is None  # the session is labelled; nothing is estimated
    assert seen[0].headers["authorization"] == f"Bearer {KEY}" and KEY not in str(seen[0].url) and "apikey" not in str(seen[0].url).lower()
    assert seen[0].url.host == "api.massive.com"


async def test_polygon_bars_daily_and_minute_with_session_cut():
    p = make(PolygonProvider, pg_handler())
    d = await p.history("AAPL", "1mo", "1d")
    assert d.interval == "1d" and len(d.t) == 5 and d.c[0] == 346.0 and d.t == sorted(d.t)
    one = await p.history("AAPL", "1d", "5m")  # two sessions in the answer: 1D keeps the last one
    assert len(one.t) == 4 and one.tz == "America/New_York"
    five = await p.history("AAPL", "5d", "5m")
    assert len(five.t) == 8
    assert (await err(p.history("AAPL", "5y", "1d"))).kind == DEPTH  # the free plan's two years
    assert (await err(p.history("AAPL", "1y", "1m"))).kind == DEPTH
    assert (await err(p.history("AAPL", "1mo", "2m"))).kind == UNSUPPORTED


async def test_polygon_search_keeps_us_listings_and_an_unknown_ticker_is_not_found():
    p = make(PolygonProvider, pg_handler())
    assert [h.symbol for h in await p.search("apple")] == ["AAPL", "APLE"]  # the Frankfurt listing has no Yahoo suffix: skipped
    empty = make(PolygonProvider, lambda r: reply("polygon_docshape_prev_unknown"))
    assert (await err(empty.quotes(["ZZZZ"]))).kind == NOT_FOUND


@pytest.mark.parametrize(("payload", "kind", "needle"), [
    ("keytest_polygon_401", KEY_REQUIRED, "Polygon"),
    ("polygon_docshape_403_not_authorized", UNSUPPORTED, "KEY PLAN"),
    ("polygon_docshape_429", RATE_LIMITED, "Polygon"),
])
async def test_polygon_errors_map_to_states_with_the_provider_name(payload, kind, needle):
    p = make(PolygonProvider, lambda r: reply(payload))
    e = await err(p.history("AAPL", "1mo", "1d"))
    assert e.kind == kind and needle in str(e) and KEY not in str(e)


# --- FMP (doc-shaped successes, real 401) ---------------------------------------------------------------------------------------------

def fmp_handler(seen: list | None = None, quarterly: str | None = "fmp_docshape_402_premium"):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        path = req.url.path.removeprefix("/stable/")
        if req.url.params.get("period") == "quarter" and quarterly:
            return reply(quarterly)
        name = {"quote": "fmp_docshape_quote_aapl", "historical-price-eod/full": "fmp_docshape_history_aapl",
                "income-statement": "fmp_docshape_income_aapl", "balance-sheet-statement": "fmp_docshape_balance_aapl",
                "cash-flow-statement": "fmp_docshape_cashflow_aapl", "search-symbol": "fmp_docshape_search_apple"}.get(path)
        return reply(name) if name else httpx.Response(404, json={})
    return handler


async def test_fmp_quote_history_search():
    seen: list = []
    p = make(FmpProvider, fmp_handler(seen))
    [q] = await p.quotes(["AAPL"])
    assert (q.price, q.prev_close, q.change_pct, q.high_52w, q.exchange, q.source) == (347.16, 350.69, -1.0066, 355.38, "NASDAQ", "fmp")
    assert seen[0].url.params["apikey"] == KEY and seen[0].url.host == "financialmodelingprep.com"
    d = await p.history("AAPL", "1mo", "1d")
    assert d.t == sorted(d.t) and len(d.t) == 5 and d.c == [346.0, 347.0, 348.0, 349.0, 350.0]  # newest-first answer, oldest-first bars
    assert [h.symbol for h in await p.search("apple")] == ["AAPL", "APLE"]  # XETRA has no mapped suffix here: skipped
    assert (await err(p.history("AAPL", "1d", "5m"))).kind == UNSUPPORTED  # intraday is a paid plan
    assert (await err(p.history("AAPL", "10y", "1d"))).kind == DEPTH
    empty = make(FmpProvider, lambda r: reply("fmp_docshape_empty"))
    assert (await err(empty.quotes(["ZZZZ"]))).kind == NOT_FOUND


async def test_fmp_fundamentals_annual_free_quarterly_left_empty_with_a_note():
    p = make(FmpProvider, fmp_handler())
    f = await p.fundamentals("AAPL")
    a = f["A"]
    assert [x["label"] for x in a["periods"]] == ["FY2025", "FY2024", "FY2023"] and a["periods"][0]["fy"] == 2025 and a["periods"][0]["fp"] == "FY"
    rows = {r["key"]: r for s in a["statements"].values() for r in s}
    assert rows["revenue"]["values"][0] == 400000 * 3_000_000
    assert rows["capex"]["values"][0] == 10000 * 3_000_000 > 0  # FMP writes capex negative; OpenTerm's row is a positive payment
    assert rows["fcf"]["values"][0] == (120000 - 10000) * 3_000_000
    assert rows["dividends"]["values"][0] > 0 and rows["buybacks"]["values"][0] > 0
    assert f["Q"]["periods"] == [] and f["notes"] == ["QUARTERLY STATEMENTS NEED A PAID FMP PLAN"]  # never filled from annual numbers


@pytest.mark.parametrize(("payload", "kind", "needle"), [
    ("keytest_fmp_401", KEY_REQUIRED, "Financial Modeling Prep"),
    ("fmp_docshape_402_premium", UNSUPPORTED, "KEY PLAN"),
    ("fmp_docshape_429", RATE_LIMITED, "Financial Modeling Prep"),
    ({"Error Message": "Invalid API KEY. Please retry or visit our documentation."}, KEY_REQUIRED, "Financial Modeling Prep"),
])
async def test_fmp_errors_map_to_states_with_the_provider_name(payload, kind, needle):
    out = reply(payload) if isinstance(payload, str) else httpx.Response(200, json=payload)
    p = make(FmpProvider, lambda r: out)
    e = await err(p.history("AAPL", "1mo", "1d"))
    assert e.kind == kind and needle in str(e) and KEY not in str(e)


# --- the key never escapes -------------------------------------------------------------------------------------------------------

ALL_CALLS = {
    "twelvedata": lambda p: p.history("AAPL", "1mo", "1d"), "alphavantage": lambda p: p.history("IBM", "1mo", "1d"),
    "polygon": lambda p: p.history("AAPL", "1mo", "1d"), "fmp": lambda p: p.history("AAPL", "1mo", "1d"),
}


@pytest.mark.parametrize("name", NEW)
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_errors_never_carry_the_key_even_when_the_body_echoes_it(name, status):
    echo = {"message": f"bad key {KEY}", "Error Message": f"bad key {KEY}", "error": f"bad key {KEY}", "Information": f"key {KEY}", "code": status,
            "status": "error"}
    p = make(providers.ADAPTERS[name], lambda r: httpx.Response(status, json=echo))
    e = await err(ALL_CALLS[name](p))
    assert KEY not in str(e) and KEY not in repr(e) and KEY not in redact.redact(str(e), [KEY])
    assert e.kind in (KEY_REQUIRED, RATE_LIMITED, UNSUPPORTED, "unavailable")


@pytest.mark.parametrize("name", NEW)
async def test_a_network_error_never_carries_the_url(name):
    def boom(req: httpx.Request):
        raise httpx.ConnectError(f"cannot reach {req.url}", request=req)

    e = await err(ALL_CALLS[name](make(providers.ADAPTERS[name], boom)))
    assert e.kind == "unavailable" and str(e) == "ConnectError"

    def slow(req: httpx.Request):
        raise httpx.ReadTimeout(f"timeout for {req.url}", request=req)

    e2 = await err(ALL_CALLS[name](make(providers.ADAPTERS[name], slow)))
    assert str(e2) == "timeout"


async def test_where_the_key_travels_and_what_redaction_does_with_it():
    seen: dict[str, httpx.Request] = {}
    for name, handler in (("twelvedata", td_handler([])), ("alphavantage", av_handler()), ("polygon", pg_handler()), ("fmp", fmp_handler())):
        def spy(req, handler=handler, name=name):
            seen[name] = req
            return handler(req)

        await make(providers.ADAPTERS[name], spy).history("IBM" if name == "alphavantage" else "AAPL", "1mo", "1d")
    # header styles: the key is not in the URL at all
    for name in ("twelvedata", "polygon"):
        assert KEY not in str(seen[name].url) and KEY in seen[name].headers["authorization"]
    # query styles (the only form these two APIs offer): the key IS in the URL, so every place a URL can be shown must mask it
    for name in ("alphavantage", "fmp"):
        url = str(seen[name].url)
        assert f"apikey={KEY}" in url
        assert KEY not in redact.redact(url)  # the `apikey=` shape alone is masked, with no key registered
        assert KEY not in redact.redact(f"GET {url} 200", [KEY])
        assert "apikey=***" in redact.redact(url)
    # and an HTTP client log line (httpx logs full URLs) goes through the same filter
    redact.register([KEY])
    try:
        record = logging.LogRecord("httpx", logging.INFO, __file__, 1, 'HTTP Request: GET %s "HTTP/1.1 200 OK"', (str(seen["alphavantage"].url),), None)
        redact.RedactFilter().filter(record)
        assert KEY not in record.getMessage()
        header_line = logging.LogRecord("openterm", logging.INFO, __file__, 1, "sent Authorization: apikey %s", (KEY,), None)
        redact.RedactFilter().filter(header_line)
        assert KEY not in header_line.getMessage()  # Twelve Data's header form is caught because the key store registers it
    finally:
        redact.unregister([KEY])


# --- through the app: fallback order, SOURCES, key tests, labelling -------------------------------------------------------------------

GOOD = "docshape-key-0123456789"


def put_key(client, name: str, value: str = GOOD) -> None:
    assert client.put(f"/api/keys/{name}", json={"fields": {FIELD[name]: value}}).status_code == 200


def test_apikeys_lists_the_four_keys_with_a_signup_link_and_never_a_value(client):
    rows = {r["name"]: r for r in client.get("/api/keys").json()["keys"]}
    for n in NEW:
        assert n in rows and rows[n]["signup"].startswith("https://") and rows[n]["present"] is False
    put_key(client, "twelvedata")
    text = client.get("/api/keys").text + client.get("/api/sources").text
    assert GOOD not in text


def test_key_tests_use_the_provider_own_cheapest_call_and_classify_the_answer(client):
    for n in ("twelvedata", "polygon", "fmp"):
        put_key(client, n, "madeupkey-0123456789")
        r = client.post(f"/api/keys/{n}/test").json()
        assert r["state"] == "INVALID", n  # the real 401 answers to a made-up key
    assert classify(401, json.dumps(body("keytest_fmp_401"))) == "INVALID"
    assert classify(429, "") == "QUOTA"
    # Alpha Vantage accepts any key and says OK for IBM: its TEST cannot tell a wrong key from a right one (documented in DATA_LIMITS)
    assert classify(200, json.dumps(body("alphavantage_real_quote_ibm"))) == "OK"


def test_with_a_key_a_down_yahoo_falls_through_to_twelvedata_and_the_answer_says_so(client):
    put_key(client, "twelvedata")
    router = client.app.state.service.router
    router.health["yahoo"].down_until = time.time() + 600
    r = client.get("/api/quote", params={"symbols": "AAPL"}).json()["results"]["AAPL"]
    assert r["source"] == "twelvedata:fixture" and r["stale"] is False  # a source that is down is skipped, not tried
    assert r["data"]["price"] == 347.16 and r["data"]["market_time"] == 1794321000
    assert 0 <= r["age_s"] < 5 and r["as_of"] > r["data"]["market_time"]  # the fetch time and the trade time are both on the answer
    # past its time to live the same answer is served STALE with its age, never as fresh
    client.app.state.service.ttl["quote"] = 0
    s = client.get("/api/quote", params={"symbols": "AAPL"}).json()["results"]["AAPL"]
    assert s["stale"] is True and s["source"] == "twelvedata:fixture" and s["age_s"] >= 0
    assert GOOD not in client.get("/api/log").text


def test_keyless_symbols_the_key_does_not_cover_still_use_the_old_chain(client):
    put_key(client, "polygon")  # US only: a keyed source that does not cover the symbol is skipped
    router = client.app.state.service.router
    names = [p.name for p in router.candidates("quotes", "RELIANCE.NS")]
    assert "polygon" not in names and names[:1] == ["yahoo"]


def test_fundamentals_stay_on_sec_and_the_keyed_sources_are_only_fallbacks(client):
    put_key(client, "fmp")
    router = client.app.state.service.router
    assert [p.name for p in router.candidates("fundamentals", "AAPL")] == ["sec", "fmp"]
    d = client.get("/api/fa", params={"symbol": "MSFT"}).json()
    assert d["source"].startswith("sec")  # SEC answers; FMP is never asked
    assert client.get("/api/sources").json()["providers"] and next(p for p in client.get("/api/sources").json()["providers"] if p["name"] == "fmp")["calls"] == 0
    router.health["sec"].down_until = time.time() + 600  # SEC is out: the keyed fallback takes over
    f = client.get("/api/fa", params={"symbol": "AAPL", "period": "A"})
    assert f.status_code == 200, f.text
    j = f.json()
    assert j["source"] == "fmp:fixture" and j["data"]["periods"][0]["label"] == "FY2025"
    q = client.get("/api/fa", params={"symbol": "AAPL", "period": "Q"}).json()
    assert q["data"]["periods"] == [] and q["data"]["notes"] == ["QUARTERLY STATEMENTS NEED A PAID FMP PLAN"]


# --- fixtures: every file says what it is ---------------------------------------------------------------------------------------------

def test_fixture_labels():
    names = sorted(p.stem for p in FIX.glob("*.json") if p.stem.split("_")[0] in NEW or p.stem in
                   ("keytest_twelvedata_401", "keytest_polygon_401", "keytest_fmp_401", "keytest_alphavantage_bad_key"))
    assert len(names) >= 25
    for n in names:
        r = rec(n)
        if "_docshape_" in n:
            assert r.get("doc_shaped", "").startswith("NOT A RECORDING") and "recorded" not in r, n
        else:
            assert "REAL" in r.get("recorded", "") and "doc_shaped" not in r, n
            assert n.startswith(("twelvedata_real_", "alphavantage_real_", "keytest_")), n
        assert "madeupkey" not in json.dumps(r), n  # a made-up key never stays in a file
    # real success shapes exist only where a public demo key can record them: nothing "real" for Polygon or FMP besides the 401s
    assert not [n for n in names if n.startswith(("polygon_real_", "fmp_real_"))]


def test_no_fixture_holds_a_secret_shaped_value():
    for p in FIX.glob("*.json"):
        if p.stem.split("_")[0] in NEW or p.stem in ("keytest_twelvedata_401", "keytest_polygon_401", "keytest_fmp_401", "keytest_alphavantage_bad_key"):
            t = p.read_text(encoding="utf-8")
            assert KEY not in t and "apikey=" not in t.lower().replace("apikey=redacted", ""), p.name


# --- the recorder (scripts/record_providers.py): never run here, but its refusal and labels are tested on made-up responses ----------------

def recorder():
    import importlib.util

    spec = importlib.util.spec_from_file_location("record_providers", Path(__file__).resolve().parents[2] / "scripts" / "record_providers.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["record_providers"] = mod  # @dataclass looks its module up here
    spec.loader.exec_module(mod)
    return mod


def fake_response(text: str, url: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("GET", url))


def test_recorder_scrubs_the_key_labels_date_and_source_and_keeps_the_key_out_of_the_url_label(tmp_path, monkeypatch):
    rp = recorder()
    monkeypatch.setattr(rp, "OUT", tmp_path)
    r = fake_response(json.dumps({"Information": f"We have detected your API key as {KEY} and ..."}),
                      f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=TSLA&apikey={KEY}")
    rp.save("demo_file", r, KEY, "test")
    saved = json.loads((tmp_path / "demo_file.json").read_text(encoding="utf-8"))
    assert KEY not in json.dumps(saved) and "REDACTED" in saved["body"]["Information"]
    assert saved["recorded"].startswith(time.strftime("%Y-%m-%d")) and "REAL answer" in saved["recorded"]
    assert saved["source"] == "https://www.alphavantage.co/query (query: function, symbol)"  # names only, never the key


def test_recorder_refuses_to_write_a_fixture_that_still_contains_the_key(tmp_path, monkeypatch):
    rp = recorder()
    monkeypatch.setattr(rp, "OUT", tmp_path)
    key = "abcDEF12!xyz"
    # the key comes back URL-encoded or in another case: the plain replace misses it, the guard must not
    for echoed in (key.upper(), "abcDEF12%21xyz", key.lower()):
        with pytest.raises(SystemExit) as e:
            rp.save("leaky", fake_response(json.dumps({"echo": echoed}), "https://api.test/x"), key, "test")
        assert "REFUSED" in str(e.value)
        assert not (tmp_path / "leaky.json").exists()
    assert rp.leaks_key("nothing here", key) is False and rp.leaks_key("demo", "demo") is False  # the public demo key is not a secret
