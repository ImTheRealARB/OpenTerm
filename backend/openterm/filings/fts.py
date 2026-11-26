"""SEC EDGAR full-text search (efts.sec.gov): query building and answer parsing. Pure.

The endpoint is the one behind sec.gov's own "full text search" page. It is not a documented API, so the parser checks the shape it
needs (`hits.hits[]._source`) and raises ValueError when the answer is something else; the provider turns that into PROVIDER DOWN.

An answer looks like (Elasticsearch):  {"hits": {"total": {"value": 3096}, "hits": [{"_id": "<adsh>:<file name>", "_source": {
    "display_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"], "ciks": ["0000320193"], "form": "10-K", "file_date": "2024-11-01",
    "adsh": "0000320193-24-000123", "file_type": "10-K", "period_ending": "2024-09-28", "items": [] ...}}]}}
`_id` after the colon is the document's file name, so a hit maps to one document under /Archives/edgar/data/.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

ENDPOINT = "https://efts.sec.gov/LATEST/search-index"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
EARLIEST = "2001-01-01"  # full-text search covers filings from 2001 on
ROW_KEYS_NOTE = ("ENTER OPENS FIL FOR THE ROW'S COMPANY, FILTERED TO THAT FORM (FIL CANNOT JUMP TO ONE FILING: FIND THE ACCESSION THERE). "
                 "O OPENS THE FILING ON SEC.GOV")
MAX_HITS = 100  # one page of the answer (the endpoint's page size)

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_FORMS = re.compile(r"[A-Za-z0-9 ./,\-]{1,80}\Z")
_CIK_TAIL = re.compile(r"\s*\(CIK (\d+)\)\s*\Z")
_TICKERS = re.compile(r"\(([A-Z0-9][A-Z0-9.,\- ]*)\)\s*\Z")


def pad_cik(cik: int | str) -> str:
    return f"{int(cik):010d}"


def build_params(q: str = "", forms: str = "", start: str = "", end: str = "", cik: int | str | None = None,
                 today: date | None = None) -> dict[str, str]:
    """Query-string parameters for one search. Raises ValueError (text shown to the user) for input the endpoint would misread.

    `start` / `end` are YYYY-MM-DD. The endpoint ignores a date range unless `dateRange=custom` is sent too, and wants both ends.
    `forms` is a comma list; the endpoint matches a form and its amendments ("S-4" also finds "S-4/A")."""
    q = " ".join((q or "").split())
    forms = ",".join(f.strip() for f in (forms or "").split(",") if f.strip())
    if forms and not _FORMS.match(forms):
        raise ValueError(f"BAD FORM LIST: {forms[:40]}")
    for label, v in (("FROM", start), ("TO", end)):
        if v and not _DATE.match(v):
            raise ValueError(f"{label}= NEEDS A DATE AS YYYY-MM-DD")
    if not (q or forms or cik):
        raise ValueError("GIVE WORDS, A FORM= OR A COMPANY")
    out: dict[str, str] = {}
    if q:
        out["q"] = q
    if forms:
        out["forms"] = forms
    if cik:
        out["ciks"] = pad_cik(cik)
    if start or end:
        out["dateRange"] = "custom"
        out["startdt"] = start or EARLIEST
        out["enddt"] = end or (today or date.today()).isoformat()
        if out["startdt"] > out["enddt"]:
            raise ValueError("FROM= IS AFTER TO=")
    return out


def split_display(name: str) -> dict[str, Any]:
    """'Apple Inc.  (AAPL)  (CIK 0000320193)' -> {name, tickers, cik}. Owners have no ticker: 'COOK TIMOTHY D  (CIK 0001214156)'."""
    text = " ".join(str(name).split())
    cik = None
    m = _CIK_TAIL.search(text)
    if m:
        cik = int(m.group(1))
        text = text[: m.start()].rstrip()
    tickers: list[str] = []
    t = _TICKERS.search(text)
    if t:
        tickers = [x.strip() for x in t.group(1).split(",") if x.strip()]
        text = text[: t.start()].rstrip()
    return {"name": text, "tickers": tickers, "cik": cik}


def doc_url(cik: int | str, adsh: str, filename: str) -> str:
    return f"{SEC_ARCHIVE}/{int(cik)}/{adsh.replace('-', '')}/{filename}"


def index_url(cik: int | str, adsh: str) -> str:
    return f"{SEC_ARCHIVE}/{int(cik)}/{adsh.replace('-', '')}/{adsh}-index.htm"


def parse_fts(body: Any) -> dict[str, Any]:
    """{"total": int, "hits": [{date, form, accession, file, names:[{name,tickers,cik}], ciks, period, items, url, index_url}]}."""
    hits_obj = body.get("hits") if isinstance(body, dict) else None
    if not isinstance(hits_obj, dict) or not isinstance(hits_obj.get("hits"), list):
        raise ValueError("SEC FULL-TEXT SEARCH ANSWERED WITH AN UNKNOWN SHAPE")  # noqa: TRY004 (callers catch ValueError for every bad shape)
    total = hits_obj.get("total")
    total_n = int(total.get("value", 0)) if isinstance(total, dict) else int(total or 0)
    out = []
    for h in hits_obj["hits"]:
        s = h.get("_source") or {}
        adsh = str(s.get("adsh") or "")
        file_name = str(h.get("_id") or "").partition(":")[2]
        ciks = [str(c) for c in (s.get("ciks") or [])]
        names = [split_display(n) for n in (s.get("display_names") or [])]
        out.append({
            "date": s.get("file_date"), "form": s.get("form") or s.get("file_type"), "accession": adsh, "file": file_name or None,
            "names": names, "ciks": ciks, "period": s.get("period_ending"), "items": list(s.get("items") or []),
            "description": s.get("file_description"),
            "url": doc_url(ciks[0], adsh, file_name) if ciks and adsh and file_name else None,
            "index_url": index_url(ciks[0], adsh) if ciks and adsh else None,
        })
    return {"total": total_n, "hits": out}


def first_cik(names: list[dict[str, Any]]) -> int | None:
    """The first filer's CIK (the company a row is about; for Forms 3/4/5 the caller picks the issuer instead)."""
    return next((n["cik"] for n in names if n["cik"] is not None), None)


def first_ticker(names: list[dict[str, Any]]) -> str | None:
    """The first listed ticker among a hit's filers (an owner has none), or None."""
    for n in names:
        if n["tickers"]:
            return n["tickers"][0]
    return None
