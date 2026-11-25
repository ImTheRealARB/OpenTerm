"""Fixture-mode answers for the Phase 29 filings sources (FTS, MA, LEGAL, BIO, RELS, ESG). One checker, `route_filings`, listed in
`fixtures.ROUTE_TABLE`; it answers a request or returns None ("not mine"), like every other checker there.

REAL recordings (scripts/record_phase29.py): the SEC full-text answers, the two SEC enforcement feeds, the ticker-by-exchange file (trimmed
to the listed issuers), the OpenFIGI ticker mapping for GOOGL and the EPA GHGRP join for ALCOA, year 2023.
DOC-SHAPED (labelled NOT A RECORDING in the file): the CourtListener answers, because that source needs a key.

A full-text search is replayed ONLY for the exact query that was recorded (same words, forms, company and dates). Any other query is
"not recorded": fixture mode never answers a different question with the same hits.
"""

from __future__ import annotations

import json

import httpx

# (q without quotes, forms, ciks, startdt, enddt) -> fixture name
FTS_RECORDED = {
    ("going concern", "10-K", "", "2024-01-01", "2024-12-31"): "fts_going_concern_10k",
    ("", "SC TO-T,DEFM14A,S-4,425", "", "2024-10-01", "2024-12-31"): "fts_ma_market",
    ("", "3,4,5", "0001214156", "2023-01-01", "2025-12-31"): "fts_bio_1214156",
    ("Timothy Cook", "DEF 14A", "", "2023-01-01", "2025-12-31"): "fts_bio_proxy_timothy_cook",
}
SEC_FEEDS = {
    "/enforcement-litigation/litigation-releases/rss": "sec_litigation_releases_rss",
    "/enforcement-litigation/administrative-proceedings/rss": "sec_admin_proceedings_rss",
}
NOT_RECORDED = "not recorded"
SIC_RECORDED = {"3571", "7372", "6331", "7370"}


def route_filings(request: httpx.Request) -> httpx.Response | None:
    from . import fixtures as fx  # imported here: fixtures.py imports this module at the top

    host, p, q = request.url.host, request.url.path, request.url.params
    if host == "efts.sec.gov" and p == "/LATEST/search-index":
        key = (q.get("q", "").replace('"', "").strip(), q.get("forms", ""), q.get("ciks", ""), q.get("startdt", ""), q.get("enddt", ""))
        name = FTS_RECORDED.get(key)
        return fx._load(name) if name else httpx.Response(404, text=NOT_RECORDED)
    if host == "www.sec.gov":
        if p == "/files/company_tickers_exchange.json":
            return fx._load("sec_company_tickers_exchange")
        if p in SEC_FEEDS:
            return fx._load(SEC_FEEDS[p])
        if p == "/search-filings/standard-industrial-classification-sic-code-list":
            return fx._load("sec_sic_list")
        if p == "/cgi-bin/browse-edgar" and q.get("SIC"):
            # TRIMMED RECORDINGS (scripts/record_gaps_28_32.py): one entry each for Apple, Microsoft, Berkshire and Meta; any other code is "not recorded".
            code = q.get("SIC", "")
            return fx._load(f"sec_sic_{code}") if code in SIC_RECORDED else httpx.Response(404, text=NOT_RECORDED)
        return None
    if host == "api.openfigi.com" and p == "/v3/mapping" and request.method == "POST":
        jobs = json.loads(request.content or b"[]")
        if not jobs or not all(j.get("idType") == "TICKER" for j in jobs):
            return None  # an ISIN / CUSIP lookup: the SECF checker answers it
        table = json.loads((fx.FIXTURES / "openfigi_ticker_googl.json").read_text(encoding="utf-8"))["body"]
        answers = [table.get(j.get("idValue")) for j in jobs]
        return httpx.Response(404, text=NOT_RECORDED) if any(a is None for a in answers) else httpx.Response(200, json=answers)
    if host == "www.courtlistener.com":
        # Doc-shaped: a key is accepted only when it starts with "docshape" (the other keyed fixtures do the same).
        if not request.headers.get("authorization", "").removeprefix("Token ").startswith("docshape"):
            return fx._load("keytest_courtlistener_401")
        if p == "/api/rest/v4/search/":
            return fx._load("courtlistener_dockets_docshape")
        if p == "/api/rest/v4/courts/":
            return fx._load("courtlistener_courts_docshape")
        return httpx.Response(404, text=NOT_RECORDED)
    if host == "data.epa.gov":
        if "/PARENT_COMPANY/CONTAINING/ALCOA/YEAR/2023/" in p:
            return fx._load("epa_ghgrp_alcoa_2023")
        return httpx.Response(404, text=NOT_RECORDED)
    return None
