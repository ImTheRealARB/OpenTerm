"""Fixture-mode answers for the Phase 30 sources. One checker, `route_macrod`, first in `fixtures.ROUTE_TABLE`.

The recorder (scripts/record_phase30.py) writes `tests/fixtures/phase30_manifest.json`: {canonical request: fixture name}. A canonical
request is host + path + the sorted query parameters WITHOUT the ones that carry a date window or a secret (`IGNORED`), so a replay
still matches next month. Anything not in the manifest on a Phase 30 host is a 404 ("not recorded"): fixture mode never answers a
different question with a recorded answer.

FRED CSVs are not here: they go through the generic `fred_csv_<ID>` route in fixtures.py. Yahoo fund valuations (WPE) are one file
holding every recorded ETF, served per symbol.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
MANIFEST = FIXTURES / "phase30_manifest.json"
IGNORED = frozenset({"api_key", "key", "crumb", "Datefrom", "from", "cosd", "startDate", "endDate"})
HOSTS = frozenset({"markets.newyorkfed.org", "data-api.ecb.europa.eu", "www.bankofengland.co.uk", "www.atlantafed.org",
                   "www.philadelphiafed.org", "www.imf.org", "sdmx.oecd.org", "www.federalreserve.gov", "www.treasurydirect.gov",
                   "usda.library.cornell.edu", "api.eia.gov", "quickstats.nass.usda.gov", "api.frankfurter.dev"})
SHARED_HOSTS = frozenset({"api.frankfurter.dev", "www.bankofengland.co.uk", "www.federalreserve.gov", "data-api.ecb.europa.eu",
                          "www.treasurydirect.gov"})
WPE_FILE ="yahoo_etfval_wpe"
VALUATION_MODULES = "summaryDetail,topHoldings"  # = providers/etf.VALUATION_MODULES (not imported: etf imports this package's parsers)


def canonical(url: str | httpx.URL, params: dict | None = None) -> str:
    u = httpx.URL(str(url), params=params) if params else httpx.URL(str(url))
    q = sorted((k, v) for k, v in u.params.multi_items() if k not in IGNORED)
    return f"{u.host}{u.path}?" + "&".join(f"{k}={v}" for k, v in q)


@cache
def _manifest() -> dict[str, str]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def route_macrod(request: httpx.Request) -> httpx.Response | None:
    from . import fixtures as fx  # imported here: fixtures.py imports this module at the top

    host, p, q = request.url.host, request.url.path, request.url.params
    if p.startswith("/v10/finance/quoteSummary/") and q.get("modules") == VALUATION_MODULES:
        body = json.loads((FIXTURES / f"{WPE_FILE}.json").read_text(encoding="utf-8"))["body"]
        sym = p.rsplit("/", 1)[1]
        if sym in body:
            return httpx.Response(200, json=body[sym])
        return httpx.Response(404, json={"quoteSummary": {"result": None, "error": {"code": "Not Found", "description": "not recorded"}}})
    if host not in HOSTS:
        return None
    name = _manifest().get(canonical(request.url))
    if name:
        return fx._load(name)
    if host in SHARED_HOSTS:
        return None  # older recordings on these hosts (Frankfurter base EUR, BoE curves, FOMC calendar, ECB curve, RATES AUCT) live in fixtures.py
    return httpx.Response(404, text="not recorded")
