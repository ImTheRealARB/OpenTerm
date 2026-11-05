"""USASP: US federal spending from USASpending.gov (keyless). Pure request builders and parsers; `providers/usgov.py` does the HTTP.

Shapes checked live on 2026-11-05 (real recordings: `tests/fixtures/usasp_real_*.json`, made by `scripts/record_usgov.py`):

  POST /api/v2/search/spending_by_category/recipient/   body {"filters": {...}, "limit": 10, "page": 1}
       -> {"category": "recipient", "results": [{"amount": 3.4e10, "recipient_id": "...-C", "name": "LOCKHEED MARTIN CORPORATION",
                                                 "code": "008016958", "uei": "G4KDGE4JFFK7", "total_outlays": null}], "page_metadata": {...}, "messages": [...]}
  POST /api/v2/search/spending_by_category/awarding_agency/  -> results [{"id": 806, "code": "HHS", "name": "Department of ...", "amount": 2.0e12, ...}]
  POST /api/v2/search/spending_by_award/   body adds "fields": [...], "sort": "Award Amount", "order": "desc"
       -> {"results": [{"internal_id", "Award ID", "Recipient Name", "Award Amount", "Awarding Agency", "Start Date", "End Date", "Description",
                        "generated_internal_id", ...}], "page_metadata": {...}}   (a search with no match: HTTP 200 and "results": [])
  filters: {"keywords": [...], "time_period": [{"start_date", "end_date"}], "award_type_codes": ["A","B","C","D"]}; dates cannot be before 2007-10-01.

Amounts are US dollars OBLIGATED (money the government has committed by contract or grant), not money paid out (outlays) and not revenue of the
recipient. In the recipient and agency views the amount is what was obligated INSIDE the date window; in the awards view "Award Amount" is the
award's total obligation over its WHOLE life (a contract from 1993 can show here), which is why the two numbers do not add up.
The agency drill-down (Enter on an agency) adds the filter "agencies": [{"type": "awarding", "tier": "toptier", "name": <agency name>}] (checked live, recorded).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .usgov import UsGovError, clip, need_list, num, text_or_none

SOURCE = "USASPENDING.GOV"
CONTRACT_TYPES = ["A", "B", "C", "D"]  # BPA call, purchase order, delivery order, definitive contract: the four "contract" award types
FISCAL_YEARS = 3  # the window is this many US fiscal years (1 Oct to 30 Sep), the current one counted to date
RECIPIENT_LIMIT = 10
AWARD_LIMIT = 15
AGENCY_LIMIT = 15
MIN_QUERY = 2
MAX_QUERY = 80
AWARD_FIELDS = ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency", "Start Date", "End Date", "Description", "generated_internal_id"]

NOTE = ("AMOUNTS ARE US DOLLARS OBLIGATED (COMMITTED BY CONTRACT OR GRANT), NOT PAYMENTS AND NOT THE RECIPIENT'S REVENUE. "
        "RECIPIENT TOTALS COUNT ONLY THE WINDOW SHOWN; AN AWARD'S AMOUNT IS ITS OBLIGATION OVER ITS WHOLE LIFE, SO THE TWO DO NOT ADD UP. "
        "THE KEYWORD MATCHES AWARD TEXT AND RECIPIENT NAMES, SO UNRELATED AWARDS CAN APPEAR. DATA IS SELF-REPORTED BY AGENCIES.")
AGENCY_NOTE = ("AMOUNTS ARE US DOLLARS OBLIGATED INSIDE THE WINDOW, ALL AWARD TYPES (CONTRACTS, GRANTS, LOANS, DIRECT PAYMENTS SUCH AS BENEFITS), "
               "NOT PAYMENTS. ENTER OPENS THE AGENCY'S TOP CONTRACT RECIPIENTS.")


def fiscal_window(today: date, years: int = FISCAL_YEARS) -> dict[str, str]:
    """The last `years` US fiscal years up to `today`. A fiscal year FYn runs 1 Oct (n-1) to 30 Sep n, so October onwards belongs to the next year."""
    fy = today.year + 1 if today.month >= 10 else today.year
    start = date(fy - years, 10, 1)
    return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": f"FY{fy - years + 1} TO {today.isoformat()}"}


def norm_query(q: str) -> tuple[str, str]:
    """('agency', '') for an empty text or the word AGENCY, else ('keyword', words). Text too short or too long is a bad_request."""
    text = " ".join((q or "").split())
    if not text or text.upper() == "AGENCY":
        return "agency", ""
    if len(text) < MIN_QUERY or len(text) > MAX_QUERY:
        raise UsGovError("bad_request", f"GIVE A COMPANY OR KEYWORD OF {MIN_QUERY} TO {MAX_QUERY} CHARACTERS, OR AGENCY FOR THE TOP AGENCIES")
    return "keyword", text


def _filters(window: dict[str, str], keywords: str | None, types: list[str] | None) -> dict[str, Any]:
    f: dict[str, Any] = {"time_period": [{"start_date": window["start_date"], "end_date": window["end_date"]}]}
    if keywords:
        f["keywords"] = [keywords]
    if types:
        f["award_type_codes"] = types
    return f


def recipient_body(window: dict[str, str], keywords: str) -> dict[str, Any]:
    return {"filters": _filters(window, keywords, CONTRACT_TYPES), "limit": RECIPIENT_LIMIT, "page": 1}


def awards_body(window: dict[str, str], keywords: str) -> dict[str, Any]:
    return {"filters": _filters(window, keywords, CONTRACT_TYPES), "fields": AWARD_FIELDS, "sort": "Award Amount", "order": "desc",
            "limit": AWARD_LIMIT, "page": 1}


def agency_body(window: dict[str, str]) -> dict[str, Any]:
    return {"filters": _filters(window, None, None), "limit": AGENCY_LIMIT, "page": 1}


def recipient_in_agency_body(window: dict[str, str], agency_name: str) -> dict[str, Any]:
    """Top contract recipients of one awarding agency (the agency view's Enter). The `agencies` filter takes the agency's exact top-tier name."""
    f = _filters(window, None, CONTRACT_TYPES)
    f["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency_name}]
    return {"filters": f, "limit": RECIPIENT_LIMIT, "page": 1}


def parse_recipients(body: Any) -> list[dict[str, Any]]:
    rows = []
    for r in need_list(body, "results", "USASPENDING RECIPIENTS"):
        if not isinstance(r, dict) or not r.get("name"):
            raise UsGovError("unavailable", "USASPENDING RECIPIENTS: A ROW HAS NO NAME")
        rows.append({"name": clip(r["name"], 80), "uei": text_or_none(r.get("uei")), "amount": num(r.get("amount"))})
    return rows


def parse_agencies(body: Any) -> list[dict[str, Any]]:
    rows = []
    for r in need_list(body, "results", "USASPENDING AGENCIES"):
        if not isinstance(r, dict) or not r.get("name"):
            raise UsGovError("unavailable", "USASPENDING AGENCIES: A ROW HAS NO NAME")
        rows.append({"name": clip(r["name"], 80), "code": text_or_none(r.get("code")), "amount": num(r.get("amount"))})
    return rows


def parse_awards(body: Any) -> list[dict[str, Any]]:
    """Awards in the order asked for (largest first). Descriptions of old awards are fixed-width legacy records: clipped to one line."""
    rows = []
    for r in need_list(body, "results", "USASPENDING AWARDS"):
        if not isinstance(r, dict) or not r.get("Award ID"):
            raise UsGovError("unavailable", "USASPENDING AWARDS: A ROW HAS NO AWARD ID")
        rows.append({
            "award_id": str(r["Award ID"]), "recipient": clip(r.get("Recipient Name"), 60), "amount": num(r.get("Award Amount")),
            "agency": clip(r.get("Awarding Agency"), 60), "start": text_or_none(r.get("Start Date")), "end": text_or_none(r.get("End Date")),
            "description": clip(r.get("Description"), 120),
        })
    return rows


def keyword_payload(query: str, window: dict[str, str], recipients: list[dict], awards: list[dict] | None, notes: list[str]) -> dict[str, Any]:
    """`awards` is None when that second call failed (the notes say why), [] when it worked and found nothing."""
    return {"mode": "KEYWORD", "query": query, "window": window["label"], "award_kind": "CONTRACTS", "recipients": recipients,
            "recipients_total": sum(r["amount"] or 0.0 for r in recipients) if recipients else None, "awards": awards, "notes": notes, "note": NOTE}


def agency_payload(window: dict[str, str], agencies: list[dict]) -> dict[str, Any]:
    return {"mode": "AGENCY", "window": window["label"], "award_kind": "ALL AWARD TYPES", "agencies": agencies, "note": AGENCY_NOTE}


def agency_detail_payload(agency: str, window: dict[str, str], recipients: list[dict]) -> dict[str, Any]:
    return {"mode": "AGENCY_RECIPIENTS", "agency": agency, "window": window["label"], "award_kind": "CONTRACTS", "recipients": recipients,
            "recipients_total": sum(r["amount"] or 0.0 for r in recipients) if recipients else None, "note": AGENCY_NOTE}
