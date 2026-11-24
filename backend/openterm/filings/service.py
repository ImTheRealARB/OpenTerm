"""The async side of the Phase 29 filings functions: ask the providers through the router, build the table payload, cache it.

Each function is `async def <fn>(svc, ...) -> envelope`, the same shape the UKCO and SECF services have: a thin layer that parses the
user's text (bad input = `DataError("bad_request")`), calls `svc.router.call(<capability>, ...)`, hands the answer to the pure builders in
this package, and caches the result with `svc.swr`. `svc.swr` turns a router `AllFailed` into a `DataError`, so a down source shows
PROVIDER DOWN with its name and a missing key shows KEY REQUIRED, exactly like every other panel.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from ..errkinds import KEY_REQUIRED
from ..errors import DataError
from ..research.table import col, head, payload, section
from ..router import AllFailed
from . import esg as E
from . import fts as F
from . import legal as L
from . import ma as M
from . import people as P
from . import rels as R

SEARCH_TTL_S = 600.0
LIST_TTL_S = 1800.0  # filing lists and enforcement feeds move slowly
EMISSIONS_TTL_S = 86400.0  # a reporting year is published once
MA_DEFAULT_DAYS = 90  # the market-wide MA window when FROM= is not given
COURT_KEY = "COURTLISTENER_API_KEY"


def _bad(e: ValueError) -> DataError:
    return DataError("bad_request", str(e))


async def _company(svc: Any, symbol: str) -> dict[str, Any]:
    """{cik, name, ticker} of a US ticker (SEC ticker-by-exchange file)."""
    who, _ = await svc.router.call("sec_tickers_x", lambda p: p.issuer(symbol), symbol)
    return who


async def _fill_tickers(svc: Any, data: dict[str, Any]) -> None:
    """Rows from the full-text search name a company by CIK, and a Form 4 names no ticker at all. Fill `ticker` from the SEC ticker file so that
    Enter can open FIL. If that file is down the rows keep an empty ticker and a note says so (Enter then opens the filing itself)."""
    rows = [r for s in data["sections"] for r in s["rows"] if r.get("ticker") is None and r.get("cik")]
    if not rows:
        return
    try:
        found, _ = await svc.router.call("sec_tickers_x", lambda p: p.tickers_for(sorted({r["cik"] for r in rows})))
    except AllFailed:
        data["notes"].append("TICKER FILE UNAVAILABLE: ENTER OPENS THE FILING ITSELF INSTEAD OF THE COMPANY'S FILING LIST")
        return
    for r in rows:
        r["ticker"] = found.get(r["cik"])


# --- FTS --------------------------------------------------------------------------------------------------------------------------------


def _fts_payload(title: str, out: dict[str, Any], query: dict[str, str]) -> dict:
    rows = [{
        "date": h["date"], "form": h["form"], "company": " / ".join(n["name"] for n in h["names"]) or None, "file": h["file"],
        "ticker": F.first_ticker(h["names"]), "cik": F.first_cik(h["names"]), "accession": h["accession"], "url": h["url"] or h["index_url"],
    } for h in out["hits"]]
    columns = [col("date", "Filed", "date"), col("form", "Form", "text"), col("company", "Company", "text", 40), col("file", "File", "text", 30)]
    total = out["total"]
    shown = f"{len(rows)} OF {total:,}" if total > len(rows) else str(len(rows))
    return payload(
        None, title, [head("HITS", shown), head("QUERY", " ".join(f"{k}={v}" for k, v in query.items() if k != "dateRange"))],
        [section("hits", "Full-text hits", columns, rows, "NEWEST FIRST, ONE PAGE OF AT MOST 100")],
        notes=[F.ROW_KEYS_NOTE, "SEC EDGAR FULL-TEXT SEARCH: THE SEC'S OWN INDEX, FILINGS FROM 2001. A HIT IS A WORD MATCH, NOT A FINDING"],
        source=out["source"],
    )


async def fts(svc: Any, q: str, forms: str, start: str, end: str, symbol: str) -> dict[str, Any]:
    cik = (await _company(svc, symbol))["cik"] if symbol else None
    try:
        params = F.build_params(q, forms, start, end, cik)
    except ValueError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        out, failed = await svc.router.call("sec_fts", lambda p: p.fts(params))
        data = _fts_payload("FTS " + (q or forms or symbol), out, params)
        await _fill_tickers(svc, data)
        return {"data": data, "fallback_from": failed, "source": out["source"]}

    return await svc.swr("w:fts:" + json.dumps(params, sort_keys=True), SEARCH_TTL_S, fetch)


# --- MA ---------------------------------------------------------------------------------------------------------------------------------


async def ma(svc: Any, symbol: str, start: str, end: str) -> dict[str, Any]:
    if symbol:
        async def fetch_company() -> dict:
            out, failed = await svc.router.call("filings", lambda p: p.filings(symbol), symbol)
            rows = M.rows_from_filings(out["filings"], out["name"] or symbol, symbol)
            scope = f"{out['name']} · ITS {len(out['filings'])} MOST RECENT FILINGS"
            return {"data": M.build_payload(symbol, f"MA {symbol}", rows, out["source"], scope), "fallback_from": failed, "source": out["source"]}

        return await svc.swr(f"w:ma:{symbol.upper()}", LIST_TTL_S, fetch_company)
    try:
        params = F.build_params(forms=M.MARKET_FORMS, start=start or (date.today() - timedelta(days=MA_DEFAULT_DAYS)).isoformat(), end=end)
    except ValueError as e:
        raise _bad(e) from e

    async def fetch_market() -> dict:
        out, failed = await svc.router.call("sec_fts", lambda p: p.fts(params))
        rows = M.rows_from_fts(out["hits"])
        extra = [f"MARKET-WIDE: {len(rows)} OF {out['total']:,} FILINGS SHOWN (NEWEST 100). TYPE A SYMBOL FOR ONE COMPANY'S DEAL FILINGS"] if out["total"] > len(rows) else []
        scope = f"ALL FILERS · {params['startdt']} TO {params['enddt']}"
        data = M.build_payload(None, "MA", rows, out["source"], scope, extra)
        await _fill_tickers(svc, data)
        return {"data": data, "fallback_from": failed, "source": out["source"]}

    return await svc.swr("w:ma:" + json.dumps(params, sort_keys=True), SEARCH_TTL_S, fetch_market)


# --- LEGAL ------------------------------------------------------------------------------------------------------------------------------


async def legal(svc: Any, symbol: str) -> dict[str, Any]:
    who = await _company(svc, symbol)
    company = who["name"]

    async def fetch() -> dict:
        feeds, failed = await svc.router.call("sec_rss", lambda p: p.litigation())
        sec_rows = L.sec_rows(company, feeds["items"])
        court: list[dict[str, Any]] | None = None
        court_note: str | None = None
        key_required: list[dict] = []
        source = feeds["source"]
        try:
            docket, _ = await svc.router.call("court_dockets", lambda p: p.dockets(company))
            court = L.court_rows(company, docket["dockets"])
            source = f"{source} + {docket['source']}"
        except AllFailed as e:
            if e.kind != KEY_REQUIRED:
                raise  # a real outage of CourtListener is shown as an error, not hidden behind the SEC rows
            court_note = f"KEY REQUIRED: set {COURT_KEY} in APIKEYS (COURT DOCKETS NOT SEARCHED)"
            key_required = [{"key": COURT_KEY, "what": "CourtListener court dockets (free)"}]
        return {"data": L.build_payload(symbol, company, sec_rows, court, source, court_note, key_required), "fallback_from": failed, "source": source}

    return await svc.swr(f"w:legal:{symbol.upper()}", LIST_TTL_S, fetch)


# --- BIO --------------------------------------------------------------------------------------------------------------------------------


async def bio(svc: Any, target: str, start: str, end: str) -> dict[str, Any]:
    cik, name = P.parse_target(target)
    if cik is None and len(name) < 3:
        raise DataError("bad_request", "GIVE AN OWNER'S CIK OR NAME, E.G. BIO 1214156 OR BIO \"COOK TIMOTHY\"")
    try:
        params = F.build_params(q=f'"{name}"' if name else "", forms=P.FORMS, start=start, end=end, cik=cik)
    except ValueError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        out, failed = await svc.router.call("sec_fts", lambda p: p.fts(params))
        rows = P.rows_from_fts(out["hits"], cik, name)
        data = P.build_payload(str(cik) if cik else name, rows, out["total"], out["source"])
        await _fill_tickers(svc, data)
        return {"data": data, "fallback_from": failed, "source": out["source"]}

    return await svc.swr("w:bio:" + json.dumps(params, sort_keys=True), LIST_TTL_S, fetch)


# --- RELS -------------------------------------------------------------------------------------------------------------------------------


async def rels(svc: Any, symbol: str) -> dict[str, Any]:
    async def fetch() -> dict:
        who, failed = await svc.router.call("sec_tickers_x", lambda p: p.related(symbol), symbol)
        figi_ticker = who["ticker"].upper().replace("-", "/")  # OpenFIGI writes class shares with a slash (BRK/B)
        figi: list[dict[str, Any]] | None = None
        note: str | None = None
        source = who["source"]
        try:
            mapped, _ = await svc.router.call("figi", lambda p: p.ticker_listings(figi_ticker))
            figi = R.figi_rows(mapped["items"])
            note = None if figi else f"OPENFIGI HAS NO LISTING FOR {figi_ticker}"
            source = f"{source} + {mapped['source']}"
        except AllFailed as e:
            note = f"OPENFIGI UNAVAILABLE: {e}"  # shown beside the SEC rows, which are still good
        return {"data": R.build_payload(symbol, who["name"], who["rows"], figi, note, source), "fallback_from": failed, "source": source}

    return await svc.swr(f"w:rels:{symbol.upper()}", LIST_TTL_S, fetch)


# --- ESG --------------------------------------------------------------------------------------------------------------------------------


async def esg(svc: Any, symbol: str, name: str, year: int) -> dict[str, Any]:
    company = name or (await _company(svc, symbol))["name"]
    core = L.core_name(company)
    if len(core) < L.MIN_NAME_CHARS:
        raise DataError("bad_request", f"COMPANY NAME TOO SHORT TO MATCH: {company[:40]}")

    async def fetch() -> dict:
        out, failed = await svc.router.call("ghg_facilities", lambda p: p.facilities(core, year))
        rows = E.facilities(out["rows"], company)
        return {"data": E.build_payload(symbol or company, company, year, rows, out["source"], out["capped"]), "fallback_from": failed, "source": out["source"]}

    return await svc.swr(f"w:esg:{core}:{year}", EMISSIONS_TTL_S, fetch)
