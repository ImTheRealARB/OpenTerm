"""FEDREG: the US Federal Register (keyless), the government's daily journal of rules, proposed rules, notices and presidential documents.

Pure request builder and parser; `providers/usgov.py` does the HTTP. Shape checked live on 2026-11-05 (recordings `tests/fixtures/fedreg_real_*.json`):

  GET https://www.federalregister.gov/api/v1/documents.json
        ?conditions[term]=<words>&conditions[type][]=RULE|PRORULE|NOTICE|PRESDOCU&order=newest&per_page=N&fields[]=title&fields[]=type ...
    -> {"description": "Documents matching '...'", "count": 3828, "total_pages": 50, "next_page_url": "...",
        "results": [{"title", "type": "Rule|Proposed Rule|Notice|Presidential Document", "agency_names": ["..."],
                     "publication_date": "2026-11-05", "abstract": "..." | null, "document_number": "2026-22576", "html_url": "https://..."}]}
    A search with no match has NO "results" key at all: {"description": "...", "count": 0}.

A document is the text AS PUBLISHED by an agency; the abstract is the agency's own summary (some notices have none).
"""

from __future__ import annotations

from typing import Any

from .usgov import UsGovError, clip, text_or_none

SOURCE = "FEDERALREGISTER.GOV"
PER_PAGE = 25
MAX_QUERY = 100
# What the user types -> the API's type code, and the label the panel shows.
TYPES = {"RULE": "RULE", "PROPOSED": "PRORULE", "NOTICE": "NOTICE", "PRESDOC": "PRESDOCU"}
LABELS = {"RULE": "RULES", "PRORULE": "PROPOSED RULES", "NOTICE": "NOTICES", "PRESDOCU": "PRESIDENTIAL DOCUMENTS"}
FIELDS = ("title", "type", "agency_names", "publication_date", "abstract", "document_number", "html_url")

NOTE = ("US FEDERAL REGISTER DOCUMENTS AS PUBLISHED, NEWEST FIRST. THE ABSTRACT IS THE AGENCY'S OWN SUMMARY, NOT OPENTERM'S; "
        "SOME NOTICES HAVE NONE. ENTER SHOWS IT; OPEN THE LINK ID ON FEDERALREGISTER.GOV FOR THE FULL TEXT.")


def parse_query(q: str) -> tuple[str | None, str]:
    """(type code or None, search words). `FEDREG RULE chips` -> ("RULE", "chips"); a bare type word filters with no words; empty = latest of all."""
    words = " ".join((q or "").split())
    if len(words) > MAX_QUERY:
        raise UsGovError("bad_request", f"KEEP THE SEARCH UNDER {MAX_QUERY} CHARACTERS")
    head, _, rest = words.partition(" ")
    if head.upper() in TYPES:
        return TYPES[head.upper()], rest.strip()
    return None, words


def params(type_code: str | None, words: str) -> list[tuple[str, str]]:
    """The query string as (name, value) pairs (the API wants repeated `fields[]` keys, which a dict cannot hold)."""
    out: list[tuple[str, str]] = []
    if words:
        out.append(("conditions[term]", words))
    if type_code:
        out.append(("conditions[type][]", type_code))
    out += [("order", "newest"), ("per_page", str(PER_PAGE))]
    out += [("fields[]", f) for f in FIELDS]
    return out


def parse(body: Any, type_code: str | None, words: str) -> dict[str, Any]:
    """The panel payload. `count == 0` with no `results` key is the documented empty answer; anything else without a results list is an error."""
    if not isinstance(body, dict) or not isinstance(body.get("count"), int):
        raise UsGovError("unavailable", "FEDERAL REGISTER: UNEXPECTED ANSWER SHAPE (NO 'count')")
    total = body["count"]
    results = body.get("results")
    if results is None and total == 0:
        results = []
    if not isinstance(results, list):
        raise UsGovError("unavailable", "FEDERAL REGISTER: UNEXPECTED ANSWER SHAPE (NO 'results' LIST)")
    items = []
    for r in results:
        if not isinstance(r, dict) or not r.get("document_number") or not r.get("title"):
            raise UsGovError("unavailable", "FEDERAL REGISTER: A DOCUMENT HAS NO NUMBER OR TITLE")
        agencies = r.get("agency_names")
        items.append({
            "number": str(r["document_number"]), "title": clip(r["title"], 200), "type": text_or_none(r.get("type")) or "UNKNOWN",
            "agencies": [a for a in agencies if isinstance(a, str)] if isinstance(agencies, list) else [],
            "date": text_or_none(r.get("publication_date")), "abstract": clip(r.get("abstract"), 600) or None,
            "url": text_or_none(r.get("html_url")),
        })
    return {"query": words, "type": LABELS.get(type_code or ""), "total": total, "shown": len(items), "items": items, "note": NOTE}
