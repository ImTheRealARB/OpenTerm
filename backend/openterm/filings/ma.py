"""MA: a deal tracker built from filings, not from a deal database. Pure.

Two inputs, one table:
  * with a symbol: the company's own SEC filing list (`parse_submissions`), keeping the forms that announce or carry a deal;
  * with no symbol: the market-wide SEC full-text search restricted to the same form families.

Forms kept (an amendment "/A" of any of them counts): 8-K with item 1.01 (material agreement) or 2.01 (acquisition or disposal
completed), SC TO-T (third-party tender offer), DEFM14A / PREM14A (merger proxy), S-4 (merger registration), 425 (deal communication).
The "stated value" column is filled by `service.ma` from the filing text (`ma_value.extract`): only a figure the filing states in words
(a cover-page transaction valuation, or a sentence with a value word and a dollar amount). Rows not read say so.
"""

from __future__ import annotations

from typing import Any

from ..providers.sec_parse import ITEMS_8K
from ..research.table import col, head, payload, section
from .fts import ROW_KEYS_NOTE, first_cik, first_ticker

DEAL_FORMS = ("SC TO-T", "DEFM14A", "PREM14A", "S-4", "425")
# The forms string sent to the market-wide search (the endpoint also returns each form's amendments).
MARKET_FORMS = "SC TO-T,DEFM14A,S-4,425"
DEAL_ITEMS = {"1.01", "2.01"}
FORM_WHAT = {
    "SC TO-T": "Third-party tender offer",
    "DEFM14A": "Definitive merger proxy",
    "PREM14A": "Preliminary merger proxy",
    "S-4": "Registration for a merger or exchange offer",
    "425": "Communication about a business combination",
}
VALUE_NOTE = "VALUE: A DOLLAR FIGURE THE FILING TEXT STATES NEXT TO A VALUE WORD (DEAL, ENTERPRISE, EQUITY, TRANSACTION). NOT STATED = READ, NONE FOUND. NOT READ = FETCH FAILED. BLANK = BEYOND THE FIRST ROWS READ"
PARTIES_NOTE = "PARTIES: THE FILING COMPANY, PLUS THE OTHER FILERS NAMED ON A MARKET-WIDE HIT (A FILING LIST HAS NO COUNTERPARTY)"


def base_form(form: str) -> str:
    return form.upper().removesuffix("/A")


def is_deal(form: str, items: str | None) -> bool:
    """True for a form that announces or carries a deal. `items` is the 8-K item list as the SEC prints it: '1.01,9.01'."""
    base = base_form(form)
    if base == "8-K":
        return bool(DEAL_ITEMS & {i.strip() for i in (items or "").split(",")})
    return base in DEAL_FORMS


def what(form: str, items: str | None) -> str:
    base = base_form(form)
    if base == "8-K":
        names = [f"{i} {ITEMS_8K.get(i, '')}".strip() for i in (items or "").split(",") if i.strip() in DEAL_ITEMS]
        text = "8-K: " + "; ".join(names)
    else:
        text = FORM_WHAT.get(base, form)
    return f"{text} (amendment)" if form.upper().endswith("/A") else text


def rows_from_filings(filings: list[dict[str, Any]], company: str, ticker: str | None) -> list[dict[str, Any]]:
    """Deal rows from `parse_submissions(...)["filings"]` (newest first, as the SEC lists them)."""
    rows = []
    for f in filings:
        if not is_deal(f["form"], f.get("items")):
            continue
        rows.append({"date": f["filed"], "form": f["form"], "what": what(f["form"], f.get("items")), "parties": company, "ticker": ticker,
                     "accession": f["accession"], "url": f["url"], "doc_url": f.get("doc_url")})
    return rows


def rows_from_fts(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deal rows from `fts.parse_fts(...)["hits"]`. The market-wide query only asks for deal forms, so no filtering is needed."""
    return [{
        "date": h["date"], "form": h["form"], "what": what(h["form"] or "", ",".join(h["items"])),
        "parties": " / ".join(n["name"] for n in h["names"]) or None, "ticker": first_ticker(h["names"]), "cik": first_cik(h["names"]),
        "accession": h["accession"], "url": h["index_url"] or h["url"], "doc_url": h["url"],
    } for h in hits]


def build_payload(symbol: str | None, title: str, rows: list[dict[str, Any]], source: str, scope: str, extra_notes: list[str] | None = None) -> dict:
    columns = [col("date", "Filed", "date"), col("form", "Form", "text"), col("what", "What", "text", 44), col("parties", "Parties", "text", 40),
               col("value", "Stated value", "text", 16), col("quote", "Where the filing says it", "text", 60)]
    rows = [{"value": None, "quote": None, **r} for r in rows]
    return payload(
        symbol, title,
        [head("DEAL FILINGS", str(len(rows))), head("SCOPE", scope)],
        [section("deals", "Deal filings", columns, rows, VALUE_NOTE)],
        notes=[ROW_KEYS_NOTE, PARTIES_NOTE, "A DEAL FORM IS A FILING, NOT A CLOSED DEAL: AN S-4 OR 425 CAN BE FOR A DEAL THAT NEVER CLOSES", *(extra_notes or [])],
        source=source,
    )
