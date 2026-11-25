"""BIO: the Form 3 / 4 / 5 filings of one reporting owner (an insider) across every company they file for. Pure.

A Form 3/4/5 is filed under TWO names at once: the owner and the issuer. The SEC search lists both in `display_names`, so one query by
the owner's CIK (or name) shows every company that owner reports for. Board seats come from the second search `proxy_params`: the
proxy statements (DEF 14A) whose text contains the person's name, grouped by company. That is a TEXT MATCH: it shows where the name is printed
(a director nominee, an officer, a large holder), and a person who shares the name can appear; it is never presented as proof of a seat.
"""

from __future__ import annotations

import re
from typing import Any

from ..research.table import col, head, payload, section
from .fts import ROW_KEYS_NOTE, first_cik, first_ticker

FORMS = "3,4,5"
PROXY_FORM = "DEF 14A"
ENTITY_WORDS = {"LLC", "LP", "LTD", "INC", "CORP", "TRUST", "FUND", "PARTNERS", "CAPITAL", "HOLDINGS", "GROUP", "CO", "COMPANY", "BANK", "PLC", "FOUNDATION"}
MAX_PROXY_HITS = 100  # one search page
FORM_WHAT = {"3": "Initial holdings", "4": "Change in holdings", "5": "Annual statement"}


def parse_target(text: str) -> tuple[int | None, str]:
    """`BIO 1214156` -> (1214156, ''); `BIO COOK TIMOTHY` -> (None, 'COOK TIMOTHY'). Quotes are dropped."""
    t = " ".join(text.replace('"', " ").split())
    if re.fullmatch(r"\d{1,10}", t):
        return int(t), ""
    return None, t


def _tokens(name: str) -> set[str]:
    return set(re.sub(r"[^A-Z0-9 ]+", " ", name.upper()).split())


def proxy_phrase(owner: str) -> str | None:
    """The way a proxy statement prints a person: 'COOK TIMOTHY D' (the SEC's Last First Middle) -> 'Timothy Cook'. Middle names and initials are
    dropped because proxies print them inconsistently. None for an entity (LLC, trust, fund ...) or a name with fewer than two words."""
    words = re.sub(r"[^A-Za-z' -]+", " ", owner).split()
    if len(words) < 2 or {w.upper() for w in words} & ENTITY_WORDS:
        return None
    return f"{words[1].title()} {words[0].title()}"


def board_rows(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per company whose proxy statements print the name: how many proxies in the window, the newest date and its link."""
    by: dict[int, dict[str, Any]] = {}
    for h in hits:
        cik = first_cik(h["names"])
        if cik is None:
            continue
        r = by.setdefault(cik, {"issuer": next((n["name"] for n in h["names"] if n["cik"] == cik), None), "ticker": first_ticker(h["names"]),
                                "cik": cik, "proxies": set(), "date": h["date"], "url": h["url"] or h["index_url"]})
        r["proxies"].add(h["accession"])
        if h["date"] > r["date"]:
            r["date"], r["url"] = h["date"], h["url"] or h["index_url"]
    rows = [{**r, "proxies": len(r["proxies"])} for r in by.values()]
    rows.sort(key=lambda r: (-r["proxies"], r["issuer"] or ""))
    return rows


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


def build_payload(target: str, rows: list[dict[str, Any]], total: int, source: str, boards: dict[str, Any] | None = None) -> dict:
    """`boards` = {"phrase", "rows", "total"} from the proxy search, or {"phrase": None, "why": ...} when no search was possible."""
    columns = [col("date", "Filed", "date"), col("form", "Form", "text"), col("what", "What", "text"), col("owner", "Reporting owner", "text", 28),
               col("issuer", "Issuer", "text", 40)]
    issuers = {r["issuer"] for r in rows if r["issuer"]}
    shown = f"{len(rows)} OF {total}" if total > len(rows) else str(len(rows))
    sections = [section("filings", "Form 3 / 4 / 5 filings", columns, rows, "NEWEST FIRST")]
    notes = [ROW_KEYS_NOTE, "A NAME SEARCH READS THE FILING TEXT: SEVERAL PEOPLE CAN SHARE A NAME. A CIK IS EXACT"]
    heads = [head("FILINGS", shown), head("ISSUERS IN VIEW", str(len(issuers)))]
    if boards and boards.get("phrase"):
        bcols = [col("issuer", "Company", "text", 36), col("ticker", "Ticker", "text", 8), col("proxies", "Proxies", "int"), col("date", "Newest", "date")]
        sections.append(section("boards", f"Proxy statements (DEF 14A) naming \"{boards['phrase']}\"", bcols, boards["rows"], "MOST PROXIES FIRST"))
        heads.append(head("COMPANIES NAMING HIM/HER", str(len(boards["rows"]))))
        notes.append(f"BOARDS: TEXT MATCH FOR \"{boards['phrase'].upper()}\" IN DEF 14A PROXY STATEMENTS. IT SHOWS WHERE THE NAME IS PRINTED "
                     "(DIRECTOR NOMINEE, OFFICER OR LARGE HOLDER), NOT A CONFIRMED SEAT; A PERSON WITH THE SAME NAME CAN APPEAR")
        if boards["total"] > MAX_PROXY_HITS:
            notes.append(f"FIRST {MAX_PROXY_HITS} OF {boards['total']} PROXY HITS GROUPED")
    elif boards:
        notes.append(f"BOARDS NOT SEARCHED: {boards['why']}")
    return payload(None, f"BIO {target}", heads, sections, notes=notes, source=source)
