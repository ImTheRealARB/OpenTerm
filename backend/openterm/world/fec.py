"""FEC: US campaign finance from OpenFEC (key FEC_API_KEY from api.data.gov, free). Pure request builders and parsers.

DOC-SHAPED, NOT RUN AGAINST A LIVE KEY: no key was available when this was written, so the shapes below come from the OpenFEC documentation
(https://api.open.fec.gov/developers/) and the fixtures `fec_*_docshape.json` hold INVENTED numbers in that shape (each file says "NOT A RECORDING").
The only live-checked parts are the gateway's answers to no key and a made-up key (`keytest_datagov_fec_*.json`: HTTP 403 API_KEY_MISSING / API_KEY_INVALID).

  GET /v1/candidates/search/?q=<name>&per_page=N&sort=-election_years
    -> {"pagination": {"count", "page", "pages", "per_page"}, "results": [{"candidate_id": "H0XX00000", "name": "SMITH, JANE", "party": "DEM",
        "party_full": "...", "office": "H|S|P", "office_full": "House", "state": "CA", "district": "12", "election_years": [2024, 2026],
        "candidate_status": "C", "incumbent_challenge": "I", "has_raised_funds": true, ...}]}
  GET /v1/committees/?q=<name>&per_page=N
    -> results [{"committee_id": "C00000000", "name": "...", "committee_type_full": "...", "designation_full": "...", "party_full": "...", "state": "..",
        "cycles": [2024, 2026], "treasurer_name": "...", ...}]
  GET /v1/candidate/<id>/totals/?sort=-cycle&per_page=N     and     GET /v1/committee/<id>/totals/?sort=-cycle&per_page=N
    -> results [{"cycle": 2024, "receipts": 1.0, "disbursements": 1.0, "cash_on_hand_end_period": 1.0, "debts_owed_by_committee": 1.0,
        "individual_itemized_contributions" / "individual_unitemized_contributions" (candidate) or "individual_contributions" (committee),
        "coverage_end_date": "2024-12-31T00:00:00", ...}]
  GET /v1/candidate/<id>/ and /v1/committee/<id>/  -> {"results": [{"name": ..., ...}]}   (the name above the totals)

Every figure is US dollars as reported to the FEC (self-reported by campaigns and committees on filings, itemised above a threshold only).
"""

from __future__ import annotations

import re
from typing import Any

from .usgov import UsGovError, clip, need_list, num, text_or_none

SOURCE = "OPENFEC (API.OPEN.FEC.GOV)"
SEARCH_LIMIT = 10  # per kind (candidates and committees), so a search shows at most 20 rows
CYCLES_SHOWN = 6
MIN_QUERY = 2
MAX_QUERY = 80
CANDIDATE_ID = re.compile(r"^[HSP]\d[A-Z]{2}\d{5}$", re.IGNORECASE)  # H8CA12345: office letter, last digit of the election year, state, serial
COMMITTEE_ID = re.compile(r"^C\d{8}$", re.IGNORECASE)

NOTE = ("FIGURES ARE US DOLLARS AS REPORTED TO THE FEC ON FILINGS: SELF-REPORTED BY CAMPAIGNS AND COMMITTEES, COVERING THE DATES SHOWN, "
        "AND A CYCLE IS A 2-YEAR ELECTION PERIOD. RECEIPTS ARE MONEY RAISED, DISBURSEMENTS MONEY SPENT; THEY ARE NOT VOTES, POLLS OR ENDORSEMENTS.")


def norm_query(q: str) -> tuple[str, str]:
    """('candidate', id) | ('committee', id) | ('search', words). Candidate and committee ids are recognised by their fixed formats."""
    text = " ".join((q or "").split())
    if CANDIDATE_ID.match(text):
        return "candidate", text.upper()
    if COMMITTEE_ID.match(text):
        return "committee", text.upper()
    if len(text) < MIN_QUERY or len(text) > MAX_QUERY:
        raise UsGovError("bad_request", f"GIVE A CANDIDATE OR COMMITTEE NAME OF {MIN_QUERY} TO {MAX_QUERY} CHARACTERS, OR AN FEC ID (H8CA12345 OR C00123456)")
    return "search", text


def parse_candidates(body: Any) -> list[dict[str, Any]]:
    rows = []
    for r in need_list(body, "results", "OPENFEC CANDIDATES"):
        if not isinstance(r, dict) or not r.get("candidate_id") or not r.get("name"):
            raise UsGovError("unavailable", "OPENFEC CANDIDATES: A ROW HAS NO ID OR NAME")
        years = [y for y in (r.get("election_years") or []) if isinstance(y, int)]
        rows.append({
            "kind": "CANDIDATE", "id": str(r["candidate_id"]).upper(), "name": clip(r["name"], 60), "party": text_or_none(r.get("party")),
            "office": text_or_none(r.get("office_full")) or text_or_none(r.get("office")), "state": text_or_none(r.get("state")),
            "district": text_or_none(r.get("district")), "last_year": max(years) if years else None,
        })
    return rows


def parse_committees(body: Any) -> list[dict[str, Any]]:
    rows = []
    for r in need_list(body, "results", "OPENFEC COMMITTEES"):
        if not isinstance(r, dict) or not r.get("committee_id") or not r.get("name"):
            raise UsGovError("unavailable", "OPENFEC COMMITTEES: A ROW HAS NO ID OR NAME")
        cycles = [y for y in (r.get("cycles") or []) if isinstance(y, int)]
        rows.append({
            "kind": "COMMITTEE", "id": str(r["committee_id"]).upper(), "name": clip(r["name"], 60), "party": text_or_none(r.get("party_full")),
            "office": text_or_none(r.get("committee_type_full")), "state": text_or_none(r.get("state")), "district": None,
            "last_year": max(cycles) if cycles else None,
        })
    return rows


def search_payload(query: str, candidates: list[dict], committees: list[dict], notes: list[str]) -> dict[str, Any]:
    return {"mode": "SEARCH", "query": query, "items": [*candidates, *committees], "notes": notes, "note": NOTE}


def parse_name(body: Any) -> str | None:
    """The name from the entity record (`/candidate/<id>/` or `/committee/<id>/`), or None when the id matched nothing."""
    rows = need_list(body, "results", "OPENFEC ENTITY")
    if not rows or not isinstance(rows[0], dict):
        return None
    return clip(rows[0].get("name"), 80) or None


def parse_totals(body: Any) -> list[dict[str, Any]]:
    """Cycle totals, newest cycle first (the request asks `sort=-cycle`; we sort again so the order never depends on the API)."""
    rows = []
    for r in need_list(body, "results", "OPENFEC TOTALS"):
        if not isinstance(r, dict) or not isinstance(r.get("cycle"), int):
            raise UsGovError("unavailable", "OPENFEC TOTALS: A ROW HAS NO CYCLE")
        # Candidates split individual money into itemised and unitemised; committees report one figure. Add the two only when both are present.
        itemised, unitemised = num(r.get("individual_itemized_contributions")), num(r.get("individual_unitemized_contributions"))
        individual = num(r.get("individual_contributions"))
        if individual is None and itemised is not None and unitemised is not None:
            individual = itemised + unitemised
        rows.append({
            "cycle": r["cycle"], "receipts": num(r.get("receipts")), "disbursements": num(r.get("disbursements")),
            "cash": num(r.get("cash_on_hand_end_period")), "debts": num(r.get("debts_owed_by_committee")), "individual": individual,
            "covered_to": (text_or_none(r.get("coverage_end_date")) or "")[:10] or None,
        })
    rows.sort(key=lambda x: -x["cycle"])
    return rows[:CYCLES_SHOWN]


def entity_payload(kind: str, ident: str, name: str | None, totals: list[dict]) -> dict[str, Any]:
    return {"mode": kind, "id": ident, "name": name, "cycles": totals, "latest": totals[0] if totals else None, "note": NOTE}
