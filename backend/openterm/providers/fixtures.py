"""Replays responses recorded from the real endpoints (backend/tests/fixtures). Exact matches only:
anything not recorded is a 404, so fixture mode can never invent data for an unknown symbol."""

import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

ROUTES = {
    ("/v8/finance/chart/AAPL", "1y", "1d"): "yahoo_chart_aapl_1y_1d",
    ("/v8/finance/chart/RELIANCE.NS", "1d", "5m"): "yahoo_chart_reliance_1d_5m",
    ("/v1/finance/search", "relian"): "yahoo_search_relian",
    ("/api/quote/AAPL/info", "stocks"): "nasdaq_info_aapl",
}


def _load(name: str) -> httpx.Response:
    rec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return httpx.Response(rec["status"], json=rec["body"])


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    q = request.url.params
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
