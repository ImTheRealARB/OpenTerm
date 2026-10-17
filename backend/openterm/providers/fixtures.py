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
# Simulated upstream latency (bench "cold network" budget). 0 = instant.
LATENCY_S = float(os.environ.get("OPENTERM_FIXTURE_LATENCY_MS", "0")) / 1000


def _load(name: str) -> httpx.Response:
    rec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return httpx.Response(rec["status"], json=rec["body"])


async def _handler(request: httpx.Request) -> httpx.Response:
    if LATENCY_S:
        await asyncio.sleep(LATENCY_S)
    return _route(request)


def _route(request: httpx.Request) -> httpx.Response:
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
