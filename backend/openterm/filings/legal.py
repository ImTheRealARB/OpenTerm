"""LEGAL: SEC enforcement feeds and CourtListener dockets matched to a company NAME. Pure.

Matching is by name only, so every row says NAME MATCH: "Apple" also matches "Apple Hospitality". Nothing is merged silently: the SEC
rows and the court rows are separate sections, and each row keeps the title the source printed.

SEC feeds (public RSS, www.sec.gov): litigation releases and administrative proceedings. SEC's current feeds hold only the latest
25 items each (the older /rss/litigation/*.xml files stopped in 2023), so a quiet company simply has no row: it does not mean "no case".
CourtListener (free key COURTLISTENER_API_KEY): RECAP federal dockets whose case name matches.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

from ..research.table import col, head, payload, section

NAME_MATCH = "NAME MATCH"
FEED_LIMIT_NOTE = "SEC FEEDS HOLD ONLY THEIR LATEST 25 ITEMS EACH: NO ROW IS NOT PROOF OF NO CASE"
COURT_URL = "https://www.courtlistener.com"
# Words that are not part of a company's identity. Dropped before comparing, so "Alcoa Corp" and "ALCOA INC" both reduce to ALCOA.
STOP = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "LLC", "LP", "PLC", "HOLDINGS", "HOLDING",
        "GROUP", "THE", "NEW", "DE", "SA", "NV", "AG", "CLASS", "COM"}
MIN_NAME_CHARS = 3
_BARE_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")


def core_name(name: str) -> str:
    """'LENNAR CORP /NEW/' -> 'LENNAR'; 'Meta Platforms, Inc.' -> 'META PLATFORMS'. Upper case, letters and digits only."""
    words = re.sub(r"[^A-Z0-9 ]+", " ", name.upper()).split()
    keep = [w for w in words if w not in STOP]
    return " ".join(keep)


def name_matches(company: str, title: str) -> bool:
    """True when the company's core name appears in the title as whole words. Too short a name matches nothing (it would match everything)."""
    core = core_name(company)
    if len(core) < MIN_NAME_CHARS:
        return False
    haystack = " " + " ".join(re.sub(r"[^A-Z0-9 ]+", " ", title.upper()).split()) + " "
    return f" {core} " in haystack


def _iso(pub: str | None) -> str | None:
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub.strip()).astimezone(UTC).date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_rss(xml: bytes | str, kind: str) -> list[dict[str, Any]]:
    """Items of one SEC RSS feed: {kind, title, date, ref, url}. `ref` is the release or order number (the feed's dc:creator). Raises
    ValueError when the text is not RSS (for example an HTML error page)."""
    text = xml.decode("utf-8", "replace") if isinstance(xml, bytes) else xml
    # The SEC's administrative-proceedings feed prints names like "Coburn & Meredith, Inc." with a bare "&", which is not well-formed XML
    # (checked 2026-11-24, see the recording). Escape every "&" that does not start an entity, then parse; nothing else is repaired.
    text = _BARE_AMP.sub("&amp;", text)
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError("SEC FEED IS NOT XML") from e
    channel = root.find("channel")
    if channel is None:
        raise ValueError("SEC FEED HAS NO CHANNEL")
    out = []
    for item in channel.findall("item"):
        def text(tag: str, item: ET.Element = item) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        out.append({"kind": kind, "title": text("title"), "date": _iso(text("pubDate")), "ref": text("{http://purl.org/dc/elements/1.1/}creator") or None,
                    "url": text("link") or None})
    return out


def sec_rows(company: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"date": i["date"], "kind": i["kind"], "ref": i["ref"], "title": i["title"], "match": NAME_MATCH, "url": i["url"]}
            for i in items if name_matches(company, i["title"])]


def parse_dockets(body: Any) -> list[dict[str, Any]]:
    """CourtListener v4 search (type=r, RECAP dockets): {"results": [{caseName, court, dateFiled, docketNumber, docket_absolute_url}]}.
    DOC-SHAPED: written from the API docs, never run against a live key. Raises ValueError for another shape."""
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise ValueError("COURTLISTENER ANSWERED WITH AN UNKNOWN SHAPE")  # noqa: TRY004 (callers catch ValueError for every bad shape)
    out = []
    for r in results:
        path = r.get("docket_absolute_url") or r.get("absolute_url")
        out.append({"date": r.get("dateFiled"), "court": r.get("court") or r.get("court_id"), "case": r.get("caseName"),
                    "docket": r.get("docketNumber"), "url": f"{COURT_URL}{path}" if path else None})
    return out


def court_rows(company: str, dockets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dockets whose case name carries the company's core name (CourtListener's own search is looser than that)."""
    return [{"date": d["date"], "court": d["court"], "case": d["case"], "docket": d["docket"], "match": NAME_MATCH, "url": d["url"]}
            for d in dockets if d["case"] and name_matches(company, d["case"])]


def build_payload(symbol: str, company: str, sec: list[dict[str, Any]], court: list[dict[str, Any]] | None, source: str,
                  court_note: str | None, key_required: list[dict] | None) -> dict:
    """`court` is None when the CourtListener part could not run (no key): the section then carries `court_note` and no rows."""
    sec_cols = [col("date", "Date", "date"), col("kind", "Feed", "text"), col("ref", "Ref", "text"), col("title", "Respondent", "text", 60),
                col("match", "Match", "text")]
    court_cols = [col("date", "Filed", "date"), col("court", "Court", "text", 28), col("case", "Case", "text", 50), col("docket", "Docket", "text"),
                  col("match", "Match", "text")]
    sections = [section("sec", "SEC enforcement", sec_cols, sec, FEED_LIMIT_NOTE),
                section("court", "Court dockets", court_cols, court or [], court_note)]
    headline = [head("COMPANY", company), head("MATCHED ON", core_name(company) or "-"), head("SEC ROWS", str(len(sec))),
                head("COURT ROWS", str(len(court)) if court is not None else "-")]
    return payload(symbol, f"LEGAL {symbol}", headline, sections,
                   notes=[f"{NAME_MATCH}: ROWS ARE MATCHED ON THE COMPANY NAME ONLY, NOT ON AN IDENTIFIER. CHECK EACH ONE."],
                   source=source, key_required=key_required)
