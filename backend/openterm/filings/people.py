"""BIO: the Form 3 / 4 / 5 filings of one reporting owner (an insider) across every company they file for. Pure.

A Form 3/4/5 is filed under TWO names at once: the owner and the issuer. The SEC search lists both in `display_names`, so one query by
the owner's CIK (or name) shows every company that owner reports for. Boards and officer titles are NOT built: they need the proxy
statement (DEF 14A) text, which this table does not read.
"""

from __future__ import annotations

import re
from typing import Any

from ..research.table import col, head, payload, section
from .fts import ROW_KEYS_NOTE, first_cik, first_ticker

FORMS = "3,4,5"
BOARDS_NOTE = "BOARDS FROM DEF 14A: NOT BUILT"
FORM_WHAT = {"3": "Initial holdings", "4": "Change in holdings", "5": "Annual statement"}


def parse_target(text: str) -> tuple[int | None, str]:
    """`BIO 1214156` -> (1214156, ''); `BIO COOK TIMOTHY` -> (None, 'COOK TIMOTHY'). Quotes are dropped."""
    t = " ".join(text.replace('"', " ").split())
    if re.fullmatch(r"\d{1,10}", t):
        return int(t), ""
    return None, t


def _tokens(name: str) -> set[str]:
    return set(re.sub(r"[^A-Z0-9 ]+", " ", name.upper()).split())


def split_roles(names: list[dict[str, Any]], owner_cik: int | None, owner_name: str) -> tuple[list[str], list[str]]:
    """(owner names, issuer names). An owner is the filer whose CIK is the one asked for, or whose name holds every word asked for. When
    neither identifies anyone the owner list is empty and every name goes to the issuer list: the table then says so instead of guessing."""
    want = _tokens(owner_name)
    owners, issuers = [], []
    for n in names:
        is_owner = (owner_cik is not None and n["cik"] == owner_cik) or (owner_cik is None and bool(want) and want <= _tokens(n["name"]))
        (owners if is_owner else issuers).append(n["name"])
    if not owners:
        issuers = [n["name"] for n in names]
    return owners, issuers


def rows_from_fts(hits: list[dict[str, Any]], owner_cik: int | None, owner_name: str) -> list[dict[str, Any]]:
    rows = []
    for h in hits:
        owners, issuers = split_roles(h["names"], owner_cik, owner_name)
        issuer_names = [n for n in h["names"] if n["name"] in issuers]
        rows.append({
            "date": h["date"], "form": h["form"], "what": FORM_WHAT.get(str(h["form"]).split("/")[0], None),
            "owner": " / ".join(owners) if owners else "(NOT IDENTIFIED)", "issuer": " / ".join(issuers) or None,
            "ticker": first_ticker(issuer_names), "cik": first_cik(issuer_names), "accession": h["accession"], "url": h["url"] or h["index_url"],
        })
    return rows


def build_payload(target: str, rows: list[dict[str, Any]], total: int, source: str) -> dict:
    columns = [col("date", "Filed", "date"), col("form", "Form", "text"), col("what", "What", "text"), col("owner", "Reporting owner", "text", 28),
               col("issuer", "Issuer", "text", 40)]
    issuers = {r["issuer"] for r in rows if r["issuer"]}
    shown = f"{len(rows)} OF {total}" if total > len(rows) else str(len(rows))
    return payload(
        None, f"BIO {target}", [head("FILINGS", shown), head("ISSUERS IN VIEW", str(len(issuers)))],
        [section("filings", "Form 3 / 4 / 5 filings", columns, rows, "NEWEST FIRST")],
        notes=[ROW_KEYS_NOTE, BOARDS_NOTE, "A NAME SEARCH READS THE FILING TEXT: SEVERAL PEOPLE CAN SHARE A NAME. A CIK IS EXACT"],
        source=source,
    )
