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
