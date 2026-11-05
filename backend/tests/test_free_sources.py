"""Four free read-only sources: Frankfurter (ECB FX fixes, keyless), UK Companies House, Marketaux news, Etherscan.

Status of the data behind these tests:
  - REAL recordings: the Frankfurter rates (frankfurter_rates_eur_usd_inr) and Etherscan's answer to a made-up key
    (keytest_etherscan_invalid). Marketaux's 401 status is real too, its body is the documented shape.
  - DOC-SHAPED (written from the official docs, invented values, marked "doc_shaped" in each file): every successful Companies House,
    Marketaux and Etherscan answer, and Companies House's 401 body. The first call with a real key is the real test.
Fixture mode accepts only keys that start with "docshape" for the three keyed hosts (providers/fixtures.py).
"""

import base64
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from openterm.providers import companies_house_parse as chp
from openterm.providers import etherscan_parse as ep
from openterm.providers import frankfurter_parse as fp
from openterm.providers import marketaux_parse as mp
from openterm.providers.base import ProviderError
from openterm.providers.companies_house import CompaniesHouseProvider
from openterm.providers.etherscan import EtherscanProvider
from openterm.providers.fixtures import FIXTURES
from openterm.providers.frankfurter import FrankfurterProvider
from openterm.providers.hierarchy import order_for, rank_of
from openterm.providers.marketaux import DAILY_BUDGET, MarketauxProvider
from openterm.router import AllFailed, Router

KEY = "docshape_key_0123456789"
ADDRESS = "0xc5102fE9359FD9a28f877a67E36B0F050d81a3CC"


def body(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]


def mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- Frankfurter: pure helpers --------------------------------------------------------------------------------------------

def test_fx_pair_symbols():
    assert fp.pair_of("EURUSD=X") == ("EUR", "USD") and fp.pair_of("usdinr=x") == ("USD", "INR")
    assert fp.pair_of("INR=X") == ("USD", "INR")  # Yahoo's short form means US dollars to INR
    assert fp.pair_of("USDUSD=X") is None
    assert fp.pair_of("AAPL") is None and fp.pair_of("BTC-USD") is None and fp.pair_of("^GSPC") is None and fp.pair_of("CL=F") is None


def test_series_picks_one_pair_sorts_and_skips_junk():
    rows = body("frankfurter_rates_eur_usd_inr")[::-1]  # newest first on purpose
    ts, rates = fp.series(rows, "EUR", "USD")
    assert len(ts) == 5 and ts == sorted(ts) and rates[0] == 1.1133 and rates[-1] == 1.1179
    assert ts[0] == int(datetime(2026, 10, 28, tzinfo=UTC).timestamp())
    assert fp.series([*rows, {"date": "2026-11-04", "base": "EUR", "quote": "USD", "rate": "n/a"}, "junk"], "EUR", "USD") == (ts, rates)
    assert fp.series([], "EUR", "USD") == ([], [])


def test_series_refuses_a_shape_that_is_not_the_documented_list():
    with pytest.raises(ProviderError) as e:
        fp.series({"rates": {}}, "EUR", "USD")  # v1's shape, not v2's
    assert e.value.kind == "unavailable"
    with pytest.raises(ProviderError):
        fp.series([{"date": "not-a-date", "base": "EUR", "quote": "USD", "rate": 1.0}], "EUR", "USD")


def test_latest_two():
    assert fp.latest_two([], []) is None
    assert fp.latest_two([5], [1.5]) == (5, 1.5, None)
    assert fp.latest_two([5, 6], [1.5, 1.6]) == (6, 1.6, 1.5)


# --- Frankfurter: adapter -------------------------------------------------------------------------------------------------

def frankfurter(seen: list | None = None) -> FrankfurterProvider:
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        wanted = set(req.url.params["quotes"].split(","))
        return httpx.Response(200, json=[r for r in body("frankfurter_rates_eur_usd_inr") if r["quote"] in wanted])

    p = FrankfurterProvider(mock(handler))
    p._today = staticmethod(lambda: date(2026, 11, 5))
    return p


async def test_frankfurter_history_is_flat_daily_bars_labelled_as_the_ecb_fix():
    seen = []
    bars = await frankfurter(seen).history("EURUSD=X", "1y", "1d")
    q = seen[0].url.params
    assert q["base"] == "EUR" and q["quotes"] == "USD" and q["providers"] == "ecb" and q["from"] == "2025-11-04"  # 1y = 366 days back
    assert bars.c == [1.1133, 1.113, 1.1172, 1.1216, 1.1179] and bars.o == bars.h == bars.l == bars.c  # no invented high or low
    assert bars.v == [None] * 5 and bars.interval == "1d" and bars.currency == "USD"
    assert "ECB" in bars.source and "open = high = low = close" in bars.source


async def test_frankfurter_range_starts():
    seen = []
    p = frankfurter(seen)
    await p.history("EURUSD=X", "ytd", "1d")
    await p.history("EURUSD=X", "max", "1d")
    assert [r.url.params["from"] for r in seen] == ["2026-01-01", "1999-01-04"]


async def test_frankfurter_serves_only_daily_fx_pairs():
    p = frankfurter()
    assert p.supports("history", "EURUSD=X") and p.supports("quotes") and not p.supports("history", "AAPL") and not p.supports("news_top")
    for sym, interval in (("EURUSD=X", "5m"), ("EURUSD=X", "1wk"), ("AAPL", "1d")):
        with pytest.raises(ProviderError) as e:
            await p.history(sym, "1y", interval)
        assert e.value.kind == "unsupported"


async def test_frankfurter_empty_answer_is_not_found():
    p = FrankfurterProvider(mock(lambda r: httpx.Response(200, json=[])))
    with pytest.raises(ProviderError) as e:
        await p.history("EURUSD=X", "1y", "1d")
    assert e.value.kind == "not_found"
    p404 = FrankfurterProvider(mock(lambda r: httpx.Response(404, json={"status": 404, "message": "not found"})))
    with pytest.raises(ProviderError) as e2:
        await p404.history("EURXYZ=X", "1y", "1d")
    assert e2.value.kind == "not_found"  # no circuit-breaker strike for an unknown currency


async def test_frankfurter_quote_is_the_last_fix_with_its_date_as_the_time():
    seen = []
    quotes = await frankfurter(seen).quotes(["EURUSD=X", "EURINR=X", "AAPL"])
    assert len(seen) == 1 and set(seen[0].url.params["quotes"].split(",")) == {"USD", "INR"}  # one request per base currency
    q = {x.symbol: x for x in quotes}
    assert set(q) == {"EURUSD=X", "EURINR=X"}
    usd = q["EURUSD=X"]
    assert usd.price == 1.1179 and usd.prev_close == 1.1216 and usd.exchange == "ECB"
    assert usd.change == pytest.approx(1.1179 - 1.1216) and usd.change_pct == pytest.approx((1.1179 - 1.1216) / 1.1216 * 100)
    assert usd.market_time == int(datetime(2026, 11, 3, tzinfo=UTC).timestamp())  # the fix date: a panel shows how old it is


def test_frankfurter_ranks_below_yahoo_with_reasons():
    for cap in ("history", "quotes"):
        order = order_for(cap)
        assert order.index("yahoo") < order.index("frankfurter")
        r = rank_of("frankfurter")[cap]
        assert r["rank"] == order.index("frankfurter") + 1 and "Yahoo" in r["why"] and r["limits"].strip()


async def test_router_falls_back_to_frankfurter_for_an_fx_pair_when_yahoo_is_down():
    class DownYahoo(FrankfurterProvider):
        name = "yahoo"

        async def history(self, symbol, range_, interval):
            raise ProviderError("unavailable", "timeout")

    router = Router({"yahoo": DownYahoo(mock(lambda r: httpx.Response(500))), "frankfurter": frankfurter()},
                    {"history": ["yahoo", "frankfurter"]})
    bars, failed = await router.call("history", lambda p: p.history("EURUSD=X", "1y", "1d"), "EURUSD=X")
    assert failed == ["yahoo"] and bars.c[-1] == 1.1179
    with pytest.raises(AllFailed):  # not an FX pair: frankfurter is skipped, nothing is invented
        await router.call("history", lambda p: p.history("AAPL", "1y", "1d"), "AAPL")


# --- Marketaux ------------------------------------------------------------------------------------------------------------

def test_marketaux_sentiment_is_the_requested_companys_score():
    items = mp.parse_news(body("marketaux_news_aapl_docshape"), "marketaux", "AAPL")
    assert [i.title for i in items] == ["Example Corp reports record quarter", "Example Corp faces a supply delay"]  # newest first
    assert [i.sentiment for i in items] == [0.5, -0.25] and items[0].publisher == "news.example.com"
    assert items[0].published == datetime(2026, 11, 4, 10, 12, tzinfo=UTC).timestamp()
    assert mp.parse_news(body("marketaux_news_aapl_docshape"), "marketaux", "TSLA")[0].sentiment is None  # no entity for that symbol


def test_marketaux_market_news_averages_every_entity():
    (item,) = mp.parse_news(body("marketaux_news_top_docshape"), "marketaux")
    assert item.sentiment == pytest.approx(0.2)


def test_marketaux_skips_rows_without_a_link_or_headline_and_refuses_a_wrong_shape():
    rows = {"data": [{"title": "No link"}, {"url": "https://a.example.com/x"}, {"title": "OK", "url": "https://a.example.com/y"}]}
    assert [i.title for i in mp.parse_news(rows, "marketaux")] == ["OK"]
    with pytest.raises(ProviderError):
        mp.parse_news({"articles": []}, "marketaux")


def test_marketaux_error_codes_map_to_provider_error_kinds():
    def err(status, code=None):
        return mp.error_of(status, {"error": {"code": code, "message": "m"}} if code else None)

    assert err(200) is None
    assert err(401, "invalid_api_token").kind == "key_required"
    assert err(402, "usage_limit_reached").kind == "rate_limited" and err(429, "rate_limit_reached").kind == "rate_limited"
    assert err(404, "resource_not_found").kind == "not_found" and err(503, "maintenance_mode").kind == "unavailable"
    assert err(402).kind == "rate_limited" and err(401).kind == "key_required"  # status alone is enough when the body is not JSON


def marketaux(handler=None, key: str = KEY) -> MarketauxProvider:
    p = MarketauxProvider(mock(handler or (lambda r: httpx.Response(200, json=body("marketaux_news_aapl_docshape")))))
    p.set_keys({"MARKETAUX_KEY": key} if key else None)
    return p


async def test_marketaux_is_inert_without_a_key_and_sends_nothing():
    sent = []
    p = marketaux(lambda r: sent.append(r) or httpx.Response(200, json={}), key="")
    assert not p.has_key and not p.supports("news_symbol") and not p.supports("news_top")
    with pytest.raises(ProviderError) as e:
        await p.news_symbol("AAPL")
    assert e.value.kind == "key_required" and sent == []


async def test_marketaux_symbol_news_asks_for_that_symbol_only_and_keeps_the_answer_for_15_minutes():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=body("marketaux_news_aapl_docshape"))

    p = marketaux(handler)
    first = await p.news_symbol("AAPL")
    again = await p.news_symbol("AAPL")
    q = seen[0].url.params
    assert q["symbols"] == "AAPL" and q["filter_entities"] == "true" and q["language"] == "en" and q["api_token"] == KEY
    assert len(seen) == 1 and again["items"] == first["items"] and p.requests_today == 1  # the repeat cost no request
    assert first["items"][0].source == "marketaux"


async def test_marketaux_stops_at_its_daily_budget():
    p = marketaux()
    p.requests_today, p._day = DAILY_BUDGET, datetime.now(UTC).date().isoformat()
    with pytest.raises(ProviderError) as e:
        await p.news_top()
    assert e.value.kind == "rate_limited" and "DAILY BUDGET" in str(e.value)
    p._day = "1999-01-01"  # a new UTC day resets the counter
    assert (await p.news_top())["items"] and p.requests_today == 1


async def test_marketaux_rejected_key_and_quota_never_echo_the_key():
    p = marketaux(lambda r: httpx.Response(401, json={"error": {"code": "invalid_api_token", "message": f"bad {KEY}"}}))
    with pytest.raises(ProviderError) as e:
        await p.news_top()
    assert e.value.kind == "key_required" and KEY not in str(e.value)
    q = marketaux(lambda r: httpx.Response(402, json={"error": {"code": "usage_limit_reached", "message": "x"}}))
    with pytest.raises(ProviderError) as e2:
        await q.news_top()
    assert e2.value.kind == "rate_limited"


async def test_marketaux_network_error_text_has_no_url():
    def boom(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")

    with pytest.raises(ProviderError) as e:
        await marketaux(boom).news_top()
    assert KEY not in str(e.value) and "http" not in str(e.value)


def test_marketaux_has_no_probe_so_the_scheduler_never_spends_its_quota():
    from openterm.providers.base import Provider

    assert MarketauxProvider.probe is Provider.probe


# --- Companies House ------------------------------------------------------------------------------------------------------

def test_company_numbers():
    assert chp.as_number("6") == "00000006" and chp.as_number("09999999") == "09999999" and chp.as_number("sc123456") == "SC123456"
    assert chp.as_number("SC 12345") == "SC012345" and chp.as_number("tesco") is None and chp.as_number("Example Trading") is None


def test_companies_house_parsers():
    s = chp.search(body("companies_house_search_docshape"))
    assert s["total"] == 1 and s["items"][0]["number"] == "09999999" and s["items"][0]["name"] == "EXAMPLE TRADING LIMITED"
    p = chp.profile(body("companies_house_profile_docshape"))
    assert p["address"] == "1 Example Street, London, EC1A 1AA, England" and p["sic"] == ["62012"]
    assert p["accounts"] == {"last_made_up_to": "2025-03-31", "next_due": "2026-12-31", "overdue": False}
    assert p["confirmation"]["next_due"] == "2027-03-16" and p["has_charges"] is False
    o = chp.officers(body("companies_house_officers_docshape"))
    assert [r["name"] for r in o["items"]] == ["EXAMPLE, Active Person", "SAMPLE, Resigned Person"]  # active first
    assert o["active"] == 1 and o["resigned"] == 1 and o["items"][0]["role"] == "DIRECTOR"
    assert "birth" not in json.dumps(o).lower()  # dates of birth are never read
    f = chp.filings(body("companies_house_filings_docshape"))
    assert f["total"] == 2 and f["items"][1]["description"] == "ACCOUNTS WITH ACCOUNTS TYPE TOTAL EXEMPTION FULL" and f["items"][0]["type"] == "CS01"


def test_companies_house_refuses_a_wrong_shape():
    with pytest.raises(ProviderError):
        chp.profile({"hello": "world"})
    with pytest.raises(ProviderError):
        chp.search([1, 2])


def ch_handler(seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        name = {"/search/companies": "companies_house_search_docshape", "/company/09999999": "companies_house_profile_docshape",
                "/company/09999999/officers": "companies_house_officers_docshape",
                "/company/09999999/filing-history": "companies_house_filings_docshape"}.get(req.url.path)
        return httpx.Response(200, json=body(name)) if name else httpx.Response(404, json={})

    return handler


def companies_house(handler, key: str = KEY) -> CompaniesHouseProvider:
    p = CompaniesHouseProvider(mock(handler))
    p.set_keys({"COMPANIES_HOUSE_KEY": key} if key else None)
    return p


async def test_companies_house_sends_the_key_as_basic_auth_user_with_an_empty_password():
    seen = []
    out = await companies_house(ch_handler(seen)).ch_company("09999999")
    auth = seen[0].headers["authorization"]
    assert auth == "Basic " + base64.b64encode(f"{KEY}:".encode()).decode()
    assert KEY not in str(seen[0].url) and "key" not in seen[0].url.query.decode().lower()
    assert [r.url.path for r in seen] == ["/company/09999999", "/company/09999999/officers", "/company/09999999/filing-history"]
    assert out["profile"]["name"] == "EXAMPLE TRADING LIMITED" and out["officers"]["active"] == 1 and out["filings"]["total"] == 2 and out["notes"] == []


async def test_companies_house_without_a_key_says_key_required_before_any_request():
    seen = []
    p = companies_house(ch_handler(seen), key="")
    assert p.supports("companies_house")  # stays on, so the panel can say KEY REQUIRED
    for call in (p.ch_search("tesco"), p.ch_company("09999999")):
        with pytest.raises(ProviderError) as e:
            await call
        assert e.value.kind == "key_required"
    assert seen == [] and p.key_name == "COMPANIES_HOUSE_KEY"


async def test_companies_house_status_codes():
    for status, kind in ((401, "key_required"), (403, "key_required"), (404, "not_found"), (429, "rate_limited"), (500, "unavailable")):
        with pytest.raises(ProviderError) as e:
            await companies_house(lambda r, s=status: httpx.Response(s, json={})).ch_company("09999999")
        assert e.value.kind == kind and KEY not in str(e.value)


async def test_companies_house_search_with_no_match_is_not_found():
    p = companies_house(lambda r: httpx.Response(200, json={"items": [], "total_results": 0}))
    with pytest.raises(ProviderError) as e:
        await p.ch_search("zzzzzz")
    assert e.value.kind == "not_found"


async def test_companies_house_keeps_the_profile_when_a_later_section_fails_and_says_so():
    def handler(req):
        if req.url.path.endswith("/officers"):
            return httpx.Response(500)
        if req.url.path.endswith("/filing-history"):
            return httpx.Response(404, json={})
        return httpx.Response(200, json=body("companies_house_profile_docshape"))

    out = await companies_house(handler).ch_company("09999999")
    assert out["officers"] is None and out["filings"] is None
    assert out["notes"] == ["OFFICERS NOT LOADED: HTTP 500", "FILINGS NOT LOADED: NONE PUBLISHED FOR THIS COMPANY"]


# --- Etherscan ------------------------------------------------------------------------------------------------------------

def test_etherscan_result_of():
    assert ep.result_of({"status": "1", "message": "OK", "result": "5"}) == "5"
    assert ep.result_of({"status": "0", "message": "No transactions found", "result": []}) == []
    for text, kind in (("Invalid API Key (#err2)", "key_required"),  # the real answer to a made-up key
                       ("Max rate limit reached, please use API Key for higher rate limit", "rate_limited"),
                       ("Too many invalid api key attempts, please try again later", "rate_limited"),  # a throttle, not a bad key
                       ("Community Free API limit reached. Resets 2026-06-24 12:00:00 UTC.", "rate_limited"),
                       ("Free API access is not supported for this chain. Please upgrade your api plan", "unsupported"),  # a plan limit, never an outage
                       ("Error! Invalid address format", "unavailable")):
        with pytest.raises(ProviderError) as e:
            ep.result_of({"status": "0", "message": "NOTOK", "result": text})
        assert e.value.kind == kind, text
    with pytest.raises(ProviderError):
        ep.result_of([1])


def test_etherscan_parsers():
    assert ep.balance("172774397764084972158218")["balance"] == pytest.approx(172774.397764084972)
    (tx,) = ep.transactions(body("etherscan_txlist_docshape")["result"], ADDRESS)
    assert tx["dir"] == "IN" and tx["value"] == 0 and not tx["failed"] and tx["method"] == "delegate(address to)"
    assert tx["fee"] == pytest.approx(48847 * 238744402 / 1e18) and tx["time"] == 1759129619 and tx["block"] == 23467053
    assert ep.transactions(body("etherscan_txlist_docshape")["result"], "0x2449ecef5012f0a0e153b278ef4fcc9625bc4c78")[0]["dir"] == "OUT"
    g = ep.gas(body("etherscan_gasoracle_docshape")["result"])
    assert g == {"last_block": 23467872, "safe": 0.496839934, "propose": 0.496840168, "fast": 0.55411917, "base_fee": 0.496839934}
    with pytest.raises(ProviderError):
        ep.balance(["x"])
    with pytest.raises(ProviderError):
        ep.eth("not a number")


def test_etherscan_address_shape_and_chains():
    assert ep.ADDRESS.match(ADDRESS) and not ep.ADDRESS.match("0x123") and not ep.ADDRESS.match("c5102fE9359FD9a28f877a67E36B0F050d81a3CC")
    assert ep.CHAINS["ETH"] == 1


def etherscan(handler, key: str = KEY) -> EtherscanProvider:
    p = EtherscanProvider(mock(handler))
    p.set_keys({"ETHERSCAN_KEY": key} if key else None)
    return p


def es_handler(seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        name = {("account", "balance"): "etherscan_balance_docshape", ("account", "txlist"): "etherscan_txlist_docshape",
                ("gastracker", "gasoracle"): "etherscan_gasoracle_docshape"}[(req.url.params["module"], req.url.params["action"])]
        return httpx.Response(200, json=body(name))

    return handler


async def test_etherscan_address_view_uses_the_documented_calls():
    seen = []
    out = await etherscan(es_handler(seen)).chain_address(ADDRESS, 1)
    assert [(r.url.params["module"], r.url.params["action"]) for r in seen] == [("account", "balance"), ("account", "txlist"), ("gastracker", "gasoracle")]
    assert all(r.url.params["chainid"] == "1" and r.url.params["apikey"] == KEY for r in seen)
    assert seen[0].url.params["address"] == ADDRESS and seen[1].url.params["offset"] == "20" and seen[1].url.params["sort"] == "desc"
    assert out["balance"]["balance"] > 172774 and out["txs"][0]["dir"] == "IN" and out["gas"]["propose"] == 0.496840168 and out["notes"] == []


async def test_etherscan_keeps_the_balance_when_transactions_fail_and_says_so():
    def handler(req):
        if req.url.params["action"] == "txlist":
            return httpx.Response(200, json={"status": "0", "message": "NOTOK", "result": "Query Timeout occured. Please select a smaller result dataset"})
        return httpx.Response(200, json=body("etherscan_balance_docshape" if req.url.params["action"] == "balance" else "etherscan_gasoracle_docshape"))

    out = await etherscan(handler).chain_address(ADDRESS, 1)
    assert out["txs"] is None and out["gas"] and out["balance"]["wei"] and out["notes"][0].startswith("TRANSACTIONS NOT LOADED: Etherscan: Query Timeout")


async def test_etherscan_without_a_key_says_key_required_before_any_request():
    seen = []
    p = etherscan(es_handler(seen), key="")
    assert p.supports("chain") and p.key_name == "ETHERSCAN_KEY"
    for call in (p.chain_gas(1), p.chain_address(ADDRESS, 1)):
        with pytest.raises(ProviderError) as e:
            await call
        assert e.value.kind == "key_required"
    assert seen == []


async def test_etherscan_invalid_key_is_key_required_and_the_key_is_not_echoed():
    p = etherscan(lambda r: httpx.Response(200, json=body("keytest_etherscan_invalid")))  # the real answer to a made-up key
    with pytest.raises(ProviderError) as e:
        await p.chain_gas(1)
    assert e.value.kind == "key_required" and KEY not in str(e.value)
    q = etherscan(lambda r: httpx.Response(200, json={"status": "0", "message": "NOTOK", "result": f"bad {KEY}, Max rate limit reached"}))
    with pytest.raises(ProviderError) as e2:
        await q.chain_gas(1)
    assert e2.value.kind == "rate_limited" and KEY not in str(e2.value)


# --- the app: key store, routes, N and history ----------------------------------------------------------------------------

def test_key_specs_and_tests_exist_for_the_three_keyed_sources():
    from openterm.keys import KEY_SPECS, TESTS

    for name, field in (("companies_house", "COMPANIES_HOUSE_KEY"), ("marketaux", "MARKETAUX_KEY"), ("etherscan", "ETHERSCAN_KEY")):
        assert KEY_SPECS[name].fields == (field,) and KEY_SPECS[name].signup.startswith("https://") and name in TESTS
    method, _url, params, headers, _body = TESTS["companies_house"]({"COMPANIES_HOUSE_KEY": "abc"})
    assert method == "GET" and headers["Authorization"] == "Basic " + base64.b64encode(b"abc:").decode() and "abc" not in str(params)


def test_classify_reads_etherscans_200_with_status_0_and_marketauxs_402():
    from openterm.keys import classify

    assert classify(200, json.dumps(body("keytest_etherscan_invalid"))) == "INVALID"
    assert classify(200, json.dumps(body("etherscan_gasoracle_docshape"))) == "OK"
    assert classify(200, json.dumps({"status": "0", "message": "NOTOK", "result": "Max rate limit reached, please use API Key"})) == "QUOTA"
    assert classify(402, '{"error": {"code": "usage_limit_reached"}}') == "QUOTA"
    assert classify(401, "") == "INVALID"


@pytest.mark.parametrize(("name", "field", "path", "params"), [
    ("companies_house", "COMPANIES_HOUSE_KEY", "/api/world/ukco", {"q": "tesco"}),
    ("etherscan", "ETHERSCAN_KEY", "/api/world/addr", {"q": "GAS"}),
])
def test_routes_say_key_required_without_a_key_and_work_with_one(client, name, field, path, params):
    r = client.get(path, params=params)
    assert r.status_code == 424 and r.json()["key"] == field and r.json()["detail"] == f"KEY REQUIRED: set {field} in APIKEYS"
    put = client.put(f"/api/keys/{name}", json={"fields": {field: KEY}})
    assert put.status_code == 200 and put.json()["state"] == "OK" and KEY not in put.text  # fixture mode accepts "docshape" keys
    r = client.get(path, params=params)
    assert r.status_code == 200 and "NOT A RECORDING" in r.json()["source"] and r.json()["age_s"] >= 0 and not r.json()["stale"]


@pytest.mark.parametrize(("name", "field"), [("companies_house", "COMPANIES_HOUSE_KEY"), ("marketaux", "MARKETAUX_KEY"), ("etherscan", "ETHERSCAN_KEY")])
def test_a_key_the_service_would_refuse_is_invalid_and_never_echoed(client, name, field):
    put = client.put(f"/api/keys/{name}", json={"fields": {field: "a-key-the-fixtures-refuse-0123"}})
    assert put.status_code == 200 and put.json()["state"] == "INVALID" and "a-key-the-fixtures-refuse" not in put.text


def test_ukco_company_and_search_over_http(client):
    client.put("/api/keys/companies_house", json={"fields": {"COMPANIES_HOUSE_KEY": KEY}})
    s = client.get("/api/world/ukco", params={"q": "example trading"}).json()
    assert s["data"]["mode"] == "SEARCH" and s["data"]["items"][0]["number"] == "09999999" and "AS FILED" in s["data"]["note"]
    c = client.get("/api/world/ukco", params={"q": "09999999"}).json()["data"]
    assert c["mode"] == "COMPANY" and c["profile"]["name"] == "EXAMPLE TRADING LIMITED" and c["officers"]["active"] == 1 and c["notes"] == []
    missing = client.get("/api/world/ukco", params={"q": "12345678"})
    assert missing.status_code == 404 and missing.json()["error"] == "NO COMPANY WITH NUMBER 12345678"  # not the router's NO DATA FOR SYMBOL
    assert client.get("/api/world/ukco", params={"q": "x"}).status_code == 400


def test_addr_over_http(client):
    client.put("/api/keys/etherscan", json={"fields": {"ETHERSCAN_KEY": KEY}})
    d = client.get("/api/world/addr", params={"q": ADDRESS}).json()["data"]
    assert d["mode"] == "ADDRESS" and d["chain"] == "ETH" and d["coin"] == "ETH" and d["address"] == ADDRESS.lower()
    assert d["balance"]["balance"] > 172774 and d["txs"][0]["dir"] == "IN" and d["gas"]["propose"] == 0.496840168 and "NO PRICES" in d["note"]
    g = client.get("/api/world/addr", params={"q": "gas"}).json()["data"]
    assert g["mode"] == "GAS" and g["gas"]["safe"] == 0.496839934 and g["address"] is None
    assert client.get("/api/world/addr", params={"q": "0x123"}).status_code == 400
    assert client.get("/api/world/addr", params={"q": ""}).status_code == 400


def test_n_adds_marketaux_headlines_with_the_sources_own_sentiment(client):
    client.put("/api/keys/marketaux", json={"fields": {"MARKETAUX_KEY": KEY}})  # before the first fetch: N caches an answer for 120 s
    d = client.get("/api/news", params={"symbol": "AAPL"}).json()
    ours = [i for i in d["data"]["items"] if i["source"].startswith("marketaux")]
    assert sorted(i["sentiment"] for i in ours) == [-0.25, 0.5] and d["data"]["failed"] == []
    assert all(i["sentiment"] is None for i in d["data"]["items"] if not i["source"].startswith("marketaux"))
    top = client.get("/api/news").json()
    assert any(i["source"].startswith("marketaux") and i["sentiment"] == pytest.approx(0.2) for i in top["data"]["items"])


def test_n_without_a_marketaux_key_is_unchanged_and_the_source_is_listed_as_inert(client):
    d = client.get("/api/news", params={"symbol": "AAPL"}).json()
    assert not any(i["source"].startswith("marketaux") for i in d["data"]["items"])
    rows = {p["name"]: p for p in client.get("/api/sources").json()["providers"]}
    assert rows["marketaux"]["calls"] == 0 and rows["companies_house"]["calls"] == 0 and rows["etherscan"]["calls"] == 0
    assert rows["frankfurter"]["hierarchy"]["history"]["rank"] == order_for("history").index("frankfurter") + 1


def test_history_of_an_fx_pair_falls_back_to_the_ecb_fix_and_says_so(client):
    r = client.get("/api/history", params={"symbol": "EURUSD=X", "range": "1Y", "interval": "1d"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "yahoo" in d["fallback_from"] and d["data"]["c"][-1] == 1.1179 and "ECB daily fix" in d["data"]["source"]
    assert d["data"]["o"] == d["data"]["c"] and d["data"]["v"] == [None] * 5


# --- REAL recordings (2026-11-05, the owner's keys): the shapes the live services really send ---------------------------------
VITALIK = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"  # a public address (behind vitalik.eth)


def test_etherscan_real_answers_parse():
    assert ep.balance(ep.result_of(body("etherscan_real_balance")))["balance"] == pytest.approx(5.780441042197210512)
    rows = ep.transactions(ep.result_of(body("etherscan_real_txlist")), VITALIK)
    assert [r["dir"] for r in rows] == ["IN", "IN", "OUT"] and all(r["fee"] is not None and r["block"] for r in rows)
    g = ep.gas(ep.result_of(body("etherscan_real_gasoracle")))
    assert g["last_block"] and 0 < g["safe"] <= g["propose"] <= g["fast"]  # gwei, ordered
    # An address with no transactions: status "0" and message "No transactions found" (confirmed live), read as an empty list, not an error.
    assert ep.transactions(ep.result_of(body("etherscan_real_txlist_empty")), "0x5a1c9d3b7e2f4a6c8d0e1f2a3b4c5d6e7f8a9b0c") == []


async def test_a_chain_outside_the_free_plan_is_unsupported_and_never_trips_the_breaker():
    """Live: a free key answers OP, BASE and BSC with status 0 'Free API access is not supported for this chain'. That used to be
    `unavailable`, so three lookups of a Base address put Etherscan 'down' and Ethereum lookups failed with it."""
    p = etherscan(lambda r: httpx.Response(200, json=body("etherscan_real_chain_not_on_free_plan")))
    router = Router({"etherscan": p}, {"chain": ["etherscan"]})
    for _ in range(5):  # more than TRIP_AFTER
        with pytest.raises(AllFailed) as e:
            await router.call("chain", lambda pr: pr.chain_gas_view(8453))
        assert e.value.kind == "not_found" and "FREE ETHERSCAN PLAN" in str(e.value.errors[0][1])
    assert not router.health["etherscan"].down and router.health["etherscan"].errors == 0


def test_addr_on_a_chain_outside_the_free_plan_says_why_and_ethereum_still_works(client):
    client.put("/api/keys/etherscan", json={"fields": {"ETHERSCAN_KEY": KEY}})
    for _ in range(4):
        r = client.get("/api/world/addr", params={"q": "GAS BASE"})
        assert r.status_code == 404 and "FREE ETHERSCAN PLAN" in r.json()["error"]  # not the generic NO DATA FOR SYMBOL
    assert client.get("/api/world/addr", params={"q": "GAS"}).status_code == 200


def test_companies_house_real_answers_parse():
    s = chp.search(body("companies_house_real_search_tesco"))
    assert s["total"] > 100 and s["items"][0]["number"] == "00445790" and s["items"][0]["name"] == "TESCO PLC"
    p = chp.profile(body("companies_house_real_profile_00000006"))  # a dissolved company: no confirmation statement, no next accounts due
    assert p["name"].startswith("MARINE AND GENERAL") and p["status"] == "dissolved" and p["ceased"] == "2018-07-10"
    assert p["accounts"]["next_due"] is None and p["confirmation"]["next_due"] is None and p["has_charges"] is True
    assert p["address"].endswith("EC4N 6AF, England") and p["sic"] == ["65110"]
    o = chp.officers(body("companies_house_real_officers_00000006"))
    assert o["total"] == 52 and o["active"] == 0 and o["resigned"] == 49  # `inactive_count` (3) is a field of its own
    assert o["items"][0]["role"] in ("SECRETARY", "DIRECTOR") and o["items"][0]["name"].startswith("REDACTED")
    f = chp.filings(body("companies_house_real_filings_00000006"))
    assert f["total"] == 206 and f["items"][0] == {"date": "2018-07-10", "category": "GAZETTE", "type": "GAZ2(A)",
                                                  "description": "GAZETTE DISSOLVED VOLUNTARY", "pages": 1, "paper": True}


async def test_companies_house_real_404_is_not_found_and_trips_nothing():
    p = companies_house(lambda r: httpx.Response(404, json=body("companies_house_real_404")))
    router = Router({"companies_house": p}, {"companies_house": ["companies_house"]})
    for _ in range(5):
        with pytest.raises(AllFailed) as e:
            await router.call("companies_house", lambda pr: pr.ch_company("99999999"))
        assert e.value.kind == "not_found"
    assert not router.health["companies_house"].down


def test_marketaux_real_answer_parses_with_the_requested_companys_sentiment():
    items = mp.parse_news(body("marketaux_real_news_aapl"), "marketaux", "AAPL")
    assert [i.sentiment for i in items] == [0.273, 0.107, -0.202]  # each article's AAPL entity score (0.2732, 0.1071, -0.2023 as sent), rounded to 3 places
    assert all(i.published and i.publisher and i.url.startswith("https://") for i in items)  # `source` is a domain; `published_at` is UTC text
    assert mp.parse_news(body("marketaux_real_news_aapl"), "marketaux", "TSLA")[0].sentiment is None  # filter_entities=true: only AAPL is there
    assert mp.error_of(401, {"error": {"code": "invalid_api_token", "message": "An invalid API token was supplied."}}).kind == "key_required"
