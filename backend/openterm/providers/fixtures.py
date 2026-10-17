"""Replays responses recorded from the real endpoints (backend/tests/fixtures). Exact matches only:
anything not recorded is a 404, so fixture mode can never invent data for an unknown symbol."""

import asyncio
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
SUMMARIES = {"AAPL": "yahoo_summary_aapl", "RELIANCE.NS": "yahoo_summary_reliance_ns"}
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
SEC_FACTS = {320193: "sec_facts_aapl", 789019: "sec_facts_msft"}
SEC_SUBS = {320193: "sec_subs_aapl", 789019: "sec_subs_msft"}
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
LLM_HOSTS = {"openrouter.ai", "api.openai.com", "api.anthropic.com"}
_route_before_llm = _route


def _route(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.host in ("127.0.0.1", "localhost") and url.port == 11434:
        raise httpx.ConnectError("fixture mode: nothing listens on the Ollama port", request=request)
    if url.host == "openrouter.ai" and url.path == "/api/v1/chat/completions":
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
    if p.startswith("/v8/finance/chart/") and q.get("events") == "div,splits":
        return _load("yahoo_chart_aapl_events") if p.endswith("/AAPL") else _load("yahoo_chart_404")
    return None


def _route(request: httpx.Request) -> httpx.Response:
    return _route_phase13(request) or _route_before_phase13(request)
