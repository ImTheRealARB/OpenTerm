"""Replays responses recorded from the real endpoints (backend/tests/fixtures). Exact matches only:
anything not recorded is a 404, so fixture mode can never invent data for an unknown symbol."""

import asyncio
import base64
import json
import os
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

ROUTES = {
    ("/v8/finance/chart/AAPL", "1y", "1d"): "yahoo_chart_aapl_1y_1d",
    ("/v8/finance/chart/RELIANCE.NS", "1d", "5m"): "yahoo_chart_reliance_1d_5m",
    ("/v1/finance/search", "relian"): "yahoo_search_relian",
    ("/api/quote/AAPL/info", "stocks"): "nasdaq_info_aapl",
}
SUMMARIES = {"AAPL": "yahoo_summary_aapl", "RELIANCE.NS": "yahoo_summary_reliance_ns", "MSFT": "yahoo_summary_msft", "META": "yahoo_summary_meta"}
# Path-only routes (one recording each). Unrecorded queries on these hosts are 404s.
PATHS = {
    "/rs/search/combinedcms/view.xml": "rss_cnbc",
    "/public/rss/mw_topstories": "rss_marketwatch",
    "/news/business/rss.xml": "rss_bbc",
    "/markets/rssfeeds/1977021501.cms": "rss_et",
    "/rss/markets": "rss_mint",
    "/api/marketmovers": "nasdaq_movers",
    "/api/v3/ticker/24hr": "binance_24hr",
}
# Phase 12: Binance klines / funding (BTCUSDT only; any other symbol is a 404, never invented data).
BINANCE_KLINES = {"/api/v3/klines": "binance_spot_klines_btcusdt_1d", "/fapi/v1/klines": "binance_perp_klines_btcusdt_1d",
                  "/fapi/v1/fundingRate": "binance_perp_funding_btcusdt"}
YAHOO_RSS = {"AAPL": "yahoo_rss_aapl"}
GDELT = {"nvidia": "gdelt_nvidia"}
COINGECKO = {"usd": "coingecko_markets_usd"}
# Simulated upstream latency (bench "cold network" budget). 0 = instant.
LATENCY_S = float(os.environ.get("OPENTERM_FIXTURE_LATENCY_MS", "0")) / 1000


def _load(name: str) -> httpx.Response:
    rec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    if "b64" in rec:  # binary answers (the Ken French zips) are recorded as base64
        return httpx.Response(rec["status"], content=base64.b64decode(rec["b64"]), headers={"content-type": rec["content_type"]})
    if "text" in rec:  # XML feeds and plain-text answers are recorded as text
        return httpx.Response(rec["status"], text=rec["text"], headers={"content-type": rec["content_type"]})
    return httpx.Response(rec["status"], json=rec["body"])


def _keyed(table: dict[str, str], key: str) -> httpx.Response:
    return _load(table[key]) if key in table else httpx.Response(404, text="not recorded")


async def _handler(request: httpx.Request) -> httpx.Response:
    if LATENCY_S:
        await asyncio.sleep(LATENCY_S)
    return _route(request)


def _route(request: httpx.Request) -> httpx.Response:
    if (r6 := _route_phase6(request)) is not None:  # Phase 6
        return r6
    p = request.url.path
    q = request.url.params
    if request.url.host == "fc.yahoo.com":
        return httpx.Response(404, text="")
    if p == "/v1/test/getcrumb":
        return httpx.Response(200, text="fixturecrumb")
    if p.startswith("/v10/finance/quoteSummary/"):
        sym = p.rsplit("/", 1)[1]
        if sym in SUMMARIES:
            return _load(SUMMARIES[sym])
        return httpx.Response(404, json={"quoteSummary": {"result": None, "error": {"code": "Not Found"}}})
    if p in PATHS:
        return _load(PATHS[p])
    if p in BINANCE_KLINES:
        return _load(BINANCE_KLINES[p]) if q.get("symbol") == "BTCUSDT" else httpx.Response(400, json={"code": -1121})
    if p == "/rss/2.0/headline":
        return _keyed(YAHOO_RSS, q.get("s", ""))
    if p == "/api/v2/doc/doc":
        return _keyed(GDELT, (q.get("query") or "").split(" ")[0].strip('"').lower())
    if p == "/api/v3/coins/markets":
        return _keyed(COINGECKO, q.get("vs_currency", ""))
    if p == "/api/company/AAPL/company-profile":
        return _load("nasdaq_profile_aapl")
    if p == "/v7/finance/spark":
        rec = json.loads((FIXTURES / "yahoo_spark.json").read_text(encoding="utf-8"))
        wanted = set(q.get("symbols", "").split(","))
        rec["body"]["spark"]["result"] = [r for r in rec["body"]["spark"]["result"] if r["symbol"] in wanted]
        return httpx.Response(200, json=rec["body"])
    for key in [(p, q.get("range"), q.get("interval")), (p, (q.get("q") or "").lower()), (p, q.get("assetclass"))]:
        if key in ROUTES:
            return _load(ROUTES[key])
    if p.startswith("/v8/finance/chart/"):
        return _load("yahoo_chart_404")
    # Nasdaq answers unknown symbols / wrong asset class with 200 and data: null.
    return httpx.Response(200, json={"data": None, "status": {"rCode": 400}})


def fixture_transport() -> httpx.MockTransport:
    return httpx.MockTransport(_handler)


# --- Phase 6: SEC EDGAR + Yahoo ownership ---
# sec_facts_*: us-gaap tags in sec_parse.TAGS only, 10-K/10-Q facts ending 2014 or later.
# sec_subs_*: filings.recent cut to the first 60 entries. sec_company_tickers: AAPL, MSFT, BRK-B only.
# sec_form4/<accession>: raw Form 4 XML of the 20 latest AAPL Form 4s in sec_subs_aapl.
SEC_FACTS = {320193: "sec_facts_aapl", 789019: "sec_facts_msft", 1326801: "sec_facts_meta"}
SEC_SUBS = {320193: "sec_subs_aapl", 789019: "sec_subs_msft", 884394: "sec_subs_spy_trust", 1067983: "sec_subs_berkshire"}
YAHOO_OWN = {("AAPL", "holders"): "yahoo_holders_aapl", ("AAPL", "insiders"): "yahoo_insiders_aapl"}


def _route_phase6(request: httpx.Request) -> httpx.Response | None:
    host, p = request.url.host, request.url.path
    if host == "www.sec.gov" and p == "/files/company_tickers.json":
        return _load("sec_company_tickers")
    if host == "data.sec.gov":
        for prefix, table in (("/api/xbrl/companyfacts/CIK", SEC_FACTS), ("/submissions/CIK", SEC_SUBS)):
            if p.startswith(prefix) and p.endswith(".json"):
                cik = p[len(prefix):-5]
                return _keyed({str(k): v for k, v in table.items()}, str(int(cik)) if cik.isdigit() else cik)
        return httpx.Response(404, text="not recorded")
    if host == "www.sec.gov" and p.startswith("/Archives/edgar/data/"):
        parts = p.split("/")  # /Archives/edgar/data/<cik>/<accession without dashes>/<document>
        acc = parts[5] if len(parts) > 6 else ""
        dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}" if len(acc) == 18 else ""
        if dashed and (FIXTURES / "sec_form4" / f"{dashed}.json").exists():
            return _load(f"sec_form4/{dashed}")
        return httpx.Response(404, text="not recorded")
    if p.startswith("/v10/finance/quoteSummary/"):
        mods = request.url.params.get("modules", "")
        kind = "holders" if "institutionOwnership" in mods else "insiders" if "insiderTransactions" in mods else None
        if kind:
            name = YAHOO_OWN.get((p.rsplit("/", 1)[1], kind))
            if name:
                return _load(name)
            return httpx.Response(404, json={"quoteSummary": {"result": None, "error": {"code": "Not Found"}}})
    return None

# --- Phase 7: macro (FRED CSV + API, Treasury curve, Nasdaq earnings, BLS/BEA ICS) ---
# Recorded 2026-10-17. fred_csv_<ID>: real fredgraph.csv answers (cosd=2021-10-01, GDP full history);
# fred_csv_dgs_curve: real multi-series answer trimmed to rows since 2025-09-01; fred_csv_404: real 404, body trimmed.
# fred_api_no_key: real answer without a key. fred_api_docshape_*: BUILT from the documented API shape (no key was
# available to record), with values copied from the real CSV / BLS recordings. Routed only when a key is sent.
_PHASE7_DGS = "DGS1MO,DGS3MO,DGS6MO,DGS1,DGS2,DGS3,DGS5,DGS7,DGS10,DGS20,DGS30"
_PHASE7_API = {
    ("series", "GDP"): "fred_api_docshape_series_GDP",
    ("series/observations", "GDP"): "fred_api_docshape_observations_GDP",
    ("releases/dates", None): "fred_api_docshape_releases_dates",
}
_route_before_phase7 = _route


def _route_phase7(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "fred.stlouisfed.org" and p == "/graph/fredgraph.csv":
        sid = q.get("id", "")
        name = "fred_csv_dgs_curve" if sid == _PHASE7_DGS else f"fred_csv_{sid}"
        return _load(name if (FIXTURES / f"{name}.json").exists() else "fred_csv_404")
    if host == "api.stlouisfed.org" and p.startswith("/fred/"):
        if not q.get("api_key"):
            return _load("fred_api_no_key")
        path = p.removeprefix("/fred/")
        if path == "series/search":
            if "inflation" in (q.get("search_text") or "").lower():
                return _load("fred_api_docshape_search_inflation")
            return httpx.Response(200, json={"count": 0, "offset": 0, "limit": 50, "seriess": []})
        name = _PHASE7_API.get((path, q.get("series_id")))
        if name:
            return _load(name)
        # Documented FRED error shape for an unknown series id.
        return httpx.Response(400, json={"error_code": 400, "error_message": "Bad Request.  The series does not exist."})
    if host == "home.treasury.gov" and "/daily-treasury-rates.csv/" in p:
        year = p.split("/daily-treasury-rates.csv/", 1)[1].split("/", 1)[0]
        return _keyed({"2025": "treasury_curve_2025", "2026": "treasury_curve_2026"}, year)
    if p == "/api/calendar/earnings":
        day = q.get("date", "")
        name = f"nasdaq_earnings_{day}"
        return _load(name) if (FIXTURES / f"{name}.json").exists() else httpx.Response(404, text="not recorded")
    if host == "www.bls.gov" and p == "/schedule/news_release/bls.ics":
        return _load("bls_schedule_ics")
    if host == "www.bea.gov" and p == "/news/schedule/ics/online-calendar-subscription.ics":
        return _load("bea_schedule_ics")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase7(request) or _route_before_phase7(request)

# --- Phase 9: screener + peers ---
# nasdaq_screener_trimmed.json is the real 2026-10-17 answer (7,002 rows) trimmed to 476 rows: the 250 largest by
# market cap plus every 30th of the rest, kept in the original order. Nothing else was edited.
PATHS.update({
    "/api/screener/stocks": "nasdaq_screener_trimmed",
    "/v6/finance/recommendationsbysymbol/AAPL": "yahoo_recs_aapl",
    # Real answer for an unknown symbol (ZZZZNOPE): 200 with an empty result list.
    "/v6/finance/recommendationsbysymbol/ZZZZNOPE": "yahoo_recs_empty",
})


# --- Phase 11: key tests (APIKEYS) ---
# keytest_*_401: real answers to a made-up key, recorded 2026-10-18 with no account. keytest_openrouter_ok is built
# from OpenRouter's docs for GET /api/v1/key (no key was available), marked "doc_shaped" in the file.
KEY_TESTS = {
    ("finnhub.io", "/api/v1/quote"): "keytest_finnhub_401",
    ("api.openai.com", "/v1/models"): "keytest_openai_401",
    ("api.anthropic.com", "/v1/models"): "keytest_anthropic_401",
    ("openrouter.ai", "/api/v1/key"): "keytest_openrouter_ok",
}
_route_before_phase11 = _route


def _route(request: httpx.Request) -> httpx.Response:
    if (name := KEY_TESTS.get((request.url.host, request.url.path))) is not None:
        return _load(name)
    return _route_before_phase11(request)


# --- Phase 11 step 5: LLM gateway ---
# Nothing listens for Ollama in fixture mode. OpenRouter chat replays the one recorded stream when it exists
# (llm_openrouter_stream.txt, raw SSE); every other LLM call is "not recorded".
LLM_HOSTS = {"openrouter.ai", "api.openai.com", "api.anthropic.com", "opencode.ai", "api.deepseek.com", "api.groq.com",
             "api.mistral.ai", "api.x.ai", "api.together.xyz", "api.fireworks.ai", "generativelanguage.googleapis.com"}
_route_before_llm = _route


def _route(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.host in ("127.0.0.1", "localhost") and url.port == 11434:
        raise httpx.ConnectError("fixture mode: nothing listens on the Ollama port", request=request)
    if url.host == "openrouter.ai" and url.path == "/api/v1/models" and (FIXTURES / "llm_openrouter_models.json").exists():
        # Phase 16: the price list the gateway needs before any call, cut to the five models SETTINGS AI offers (recorded 2026-10-18).
        return httpx.Response(200, content=(FIXTURES / "llm_openrouter_models.json").read_bytes(), headers={"content-type": "application/json"})
    if url.host == "openrouter.ai" and url.path == "/api/v1/chat/completions":
        # Phase 16: a request that offers tools replays the recorded tool turn (call, then the answer once a tool result is in the messages);
        # anything else replays the plain stream. The recordings are real OpenRouter answers about AAPL, labelled RECORDED in the panel.
        body = json.loads(request.content or b"{}")
        if body.get("tools"):
            done = any(m.get("role") == "tool" for m in body.get("messages") or [])
            tool_rec = FIXTURES / ("llm_tool_turn2.txt" if done else "llm_tool_turn1.txt")
            if tool_rec.exists():
                return httpx.Response(200, content=tool_rec.read_bytes(), headers={"content-type": "text/event-stream"})
        rec = FIXTURES / "llm_openrouter_stream.txt"
        if rec.exists():
            return httpx.Response(200, content=rec.read_bytes(), headers={"content-type": "text/event-stream"})
    if url.host in LLM_HOSTS and (url.host, url.path) not in KEY_TESTS:
        return httpx.Response(404, text="not recorded")
    return _route_before_llm(request)

# --- Phase 12: BT (10-year daily bars, recorded 2026-10-19 by scripts/record_phase12.py) ---
ROUTES.update({
    ("/v8/finance/chart/AAPL", "10y", "1d"): "yahoo_chart_aapl_10y_1d",
    ("/v8/finance/chart/SPY", "10y", "1d"): "yahoo_chart_spy_10y_1d",
    ("/v8/finance/chart/RELIANCE.NS", "10y", "1d"): "yahoo_chart_reliance_10y_1d",
    ("/v8/finance/chart/^NSEI", "10y", "1d"): "yahoo_chart_nsei_10y_1d",
})

# --- Phase 13: research (recorded 2026-10-18 by scripts/record_phase13.py) ---
# Yahoo quoteSummary answers are matched on the exact module list a provider method asks for; the profile call
# ("assetProfile,summaryDetail,...") never matches. yahoo_summary_aapl_ratings is trimmed to the newest 40 rating changes.
YAHOO_RESEARCH = {
    ("AAPL", "earningsTrend,earningsHistory"): "yahoo_summary_aapl_estimates",
    ("AAPL", "recommendationTrend,upgradeDowngradeHistory,financialData"): "yahoo_summary_aapl_ratings",
    ("AAPL", "assetProfile"): "yahoo_summary_aapl_profile",
    ("AAPL", "defaultKeyStatistics,summaryDetail"): "yahoo_summary_aapl_keystats",
    ("SPY", "topHoldings,fundProfile,quoteType"): "yahoo_summary_spy_fund",
}
_YAHOO_RESEARCH_MODULES = {m for _, m in YAHOO_RESEARCH}
_route_before_phase13 = _route


def _route_phase13(request: httpx.Request) -> httpx.Response | None:
    p, q = request.url.path, request.url.params
    if p.startswith("/v10/finance/quoteSummary/") and q.get("modules") in _YAHOO_RESEARCH_MODULES:
        name = YAHOO_RESEARCH.get((p.rsplit("/", 1)[1], q.get("modules", "")))
        if name:
            return _load(name)
        return httpx.Response(404, json={"quoteSummary": {"result": None, "error": {"code": "Not Found"}}})
    if request.url.host == "api.nasdaq.com":
        quote = {"/api/quote/AAPL/dividends": "nasdaq_dividends_aapl", "/api/quote/AAPL/short-interest": "nasdaq_shortinterest_aapl",
                 "/api/company/AAPL/earnings-surprise": "nasdaq_earnings_surprise_aapl"}
        if p in quote:
            return _load(quote[p])
        if p == "/api/ipo/calendar":
            name = f"nasdaq_ipo_{q.get('date')}"
            return _load(name) if (FIXTURES / f"{name}.json").exists() else httpx.Response(200, json={"data": None, "status": {"rCode": 400}})
    if request.url.host == "www.sec.gov":
        # Archives: N-PORT primary_doc (SPY trust) and 13F information tables (Berkshire), looked up by accession
        parts = p.split("/")
        if p == "/files/company_tickers_mf.json":
            return _load("sec_company_tickers_mf")
        if p.startswith("/Archives/edgar/data/") and len(parts) > 6:
            acc, doc = parts[5], parts[6]
            dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}" if len(acc) == 18 else ""
            hits = sorted(FIXTURES.glob(f"sec_nport_*_{dashed}.json")) if dashed else []
            if doc == "primary_doc.xml" and hits:
                return _load(hits[0].stem)
            if doc == "index.json" and (FIXTURES / f"sec_index_{dashed}.json").exists():
                return _load(f"sec_index_{dashed}")
            for name in ((f"sec_13f_primary_{dashed}",) if doc == "primary_doc.xml" else (f"sec_13f_{dashed}",)):
                if dashed and (FIXTURES / f"{name}.json").exists():
                    return _load(name)
    if request.url.host == "cdn.finra.org" and p.startswith("/equity/regsho/daily/CNMSshvol"):
        name = "finra_shvol_" + p.rsplit("CNMSshvol", 1)[1].removesuffix(".txt")
        return _load(name) if (FIXTURES / f"{name}.json").exists() else httpx.Response(404, text="not recorded")
    if p.startswith("/v8/finance/chart/") and q.get("events") == "div,splits":
        return _load("yahoo_chart_aapl_events") if p.endswith("/AAPL") else _load("yahoo_chart_404")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase13(request) or _route_before_phase13(request)


# --- Phase 13 step 6: keyed sources (doc-shaped fixtures, labelled in each file; only AAPL and the market feed) ---
# A request without the key header is answered 401 like the real services do.
KEYED_ROUTES = {
    ("finnhub.io", "/api/v1/company-news", "AAPL"): "finnhub_company_news_aapl",
    ("finnhub.io", "/api/v1/news", None): "finnhub_news_general",
    ("finnhub.io", "/api/v1/stock/recommendation", "AAPL"): "finnhub_recommendation_aapl",
    ("finnhub.io", "/api/v1/stock/earnings", "AAPL"): "finnhub_earnings_aapl",
    ("data.alpaca.markets", "/v1beta1/news", "AAPL"): "alpaca_news_aapl",
    ("data.alpaca.markets", "/v1beta1/news", None): "alpaca_news_all",
}
_route_before_keyed = _route


def _route(request: httpx.Request) -> httpx.Response:
    host, p, q = request.url.host, request.url.path, request.url.params
    if (host == "finnhub.io" and p != "/api/v1/quote") or host == "data.alpaca.markets":
        authed = request.headers.get("x-finnhub-token") if host == "finnhub.io" else request.headers.get("apca-api-key-id")
        if not authed:
            return httpx.Response(401, json={"error": "Invalid API key"})
        name = KEYED_ROUTES.get((host, p, q.get("symbol") or q.get("symbols")))
        if name:
            return _load(name)
        return httpx.Response(200, json=[] if host == "finnhub.io" else {"news": [], "next_page_token": None})
    return _route_before_keyed(request)

# --- Phase 14: options, rates, futures (recorded 2026-10-18 by scripts/record_phase14.py) ---
# yahoo_options_aapl_<expiry epoch>: the eight expiries pick_expiries chooses, strikes trimmed to 65%..135% of spot. Any other symbol
# or expiry is a 404 (never invented). Tradier fixtures are DOC-SHAPED (marked in each file): no sandbox token was available.
OPTION_NEAREST = "1792368000"
_route_before_phase14 = _route


def _route_phase14(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if p.startswith("/v7/finance/options/"):
        name = f"yahoo_options_aapl_{q.get('date') or OPTION_NEAREST}"
        if p.endswith("/AAPL") and (FIXTURES / f"{name}.json").exists():
            return _load(name)
        return httpx.Response(404, json={"optionChain": {"result": None, "error": {"code": "Not Found"}}})
    if host == "sandbox.tradier.com":
        if not request.headers.get("authorization", "").startswith("Bearer ") or len(request.headers["authorization"]) < 12:
            return httpx.Response(401, json={"fault": {"faultstring": "Invalid Access Token"}})
        if p == "/v1/markets/options/expirations" and q.get("symbol") == "AAPL":
            return _load("tradier_expirations_aapl")
        if p == "/v1/markets/options/chains" and q.get("symbol") == "AAPL" and q.get("expiration") == "2026-12-18":
            return _load("tradier_chain_aapl_2026-12-18")
        if p == "/v1/markets/quotes" and q.get("symbols") == "AAPL":
            return _load("tradier_quote_aapl")
        return httpx.Response(404, text="not recorded")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase14(request) or _route_before_phase14(request)


# --- Phase 14 step 5: Deribit (BTC only; four expiries kept in deribit_book_btc, any other currency is a 400 like the real API) ---
_route_before_deribit = _route


def _route(request: httpx.Request) -> httpx.Response:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "www.deribit.com":
        if p.endswith("/get_book_summary_by_currency") and q.get("currency") == "BTC":
            return _load("deribit_book_btc")
        if p.endswith("/get_index_price") and q.get("index_name") == "btc_usd":
            return _load("deribit_index_btc")
        return httpx.Response(400, json={"error": {"message": "Invalid params", "code": -32602}})
    return _route_before_deribit(request)


# --- Phase 14 step 6: rates views (ECB, BoE, BoC, MoF, TreasuryDirect; FRED OAS goes through the fred_csv_<ID> route above) ---
_route_before_rates = _route


def _route(request: httpx.Request) -> httpx.Response:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "data-api.ecb.europa.eu":
        return _load("ecb_yc_spot") if p.startswith("/service/data/YC/") and "SR_10Y" in p else httpx.Response(404, text="not recorded")
    if host == "www.bankofengland.co.uk":
        ok = p.endswith("/_iadb-fromshowcolumns.asp") and q.get("SeriesCodes") == "IUDSNPY,IUDMNPY,IUDLNPY"
        return _load("boe_par_yields") if ok else httpx.Response(404, text="not recorded")
    if host == "www.bankofcanada.ca":
        return _load("boc_yields") if p.endswith("/observations/group/bond_yields_benchmark/json") else httpx.Response(404, text="not recorded")
    if host == "www.mof.go.jp":
        return _load("mof_jgb") if p.endswith("/jgbcme_all.csv") else httpx.Response(404, text="not recorded")
    if host == "www.treasurydirect.gov":
        if p.endswith("/securities/auctioned"):
            return _load("treasurydirect_auctioned")
        if p.endswith("/securities/upcoming"):
            return _load("treasurydirect_upcoming")
        return httpx.Response(404, text="not recorded")
    return _route_before_rates(request)


# --- Phase 14 step 7: futures contracts (CT, WIRP), CFTC COT, FOMC calendar ---
# yahoo_chart_fut_<symbol>: one recorded v8/chart per contract (a contract that was not recorded is a 404, like Yahoo's). cftc_legacy_<tag>:
# four markets by contract code. cftc_markets answers the distinct-name query. fomc_calendar: the recorded federalreserve.gov page.
_COT_TAGS = {"13874A": "es", "067651": "cl", "088691": "gc", "043602": "zn"}
_route_before_futures = _route


def _route(request: httpx.Request) -> httpx.Response:
    host, p, q = request.url.host, request.url.path, request.url.params
    if p.startswith("/v8/finance/chart/") and (FIXTURES / f"yahoo_chart_fut_{p.rsplit('/', 1)[-1].replace('.', '_')}.json").exists():
        return _load(f"yahoo_chart_fut_{p.rsplit('/', 1)[-1].replace('.', '_')}")
    if host == "publicreporting.cftc.gov":
        if q.get("$group"):
            return _load("cftc_markets")
        code = next((c for c in _COT_TAGS if f"'{c}'" in q.get("$where", "")), None)
        return _load(f"cftc_legacy_{_COT_TAGS[code]}") if code else httpx.Response(200, json=[])
    if host == "www.federalreserve.gov" and p.endswith("/fomccalendars.htm"):
        return _load("fomc_calendar")
    return _route_before_futures(request)


# --- Phase 15 step 3: 20y daily charts (RISK stress windows) and the SPDR sector ETFs (PORT ATTR) ---
# Exact recordings first (the routes above win). A shorter DAILY range of a symbol that has a longer recorded daily chart is sliced
# from it, newest bar backwards: so 1y/2y/3y/5y answer for SPY, AAPL (20y) and the 11 SPDR ETFs (3y).
ROUTES.update({
    ("/v8/finance/chart/SPY", "20y", "1d"): "yahoo_chart_spy_20y_1d",
    ("/v8/finance/chart/AAPL", "20y", "1d"): "yahoo_chart_aapl_20y_1d",
    **{(f"/v8/finance/chart/{e.upper()}", "3y", "1d"): f"yahoo_chart_{e}_3y_1d"
       for e in ("xlk", "xlf", "xlv", "xly", "xlp", "xle", "xli", "xlb", "xlu", "xlre", "xlc")},
})
_SLICE_DAYS = {"1y": 366, "2y": 731, "3y": 1096, "5y": 1827, "10y": 3653}
_route_before_slice = _route


def _sliced_chart(path: str, rng: str) -> httpx.Response | None:
    days = _SLICE_DAYS[rng]
    for longer in ("20y", "10y", "5y", "3y"):
        if _SLICE_DAYS.get(longer, 7305) <= days:
            continue
        name = ROUTES.get((path, longer, "1d"))
        if name is None:
            continue
        rec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        res = rec["body"]["chart"]["result"][0]
        ts = res["timestamp"]
        cut = ts[-1] - days * 86400
        keep = [i for i, t in enumerate(ts) if t >= cut]
        res["timestamp"] = [ts[i] for i in keep]
        for block in res["indicators"].values():
            for series in block:
                for k, v in series.items():
                    series[k] = [v[i] for i in keep]
        res.setdefault("meta", {})["range"] = rng
        return httpx.Response(rec["status"], json=rec["body"])
    return None


def _route(request: httpx.Request) -> httpx.Response:
    p, q = request.url.path, request.url.params
    wanted = (p, q.get("range"), "1d")
    if p.startswith("/v8/finance/chart/") and q.get("interval") == "1d" and q.get("range") in _SLICE_DAYS and not q.get("events")             and wanted not in ROUTES:
        sliced = _sliced_chart(p, q["range"])
        if sliced is not None:
            return sliced
    return _route_before_slice(request)


# --- Phase 15 step 4: Ken French daily factor zips (FACT), recorded as base64 ---
_KEN_FRENCH = {"F-F_Research_Data_5_Factors_2x3_daily_CSV.zip": "kenfrench_ff5_daily", "F-F_Momentum_Factor_daily_CSV.zip": "kenfrench_mom_daily"}
_route_before_kenfrench = _route


def _route(request: httpx.Request) -> httpx.Response:
    if request.url.host == "mba.tuck.dartmouth.edu":
        name = _KEN_FRENCH.get(request.url.path.rsplit("/", 1)[-1])
        return _load(name) if name else httpx.Response(404, text="not recorded")
    return _route_before_kenfrench(request)


# --- Phase 15 steps 6-7: Zerodha Kite Connect (READ-ONLY). Fixtures are DOC-SHAPED, labelled NOT A RECORDING in each file. ---
# POST /session/token answers only for the test trio below (checksum = sha256(api_key + request_token + api_secret)), else 403
# InputException. With env OPENTERM_KITE_EXPIRED=1 every authenticated call answers the TokenException fixture with 403.
KITE_KEY, KITE_SECRET, KITE_REQUEST_TOKEN = "docshape_api_key", "docshape_secret", "docshape_request_token"
KITE_HISTORICAL = {"738561": "kite_historical_reliance_day_docshape", "9000001": "kite_historical_nifty_fut_day_oi_docshape"}
_route_before_kite = _route


def _kite_json(name: str, status: int | None = None) -> httpx.Response:
    rec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    code = status or rec["status"]
    if "text" in rec:
        return httpx.Response(code, text=rec["text"], headers={"content-type": rec.get("content_type", "text/csv")})
    return httpx.Response(code, json=rec["body"])


def _kite_error(status: int, error_type: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"status": "error", "message": message, "data": None, "error_type": error_type})


def _route(request: httpx.Request) -> httpx.Response:
    if request.url.host != "api.kite.trade":
        return _route_before_kite(request)
    import hashlib
    from urllib.parse import parse_qs

    p, q = request.url.path, request.url.params
    if request.method == "POST" and p == "/session/token":
        form = {k: v[0] for k, v in parse_qs(request.content.decode("utf-8")).items()}
        want = hashlib.sha256((form.get("api_key", "") + form.get("request_token", "") + KITE_SECRET).encode()).hexdigest()
        if form.get("api_key") == KITE_KEY and form.get("request_token") == KITE_REQUEST_TOKEN and form.get("checksum") == want:
            return _kite_json("kite_session_token_docshape")
        return _kite_error(403, "InputException", "Invalid `checksum` or `request_token`.")
    if os.environ.get("OPENTERM_KITE_EXPIRED") == "1" or not request.headers.get("authorization", "").startswith("token "):
        return _kite_json("kite_error_token_docshape", 403)
    if request.method != "GET":
        return httpx.Response(405, text="not recorded")
    if p == "/instruments":
        return _kite_json("kite_instruments_docshape")
    if p == "/quote":
        data = json.loads((FIXTURES / "kite_quote_nifty_docshape.json").read_text(encoding="utf-8"))["body"]["data"]
        # REAL recording (2026-11-05) of RELIANCE and SENSEX fills in keys the doc-shaped chain file lacks. NIFTY 50 stays doc-shaped
        # (25000.0) because the option-chain tests are built on that spot price.
        data = json.loads((FIXTURES / "kite_quote_reliance_nifty_sensex_real.json").read_text(encoding="utf-8"))["body"]["data"] | data
        return httpx.Response(200, json={"status": "success", "data": {k: data[k] for k in q.get_list("i") if k in data}})
    if p.startswith("/instruments/historical/"):
        token = p.split("/")[3] if len(p.split("/")) > 3 else ""
        if token == "738561" and p.endswith("/5minute"):
            return _kite_json("kite_historical_reliance_5m_real")  # REAL recording, 3 days of RELIANCE 5 minute bars
        return _kite_json(KITE_HISTORICAL[token]) if token in KITE_HISTORICAL else _kite_error(400, "InputException", "Invalid instrument token.")
    return httpx.Response(404, text="not recorded")


# --- Phase 19 step 4: OpenFIGI mapping (openfigi_mapping.json = real answers per identifier; anything else is not recorded, never invented) ---
_route_before_phase19 = _route


def _route_phase19(request: httpx.Request) -> httpx.Response | None:
    if request.url.host == "api.openfigi.com" and request.url.path == "/v3/mapping" and request.method == "POST":
        table = json.loads((FIXTURES / "openfigi_mapping.json").read_text(encoding="utf-8"))["body"]
        jobs = json.loads(request.content)
        answers = [table.get(f"{j.get('idType')}:{j.get('idValue')}") for j in jobs]
        if any(a is None for a in answers):
            return httpx.Response(404, text="not recorded")
        return httpx.Response(200, json=answers)
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase19(request) or _route_before_phase19(request)


# --- Phase 19 step 5: World Bank, DBnomics, Nager.Date, policy rates (recordings from scripts/record_phase19.py 5) ---
_WB_WECO = {"NY.GDP.MKTP.KD.ZG": "gdp_growth", "FP.CPI.TOTL.ZG": "inflation", "SL.UEM.TOTL.ZS": "unemployment",
            "GC.DOD.TOTL.GD.ZS": "debt_gdp", "BN.CAB.XOKA.GD.ZS": "current_account"}
_route_before_phase19b = _route


def _route_phase19b(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "api.worldbank.org":
        parts = p.strip("/").split("/")  # v2/country/<codes>[/indicator/<code>]
        if len(parts) == 3:
            return _load("worldbank_countries_g20") if ";" in parts[2] else httpx.Response(404, text="not recorded")
        if len(parts) == 5 and ";" in parts[2] and q.get("mrnev") and parts[4] in _WB_WECO:
            return _load("worldbank_g20_" + _WB_WECO[parts[4]])
        if len(parts) == 5 and parts[2] == "USA" and parts[4] == "NY.GDP.MKTP.KD.ZG":
            return _load("worldbank_usa_gdp_growth")
        if len(parts) == 5 and parts[2] == "USA" and parts[4] == "NY.GDP.PCAP.CD":
            return _load("worldbank_usa_gdppc")
        if len(parts) == 5 and parts[3] == "indicator":  # World Bank answers an unknown pairing with an error message list
            return httpx.Response(200, json=[{"message": [{"id": "175", "key": "Invalid format", "value": "not recorded (fixture)"}]}])
        return httpx.Response(404, text="not recorded")
    if host == "api.db.nomics.world":
        return _load("dbnomics_imf_weo_usa_ngdp_rpch") if p.endswith("/IMF/WEO:latest/USA.NGDP_RPCH") else httpx.Response(404, text="not recorded")
    if host == "date.nager.at":
        cc = p.rsplit("/", 1)[-1].lower()
        year = p.rsplit("/", 2)[-2]
        if year == "2026" and cc in ("gb", "jp", "hk"):
            return _load(f"nager_{cc}_2026")
        return httpx.Response(204) if cc == "in" else httpx.Response(404, text="not recorded")
    if host == "data-api.ecb.europa.eu" and "MRR_FR" in p:
        return _load("ecb_policy_rate_mrr")
    if host == "www.bankofcanada.ca" and p.endswith("/observations/V39079/json"):
        return _load("boc_policy_rate")
    if host == "www.bankofengland.co.uk" and q.get("SeriesCodes") == "IUDBEDR":
        return _load("boe_bank_rate")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase19b(request) or _route_before_phase19b(request)


# --- Phase 19 step 6: Open-Meteo, NWS alerts (recordings from scripts/record_phase19.py 6; FRED energy CSVs go through the fred_csv_<ID> route) ---
_route_before_phase19c = _route
_NWS_POINTS = {(29.76, -95.37): "nws_alerts_houston", (34.1471, -98.5971): "nws_alerts_point"}  # matched within 0.01 degrees


def _route_phase19c(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "api.open-meteo.com" and p == "/v1/forecast":
        lat = q.get("latitude", "")
        if "," in lat:
            return _load("openmeteo_forecast_basket")
        return _load("openmeteo_forecast_houston") if lat.startswith("29.76") else httpx.Response(404, text="not recorded")
    if host == "geocoding-api.open-meteo.com":
        name = q.get("name", "").strip().lower()
        return _load({"houston": "openmeteo_geocode_houston", "zzqqxxvv": "openmeteo_geocode_nowhere"}[name]) if name in ("houston", "zzqqxxvv") else httpx.Response(404, text="not recorded")
    if host == "api.weather.gov" and p == "/alerts/active":
        try:
            lat, lon = (float(x) for x in q.get("point", "").split(","))
        except ValueError:
            return httpx.Response(404, text="not recorded")
        name = next((n for (a, b), n in _NWS_POINTS.items() if abs(a - lat) < 0.01 and abs(b - lon) < 0.01), None)
        return _load(name) if name else httpx.Response(404, text="not recorded")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase19c(request) or _route_before_phase19c(request)


# --- Phase 19 step 8: Polymarket and Kalshi (recordings from scripts/record_phase19.py 8; one market and its history each, anything else is not recorded) ---
_route_before_phase19e = _route
_POLY_ID, _POLY_TOKEN_OF = "665374", "polymarket_market_665374"
_KALSHI_TICKER = "KXOAIANTH-40-ANTH"


def _route_phase19e(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "gamma-api.polymarket.com":
        if p == "/markets":
            return _load("polymarket_markets_closed" if q.get("closed") == "true" else "polymarket_markets")
        if p == f"/markets/{_POLY_ID}":
            return _load(_POLY_TOKEN_OF)
        return httpx.Response(404, text="not recorded")
    if host == "clob.polymarket.com" and p == "/prices-history":
        token = json.loads(json.loads((FIXTURES / f"{_POLY_TOKEN_OF}.json").read_text(encoding="utf-8"))["body"]["clobTokenIds"])[0]
        return _load("polymarket_prices_history") if q.get("market") == token else httpx.Response(404, text="not recorded")
    if host == "api.elections.kalshi.com":
        if p == "/trade-api/v2/markets":
            return _load("kalshi_markets")
        if p == f"/trade-api/v2/markets/{_KALSHI_TICKER}":
            return _load(f"kalshi_market_{_KALSHI_TICKER}")
        if p == f"/trade-api/v2/series/KXOAIANTH/markets/{_KALSHI_TICKER}/candlesticks":
            return _load("kalshi_candlesticks")
        return httpx.Response(404, text="not recorded")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase19e(request) or _route_before_phase19e(request)


# --- Phase 19 step 9: NSE bhavcopy day files and AMFI NAVAll.txt (recordings from scripts/record_phase19.py 9). A day with no recording answers
# the recorded 404 (so it reads as a holiday: fixture mode never invents a day file). NAVAll.txt answers 302 first, as the real host does. ---
_route_before_phase19f = _route


def _route_phase19f(request: httpx.Request) -> httpx.Response | None:
    host, p = request.url.host, request.url.path
    if host == "nsearchives.nseindia.com":
        stem = p.rsplit("/", 1)[-1]  # BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip
        ymd = stem[len("BhavCopy_NSE_CM_0_0_0_"):][:8] if stem.startswith("BhavCopy_NSE_CM_0_0_0_") else ""
        return _load(f"nse_bhavcopy_{ymd}") if ymd.isdigit() and (FIXTURES / f"nse_bhavcopy_{ymd}.json").exists() else _load("nse_bhavcopy_404")
    if host == "www.amfiindia.com" and p == "/spages/NAVAll.txt":
        return httpx.Response(302, headers={"location": "https://portal.amfiindia.com/spages/NAVAll.txt"}, text="Object moved")
    if host == "portal.amfiindia.com" and p == "/spages/NAVAll.txt":
        return _load("amfi_navall")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase19f(request) or _route_before_phase19f(request)


# --- Phase 19 step 7: Binance depth / premium / funding info, OKX v5 public, DefiLlama stablecoins + yields (recordings from scripts/record_phase19.py 7).
# BTCUSDT / BTC-USDT only; OKX single-instrument answers are the matching row of the recorded all-instrument answer. `fapi/v1/fundingRate` keeps its Phase 12 route. ---
_route_before_phase19h = _route
_BINANCE_19H = {("/api/v3/depth", "BTCUSDT"): "binance_depth_btcusdt", ("/fapi/v1/premiumIndex", "BTCUSDT"): "binance_premium_btcusdt",
                ("/fapi/v1/premiumIndex", ""): "binance_premium_all", ("/fapi/v1/fundingInfo", ""): "binance_funding_info"}
_OKX_ALL = {"/api/v5/public/funding-rate": "okx_funding_any", "/api/v5/public/mark-price": "okx_mark_swap", "/api/v5/market/index-tickers": "okx_index_usdt"}
_OKX_NONE = {"code": "51001", "msg": "Instrument ID does not exist (not recorded)", "data": []}


def _okx_rows(name: str, inst: str) -> httpx.Response:
    body = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]
    rows = [x for x in body["data"] if x.get("instId") == inst]
    return httpx.Response(200, json={**body, "data": rows}) if rows else httpx.Response(200, json=_OKX_NONE)


def _route_phase19h(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host in ("api.binance.com", "fapi.binance.com") and p in ("/api/v3/depth", "/fapi/v1/premiumIndex", "/fapi/v1/fundingInfo"):
        name = _BINANCE_19H.get((p, q.get("symbol", "")))
        return _load(name) if name else httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
    if host == "www.okx.com":
        if p == "/api/v5/market/books":
            return _load("okx_books_btcusdt") if q.get("instId") == "BTC-USDT" else httpx.Response(200, json=_OKX_NONE)
        if p in _OKX_ALL:
            inst = q.get("instId", "")
            if p == "/api/v5/public/funding-rate" and inst == "ANY" or p != "/api/v5/public/funding-rate" and not inst:
                return _load(_OKX_ALL[p])
            return _okx_rows(_OKX_ALL[p], inst)
        if p == "/api/v5/public/funding-rate-history":
            return _load("okx_funding_history_btc") if q.get("instId") == "BTC-USDT-SWAP" else httpx.Response(200, json=_OKX_NONE)
        if p == "/api/v5/public/liquidation-orders":
            return _load("okx_liq_btcusdt") if q.get("uly") == "BTC-USDT" else httpx.Response(200, json=_OKX_NONE)
        if p == "/api/v5/public/instruments":
            return _load("okx_instruments_btcusdt") if q.get("uly") == "BTC-USDT" else httpx.Response(200, json=_OKX_NONE)
        return httpx.Response(404, text="not recorded")
    if host == "stablecoins.llama.fi":
        return _load("llama_stablecoins") if p == "/stablecoins" else httpx.Response(404, text="not recorded")
    if host == "yields.llama.fi":
        return _load("llama_yields") if p == "/pools" else httpx.Response(404, text="not recorded")
    if host == "api.llama.fi" and p.startswith("/emissions"):
        return _load("llama_emissions_probe")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase19h(request) or _route_before_phase19h(request)


# --- SHIP: IMF PortWatch chokepoints (recorded 2026-11-05 from the real ArcGIS layer; where= is ignored, one page of 868 rows) ---
_route_before_portwatch = _route


def _route_portwatch(request: httpx.Request) -> httpx.Response | None:
    if request.url.host == "services9.arcgis.com" and request.url.path.endswith("/Daily_Chokepoints_Data/FeatureServer/0/query"):
        q = request.url.params
        if q.get("resultOffset", "0") != "0":
            return httpx.Response(200, json={"features": []})  # the recording fits in one page
        if q.get("where", "").startswith("portid="):
            return _load("portwatch_probe")
        return _load("portwatch_chokepoints_daily")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_portwatch(request) or _route_before_portwatch(request)


# --- Trade + US macro family (UN Comtrade, BLS, BEA, Census): ALL DOC-SHAPED, no key was available to record real answers ---
# Every file is marked `doc_shaped` and its numbers are invented. A request without a key gets the 401 (or in-body error) the real
# service gives; the key value "invalid-fixture-key" gets the "wrong key" answer. Unrecorded combinations are 404 / 204 / empty.
_BAD_KEY = "invalid-fixture-key"
_route_before_tradeus = _route


def _route_tradeus(request: httpx.Request) -> httpx.Response | None:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "comtradeapi.un.org":
        key = request.headers.get("ocp-apim-subscription-key", "")
        if not key or key == _BAD_KEY:
            return httpx.Response(401, json={"statusCode": 401, "message": "Access denied due to invalid subscription key (fixture text)."})
        if q.get("maxrecords"):  # the APIKEYS key test (1 record): any data proves the key
            return _load("comtrade_docshape_usa_chn_total")
        ok = q.get("reporterCode") == "842" and q.get("partnerCode") == "156" and q.get("cmdCode") == "TOTAL"
        return _load("comtrade_docshape_usa_chn_total" if ok else "comtrade_docshape_empty")
    if host == "api.bls.gov":
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            return httpx.Response(400, text="bad json")
        key = body.get("registrationkey", "")
        if not key or key == _BAD_KEY:
            return _load("bls_docshape_bad_key")
        rec = json.loads((FIXTURES / "bls_docshape_series.json").read_text(encoding="utf-8"))
        wanted = set(body.get("seriesid", []))
        rec["body"]["Results"]["series"] = [s for s in rec["body"]["Results"]["series"] if s["seriesID"] in wanted]
        return httpx.Response(200, json=rec["body"])
    if host == "apps.bea.gov" and p == "/api/data":
        if not q.get("UserID") or q.get("UserID") == _BAD_KEY:
            return _load("bea_docshape_bad_userid")
        if q.get("method", "").upper() == "GETDATASETLIST":
            return _load("bea_docshape_datasetlist")
        ds, table, ind = q.get("datasetname"), q.get("TableName"), q.get("Indicator")
        if ds == "NIPA" and table in ("T10101", "T10105"):
            return _load(f"bea_docshape_nipa_{table}")
        if ds == "ITA" and ind in ("BalGds", "BalServ", "BalCurrAcct"):
            return _load(f"bea_docshape_ita_{ind}")
        if ds == "GDPbyIndustry":
            return _load("bea_docshape_gdpbyindustry")
        return httpx.Response(200, json={"BEAAPI": {"Results": {"Data": []}}})
    if host == "api.census.gov" and p.startswith("/data/timeseries/"):
        if not q.get("key") or q.get("key") == _BAD_KEY:
            return httpx.Response(401, text="Invalid Key (fixture text)")
        if p.endswith("/eits/marts"):
            rec = json.loads((FIXTURES / "census_docshape_marts.json").read_text(encoding="utf-8"))
            wanted = set((q.get("category_code") or "").split(","))
            head, rows = rec["body"][0], rec["body"][1:]
            i = head.index("category_code")
            return httpx.Response(200, json=[head, *[r for r in rows if not wanted or r[i] in wanted]])
        for flow, col in (("exports", "E_COMMODITY"), ("imports", "I_COMMODITY")):
            if p.endswith(f"/intltrade/{flow}/hs"):
                if q.get(col) == "85" and q.get("CTY_CODE") == "5700":
                    return _load(f"census_docshape_{flow}_hs85_china")
                return httpx.Response(204)
        return httpx.Response(404, text="not recorded")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_tradeus(request) or _route_before_tradeus(request)


# --- Frankfurter (real recording), Companies House, Marketaux, Etherscan (doc-shaped, marked in each file) ---
# Fixture mode accepts only keys that start with "docshape" for the three keyed hosts and answers every other key with that service's
# invalid-key answer (Etherscan's is a real recording, Marketaux's status is real, Companies House's is a placeholder).
_DOCSHAPE_KEY = "docshape"
_ETHERSCAN = {("account", "balance"): "etherscan_balance_docshape", ("account", "txlist"): "etherscan_txlist_docshape",
              ("gastracker", "gasoracle"): "etherscan_gasoracle_docshape"}
_CH_PATHS = {"/search/companies": "companies_house_search_docshape", "/company/09999999": "companies_house_profile_docshape",
             "/company/09999999/officers": "companies_house_officers_docshape", "/company/09999999/filing-history": "companies_house_filings_docshape"}
_route_before_freesrc = _route


def _ch_user(request: httpx.Request) -> str:
    """The user-name half of a basic-auth header (Companies House: the API key), or '' when absent or malformed."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return ""
    try:
        return base64.b64decode(token).decode("utf-8").partition(":")[0]
    except ValueError:
        return ""


def _route(request: httpx.Request) -> httpx.Response:
    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "api.frankfurter.dev":
        if p == "/v2/rates" and q.get("base") == "EUR" and q.get("providers") == "ecb":
            wanted = set((q.get("quotes") or "").split(","))
            rows = [r for r in json.loads((FIXTURES / "frankfurter_rates_eur_usd_inr.json").read_text(encoding="utf-8"))["body"] if r["quote"] in wanted]
            if rows:
                return httpx.Response(200, json=rows)
        return httpx.Response(404, json={"status": 404, "message": "not recorded"})
    if host == "api.etherscan.io":
        if not q.get("apikey", "").startswith(_DOCSHAPE_KEY):
            return _load("keytest_etherscan_invalid")
        name = _ETHERSCAN.get((q.get("module"), q.get("action")))
        return _load(name) if name else httpx.Response(404, text="not recorded")
    if host == "api.marketaux.com":
        if not q.get("api_token", "").startswith(_DOCSHAPE_KEY):
            return _load("keytest_marketaux_401")
        name = "marketaux_news_aapl_docshape" if q.get("symbols") == "AAPL" else "marketaux_news_top_docshape" if not q.get("symbols") else None
        return _load(name) if name else httpx.Response(200, json={"meta": {"found": 0, "returned": 0, "limit": 3, "page": 1}, "data": []})
    if host == "api.company-information.service.gov.uk":
        if not _ch_user(request).startswith(_DOCSHAPE_KEY):
            return _load("keytest_companies_house_401")
        name = _CH_PATHS.get(p)
        return _load(name) if name else httpx.Response(404, json={"errors": [{"type": "ch:service", "error": "company-profile-not-found"}]})
    return _route_before_freesrc(request)


# --- DBSRCH: DBnomics dataset and series search (REAL recordings from scripts/record_dbsearch.py) ---
# Recorded: datasets for "france inflation" / "OECD unemployment" / a no-match word, and the series of BDF/ICP and OECD/DSD_TAXBEN_NRR@DF_NRR
# (first page only). Every other search, other page or other dataset answers 404 "not recorded", like the rest of this file.
_route_before_dbsearch = _route
_DBS_DATASETS = {"france inflation": "dbnomics_search_france_inflation", "oecd unemployment": "dbnomics_search_oecd_unemployment",
                 "zzqxjw": "dbnomics_search_nomatch"}
_DBS_SERIES = {("BDF", "ICP", "france inflation"): "dbnomics_series_bdf_icp_france_inflation",
               ("OECD", "DSD_TAXBEN_NRR@DF_NRR", "oecd unemployment"): "dbnomics_series_oecd_nrr_oecd_unemployment"}


def _route_dbsearch(request: httpx.Request) -> httpx.Response | None:
    if request.url.host != "api.db.nomics.world":
        return None
    p, q = request.url.path, request.url.params
    if q.get("offset", "0") != "0":
        return httpx.Response(404, text="not recorded")  # only the first page of each search was recorded
    words = (q.get("q") or "").lower()
    if p == "/v22/search":
        name = _DBS_DATASETS.get(words)
        return _load(name) if name else httpx.Response(404, text="not recorded")
    parts = p.split("/")  # ["", "v22", "series", provider, dataset] for a series LIST (a 5th part would be one series: older routes answer)
    if len(parts) == 5 and parts[1:3] == ["v22", "series"]:
        name = _DBS_SERIES.get((parts[3], parts[4], words))
        return _load(name) if name else httpx.Response(404, text="not recorded")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_dbsearch(request) or _route_before_dbsearch(request)


# --- PORTS: IMF PortWatch daily port activity (recorded 2026-11-05 from the real ArcGIS layers) ---
# Daily_Ports_Data: the max(date) answer, the 25-busiest-ports sum, and the daily rows of those 25 ports (the route filters them by the
# ids and the date in the request, as the real service would). PortWatch_ports_database: only ROTTERDAM and BELGIUM were recorded; any
# other words answer with no ports, which is what a search that matches nothing gets.
_route_before_ports = _route


def _route_ports(request: httpx.Request) -> httpx.Response | None:
    if request.url.host != "services9.arcgis.com":
        return None
    p, q = request.url.path, request.url.params
    where = q.get("where", "")
    if p.endswith("/Daily_Ports_Data/FeatureServer/0/query"):
        if q.get("outStatistics"):
            kind = json.loads(q["outStatistics"])[0]["statisticType"]
            return _load("portwatch_ports_newest" if kind == "max" else "portwatch_ports_top25")
        if q.get("resultOffset", "0") != "0" or "IN (" not in where:
            return httpx.Response(200, json={"features": []})
        ids = set(where.split("IN (")[1].split(")")[0].replace("'", "").split(","))
        since = where.split("DATE '")[1][:10]  # ISO dates compare correctly as text
        rec = json.loads((FIXTURES / "portwatch_ports_daily_top25.json").read_text(encoding="utf-8"))
        rows = [f for f in rec["body"]["features"] if f["attributes"]["portid"] in ids and f["attributes"]["date"] >= since]
        return httpx.Response(200, json={"features": rows})
    if p.endswith("/PortWatch_ports_database/FeatureServer/0/query"):
        if "'%ROTTERDAM%'" in where:
            return _load("portwatch_ports_db_rotterdam")
        if "'%BELGIUM%'" in where:
            return _load("portwatch_ports_db_belgium")
        return httpx.Response(200, json={"features": []})
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_ports(request) or _route_before_ports(request)
