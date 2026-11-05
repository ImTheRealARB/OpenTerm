"""CONGRESS: US bills from the Congress.gov API v3 (key CONGRESS_API_KEY from api.data.gov, free). Pure request builders and parsers.

DOC-SHAPED, NOT RUN AGAINST A LIVE KEY: no key was available when this was written, so the shapes below come from the API documentation
(https://api.congress.gov and https://github.com/LibraryOfCongress/api.congress.gov) and `congress_*_docshape.json` hold INVENTED bills in that shape
(each file says "NOT A RECORDING"). Only the gateway's answers to no key / a made-up key were checked live (`keytest_datagov_congress_*.json`: HTTP 403).

  GET /v3/bill?format=json&limit=N&sort=updateDate+desc
    -> {"bills": [{"congress": 119, "type": "HR", "number": "1234", "title": "...", "originChamber": "House", "originChamberCode": "H",
                   "latestAction": {"actionDate": "2026-11-03", "text": "..."}, "updateDate": "2026-11-04", "url": "..."}],
        "pagination": {"count": 20000, "next": "..."}}                        (the LIST has NO sponsor)
  GET /v3/bill/<congress>/<type lower>/<number>?format=json
    -> {"bill": {"congress", "type", "number", "title", "originChamber", "introducedDate", "policyArea": {"name"},
                 "sponsors": [{"fullName", "party", "state", "district", "bioguideId"}], "cosponsors": {"count"},
                 "latestAction": {"actionDate", "text"}, "updateDate", "legislationUrl"}}

As far as the documentation shows, the bill list has no text-search parameter. So `CONGRESS <words>` filters TITLES inside the most recently updated
bills it can fetch in one call, and says so; it is not a search of the whole record. (Unverified without a key; the panel states the limit.)
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .usgov import UsGovError, clip, need_list, num, text_or_none

SOURCE = "CONGRESS.GOV API"
LIST_LIMIT = 250  # the API's documented maximum page size; one call, filtered here
SHOWN_LIMIT = 40
LATEST_SHOWN = 25
MIN_QUERY = 2
MAX_QUERY = 80
# URL spelling of each bill type (lowercase in the path) and how people write them
BILL_TYPES = ("HR", "S", "HJRES", "SJRES", "HCONRES", "SCONRES", "HRES", "SRES")
_BILL_REF = re.compile(r"^(?:(\d{2,3})\s+)?(" + "|".join(sorted(BILL_TYPES, key=len, reverse=True)) + r")\s*(\d{1,5})$")

NOTE = ("BILLS AS RECORDED BY CONGRESS.GOV (LIBRARY OF CONGRESS). THE LATEST ACTION IS THE NEWEST STEP RECORDED, NOT A PREDICTION OF WHETHER A BILL PASSES. "
        "THE LIST HAS NO SPONSOR: ENTER OPENS A BILL FOR ITS SPONSOR AND DETAILS.")
FILTER_NOTE = ("NO FULL-TEXT SEARCH: YOUR WORDS ARE MATCHED AGAINST THE TITLES OF THE {n} MOST RECENTLY UPDATED BILLS ONLY, SO OLDER BILLS CAN BE MISSING. "
               "TO OPEN ONE BILL TYPE ITS NUMBER, FOR EXAMPLE CONGRESS HR 1234.")


def current_congress(today: date) -> int:
    """The Congress in session on `today`. The 1st met in 1789 and each lasts two years starting in an odd year (3 Jan), so 2025-2026 is the 119th."""
    year = today.year if today.month > 1 or today.day >= 3 else today.year - 1  # early January of an odd year still belongs to the old Congress until the 3rd
    return (year - 1789) // 2 + 1


def parse_query(q: str, today: date) -> tuple[str, Any]:
    """('latest', None) | ('bill', (congress, type, number)) | ('words', [lowercase words]). A bill reference is `HR 1234`, `H.R. 1234`, `119 S 55`."""
    text = " ".join((q or "").split())
    if not text:
        return "latest", None
    m = _BILL_REF.match(" ".join(text.replace(".", "").upper().split()))  # "h.r. 1234" -> "HR 1234"; the dots are kept for word searches
    if m:
        return "bill", (int(m.group(1)) if m.group(1) else current_congress(today), m.group(2), int(m.group(3)))
    if len(text) < MIN_QUERY or len(text) > MAX_QUERY:
        raise UsGovError("bad_request", f"GIVE WORDS OF {MIN_QUERY} TO {MAX_QUERY} CHARACTERS, A BILL NUMBER SUCH AS HR 1234, OR NOTHING FOR THE LATEST BILLS")
    return "words", text.lower().split()


def list_params(limit: int) -> dict[str, Any]:
    return {"format": "json", "limit": limit, "sort": "updateDate desc"}  # the space is sent as "+" on the wire: updateDate+desc


def _action(a: Any) -> tuple[str | None, str]:
    if not isinstance(a, dict):
        return None, ""
    return text_or_none(a.get("actionDate")), clip(a.get("text"), 200)


def parse_list(body: Any) -> list[dict[str, Any]]:
    rows = []
    for b in need_list(body, "bills", "CONGRESS BILLS"):
        if not isinstance(b, dict) or not b.get("number") or not b.get("type") or not isinstance(b.get("congress"), int):
            raise UsGovError("unavailable", "CONGRESS BILLS: A ROW HAS NO CONGRESS, TYPE OR NUMBER")
        when, text = _action(b.get("latestAction"))
        rows.append({
            "congress": b["congress"], "type": str(b["type"]).upper(), "number": str(b["number"]), "title": clip(b.get("title"), 220),
            "chamber": text_or_none(b.get("originChamber")), "action_date": when, "action": text, "updated": text_or_none(b.get("updateDate")),
        })
    return rows


def filter_words(rows: list[dict], words: list[str]) -> list[dict]:
    """Rows whose title holds every word (any order, case-insensitive), in the order given (newest update first)."""
    return [r for r in rows if all(w in r["title"].lower() for w in words)]


def list_payload(mode: str, query: str, fetched: int, rows: list[dict]) -> dict[str, Any]:
    shown = rows[: (LATEST_SHOWN if mode == "LATEST" else SHOWN_LIMIT)]
    note = NOTE if mode == "LATEST" else f"{NOTE} {FILTER_NOTE.format(n=fetched)}"
    return {"mode": mode, "query": query, "fetched": fetched, "matched": len(rows), "items": shown, "note": note}


def bill_ref(congress: int, typ: str, number: int | str) -> str:
    return f"{congress} {typ} {number}"


def parse_bill(body: Any) -> dict[str, Any]:
    """One bill with its sponsor. A missing `bill` object is an error (an unknown bill is HTTP 404, handled by the provider)."""
    b = body.get("bill") if isinstance(body, dict) else None
    if not isinstance(b, dict) or not b.get("number") or not isinstance(b.get("congress"), int):
        raise UsGovError("unavailable", "CONGRESS BILL: UNEXPECTED ANSWER SHAPE (NO 'bill' OBJECT)")
    sponsors = []
    for s in b.get("sponsors") or []:
        if isinstance(s, dict) and s.get("fullName"):
            where = "-".join(x for x in (text_or_none(s.get("state")), str(s["district"]) if s.get("district") is not None else None) if x)
            tag = "/".join(x for x in (text_or_none(s.get("party")), where) if x)  # "D/CA-12", or just "R/TX" for a senator
            name = clip(s["fullName"], 90)  # the API's own fullName usually already ends in "[D-CA-12]"; add the tag only when it does not
            sponsors.append(name if "[" in name or not tag else f"{name} [{tag}]")
    when, text = _action(b.get("latestAction"))
    area = b.get("policyArea")
    cos = b.get("cosponsors")
    return {
        "mode": "BILL", "congress": b["congress"], "type": str(b.get("type", "")).upper(), "number": str(b["number"]), "title": clip(b.get("title"), 400),
        "chamber": text_or_none(b.get("originChamber")), "introduced": text_or_none(b.get("introducedDate")), "sponsors": sponsors,
        "cosponsors": int(cos["count"]) if isinstance(cos, dict) and num(cos.get("count")) is not None else None,
        "policy_area": text_or_none(area.get("name")) if isinstance(area, dict) else None, "action_date": when, "action": text,
        "updated": text_or_none(b.get("updateDate")), "note": NOTE,
    }
