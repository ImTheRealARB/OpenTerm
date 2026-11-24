"""ESG: greenhouse-gas EMISSIONS only, from the US EPA Greenhouse Gas Reporting Program (GHGRP). Pure.

NOT A SCORE. It is a list of US facilities whose reported parent-company text contains the company's name, with each facility's reported
CO2-equivalent tonnes for one reporting year. EPA's parent text carries ownership shares ("ALCOA CORP (60%); OTHER CO (40%)"): where one
is stated for the matched name the table also shows the share-weighted tonnes. Matching is by NAME, so every row says NAME MATCH.
Only facilities above the programme's reporting threshold (25,000 t CO2e a year) exist here; scope 2/3 and non-US sites are absent.
"""

from __future__ import annotations

import re
from typing import Any

from ..research.table import col, head, payload, section
from .legal import core_name

NAME_MATCH = "NAME MATCH"
LABEL = "EMISSIONS ONLY, NO SCORE"
LATEST_YEAR = 2023  # the newest reporting year EPA served on 2026-11-24 (year 2024 answered with no rows)
ROW_CAP = 2000  # the most joined rows asked for in one request
_SHARE = re.compile(r"(?P<who>[^;()]+?)\s*\((?P<pct>\d+(?:\.\d+)?)%\)")


def stated_share(parent_text: str | None, company: str) -> float | None:
    """The ownership percentage EPA lists for `company` inside a parent text, or None when no entry IS the company (same core name).
    The same entry can repeat (EPA data does): equal entries count once, and the largest distinct share wins."""
    core = core_name(company)
    if not parent_text or not core:
        return None
    best = None
    for m in _SHARE.finditer(parent_text.upper()):
        if core_name(m.group("who")) == core:  # the whole entry is the company: "CITY OF ALCOA TENNESSEE" must not take Alcoa's share
            pct = float(m.group("pct"))
            best = pct if best is None else max(best, pct)
    return best


def facilities(rows: list[dict[str, Any]], company: str) -> list[dict[str, Any]]:
    """One row per facility: the sum of its `co2e_emission` rows (null rows add nothing), and the share stated for the company."""
    by_id: dict[int, dict[str, Any]] = {}
    for r in rows:
        f = by_id.setdefault(r["facility_id"], {
            "facility": r.get("facility_name"), "city": r.get("city"), "state": r.get("state"), "year": r.get("year"),
            "parent": r.get("parent_company"), "co2e": 0.0, "has_value": False})
        if r.get("co2e_emission") is not None:
            f["co2e"] += float(r["co2e_emission"])
            f["has_value"] = True
    out = []
    for f in by_id.values():
        share = stated_share(f["parent"], company)
        total = f["co2e"] if f["has_value"] else None
        out.append({"facility": f["facility"], "place": ", ".join(x for x in (f["city"], f["state"]) if x) or None, "year": f["year"],
                    "parent": f["parent"], "co2e": total, "share": share,
                    "weighted": total * share / 100.0 if total is not None and share is not None else None, "match": NAME_MATCH})
    out.sort(key=lambda x: -(x["co2e"] or 0.0))
    return out


def build_payload(symbol: str, company: str, year: int, rows: list[dict[str, Any]], source: str, capped: bool) -> dict:
    cols = [col("facility", "Facility", "text", 34), col("place", "Place", "text", 20), col("co2e", "t CO2e", "int"), col("share", "Share %", "num"),
            col("weighted", "Weighted t", "int"), col("parent", "Parent text (EPA)", "text", 50), col("match", "Match", "text")]
    total = sum(r["co2e"] for r in rows if r["co2e"] is not None)
    weighted = sum(r["weighted"] for r in rows if r["weighted"] is not None)
    notes = [f"{LABEL}. NO SCOPE 2/3, NO NON-US SITES, ONLY FACILITIES OVER THE 25,000 t CO2e REPORTING THRESHOLD.",
             "EU ETS: NOT BUILT (NO COMPANY LOOKUP ADDED). 'WEIGHTED' NEEDS A SHARE STATED BY EPA FOR THIS NAME; WITHOUT ONE IT STAYS EMPTY"]
    if capped:
        notes.append(f"EPA ANSWER CUT AT {ROW_CAP} ROWS: SOME FACILITIES MAY BE MISSING")
    return payload(
        symbol, f"ESG {symbol}",
        [head("COMPANY", company), head("MATCHED ON", core_name(company)), head("YEAR", str(year)), head("FACILITIES", str(len(rows))),
         head("FACILITY t CO2e", f"{total:,.0f}", total), head("WEIGHTED t CO2e", f"{weighted:,.0f}" if weighted else "-")],
        [section("facilities", f"GHGRP facilities, {year}", cols, rows, f"{LABEL} · {NAME_MATCH}")],
        notes=notes, source=source, status=None,
    )
