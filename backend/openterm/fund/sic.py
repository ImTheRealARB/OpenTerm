"""SIC codes (Phase 29 finish): the industry code the SEC gives each filer. Pure parsers, no I/O.

Two SEC pages feed it (both public, declared User-Agent, no key):
  * the SIC code list  https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list
    a table of (code, SEC office, title); codes are printed without leading zeros (3674, and 100 for 0100);
  * the EDGAR company browser, filtered by one SIC code, as an Atom feed
    https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=3674&type=10-K&output=atom&count=100&start=0
    one <entry> per company that ever filed a 10-K under that code (so it also lists dead companies: the roll-up only keeps
    the ones that have numbers in the SEC frames for the year asked).

A SIC code has four digits. Its first two (the "major group") roll up into ten divisions, A to J, defined by the US
Standard Industrial Classification manual: `division()` below.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

# (first major group, last major group, letter, title) from the 1987 SIC manual.
DIVISIONS: tuple[tuple[int, int, str, str], ...] = (
    (1, 9, "A", "AGRICULTURE, FORESTRY, FISHING"),
    (10, 14, "B", "MINING"),
    (15, 17, "C", "CONSTRUCTION"),
    (20, 39, "D", "MANUFACTURING"),
    (40, 49, "E", "TRANSPORT, COMMUNICATIONS, UTILITIES"),
    (50, 51, "F", "WHOLESALE TRADE"),
    (52, 59, "G", "RETAIL TRADE"),
    (60, 67, "H", "FINANCE, INSURANCE, REAL ESTATE"),
    (70, 89, "I", "SERVICES"),
    (90, 99, "J", "PUBLIC ADMINISTRATION"),
)

_ROW = re.compile(r"<tr>\s*<td>\s*(\d{1,4})\s*</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def parse_sic_table(page: str) -> dict[int, dict[str, str]]:
    """{code: {"title", "office"}} from the SEC list page. A page without the table raises ValueError (the layout changed)."""
    out: dict[int, dict[str, str]] = {}
    for code, office, title in _ROW.findall(page):
        out[int(code)] = {"title": html.unescape(_TAGS.sub("", title)).strip(), "office": html.unescape(_TAGS.sub("", office)).strip()}
    if not out:
        raise ValueError("NO SIC TABLE ON THE SEC PAGE (THE PAGE LAYOUT CHANGED)")
    return out


def parse_atom(body: bytes | str) -> list[dict]:
    """[{cik, name, sic}] for every <entry> of one EDGAR company-browser Atom page. An entry with no number for CIK or SIC is skipped."""
    try:
        root = ET.fromstring(body if isinstance(body, bytes) else body.encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError(f"EDGAR ATOM PAGE DID NOT PARSE: {e}") from e
    ns = "{http://www.w3.org/2005/Atom}"
    out = []
    for entry in root.iter(f"{ns}entry"):
        info = entry.find(f"{ns}content/{ns}company-info")  # the feed's default namespace covers every unprefixed child
        if info is None:
            continue
        cik, sic = (info.findtext(f"{ns}cik") or "").strip(), (info.findtext(f"{ns}sic") or "").strip()
        if cik.isdigit() and sic.isdigit():
            out.append({"cik": int(cik), "sic": int(sic), "name": (info.findtext(f"{ns}name") or "").strip()})
    return out


def major_group(code: int) -> int:
    return code // 100


def division(code: int) -> tuple[str, str]:
    """(letter, title) of the division holding a SIC code; ("?", "UNCLASSIFIED") for a code outside the manual."""
    g = major_group(code)
    for lo, hi, letter, title in DIVISIONS:
        if lo <= g <= hi:
            return letter, title
    return "?", "UNCLASSIFIED"
