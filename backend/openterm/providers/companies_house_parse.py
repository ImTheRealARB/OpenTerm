"""Pure parsers for the UK Companies House Public Data API (`api.company-information.service.gov.uk`). No network, no pandas.

Field names are copied from the official resource pages (developer-specs.company-information.service.gov.uk, read 2026-11-05):
  search     /search/companies?q=            {items: [{title, company_number, company_status, company_type, date_of_creation,
                                              date_of_cessation, address_snippet, address{...}, description, kind, links}],
                                              items_per_page, start_index, total_results}
  profile    /company/{number}               {company_name, company_number, company_status, company_status_detail, type, subtype,
                                              date_of_creation, date_of_cessation, jurisdiction, sic_codes[], registered_office_address{...},
                                              accounts{next_due, overdue, last_accounts{made_up_to, type}, next_accounts{due_on, overdue}},
                                              confirmation_statement{next_due, overdue, last_made_up_to}, has_charges,
                                              has_insolvency_history, can_file, ...}
  officers   /company/{number}/officers      {items: [{name, officer_role, appointed_on, resigned_on, nationality, occupation,
                                              country_of_residence, address{...}, date_of_birth{month, year}, ...}],
                                              active_count, resigned_count, total_results, items_per_page, start_index}
  filings    /company/{number}/filing-history {items: [{date, category, type, description, pages, paper_filed, transaction_id, links}],
                                              items_per_page, start_index, total_count}
They are NOT recordings (no key was available). Values the docs do not describe (such as the variable text behind a filing's
`description` code) are not guessed at: the code is shown as written. Officers' dates of birth and home addresses are not read at all.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ProviderError

# A company number is 8 characters: digits (00000006) or a 2-letter prefix and 6 digits (SC123456, NI012345, OC301234 ...).
_NUMBER = re.compile(r"^(?:\d{1,8}|[A-Za-z]{2}\d{1,6})$")


def as_number(text: str) -> str | None:
    """The 8-character company number the text stands for ('6' -> '00000006', 'sc123456' -> 'SC123456'), or None when it is a name."""
    s = (text or "").strip().replace(" ", "")
    if not _NUMBER.match(s):
        return None
    return s.zfill(8) if s.isdigit() else s[:2].upper() + s[2:].zfill(6)


def _dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _items(body: Any, what: str) -> list[dict]:
    if not isinstance(body, dict) or not isinstance(body.get("items", []), list):
        raise ProviderError("unavailable", f"unexpected Companies House {what} shape")
    return [i for i in body.get("items", []) if isinstance(i, dict)]


def one_line(addr: Any) -> str:
    a = _dict(addr)
    parts = [a.get(k) for k in ("care_of", "po_box", "premises", "address_line_1", "address_line_2", "locality", "region", "postal_code", "country")]
    return ", ".join(str(p) for p in parts if p)


def words(code: Any) -> str:
    """'accounts-with-accounts-type-full' -> 'ACCOUNTS WITH ACCOUNTS TYPE FULL' (the register's own code, only made readable)."""
    return str(code or "").replace("-", " ").replace("_", " ").upper()


def search(body: Any) -> dict:
    rows = [{"number": r.get("company_number"), "name": r.get("title"), "status": r.get("company_status"), "type": r.get("company_type"),
             "created": r.get("date_of_creation"), "ceased": r.get("date_of_cessation"),
             "address": r.get("address_snippet") or one_line(r.get("address"))}
            for r in _items(body, "search") if r.get("company_number")]
    return {"total": _dict(body).get("total_results"), "items": rows}


def profile(body: Any) -> dict:
    b = _dict(body)
    if not b.get("company_number"):
        raise ProviderError("unavailable", "unexpected Companies House profile shape")
    acc, conf = _dict(b.get("accounts")), _dict(b.get("confirmation_statement"))
    last = _dict(acc.get("last_accounts"))
    nxt = _dict(acc.get("next_accounts"))
    return {
        "number": b["company_number"], "name": b.get("company_name"), "status": b.get("company_status"),
        "status_detail": b.get("company_status_detail"), "type": b.get("type"), "subtype": b.get("subtype"),
        "created": b.get("date_of_creation"), "ceased": b.get("date_of_cessation"), "jurisdiction": b.get("jurisdiction"),
        "sic": [str(s) for s in b.get("sic_codes") or []], "address": one_line(b.get("registered_office_address")),
        "accounts": {"last_made_up_to": last.get("made_up_to"), "next_due": acc.get("next_due") or nxt.get("due_on"),
                     "overdue": acc.get("overdue") if acc.get("overdue") is not None else nxt.get("overdue")},
        "confirmation": {"last_made_up_to": conf.get("last_made_up_to"), "next_due": conf.get("next_due"), "overdue": conf.get("overdue")},
        "has_charges": b.get("has_charges"), "has_insolvency_history": b.get("has_insolvency_history"),
    }


def officers(body: Any) -> dict:
    rows = [{"name": r.get("name"), "role": words(r.get("officer_role")), "appointed": r.get("appointed_on"),
             "resigned": r.get("resigned_on"), "nationality": r.get("nationality"), "occupation": r.get("occupation"),
             "country": r.get("country_of_residence")}
            for r in _items(body, "officers")]
    # Active officers first (no resignation date), each group newest appointment first.
    rows.sort(key=lambda r: (r["resigned"] is not None, _neg(r["appointed"])))
    b = _dict(body)
    return {"total": b.get("total_results"), "active": b.get("active_count"), "resigned": b.get("resigned_count"), "items": rows}


def _neg(date_text: Any) -> str:
    """Sort key that puts the latest ISO date first: invert each digit so a plain ascending sort reads newest first."""
    return "".join(str(9 - int(c)) if c.isdigit() else c for c in str(date_text or "0000-00-00"))


def filings(body: Any) -> dict:
    rows = [{"date": r.get("date"), "category": words(r.get("category")), "type": r.get("type"), "description": words(r.get("description")),
             "pages": r.get("pages"), "paper": bool(r.get("paper_filed"))}
            for r in _items(body, "filing history")]
    return {"total": _dict(body).get("total_count"), "items": rows}
