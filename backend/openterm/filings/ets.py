"""ETS: EU Emissions Trading System, installation-level verified emissions matched to a company by NAME. Emissions only, never a score. Pure.

Source: the European Commission's Union Registry public data (https://union-registry-data.ec.europa.eu, Commission reuse policy, CC BY 4.0), two files:
  * "Operators Daily"   gz CSV, one row per installation or aircraft operator with its ACCOUNT_HOLDER_NAME (the legal owner) and country;
  * "Verified Emissions for <year>"  xlsx, one row per installation: verified tonnes of CO2-equivalent and the free allowances handed out.
They join on (REGISTRY_CODE, INSTALLATION_IDENTIFIER). The account holder is NOT the listed parent: it is often a local subsidiary ("Alcoa Norway AS"),
so a company is matched when its core name opens the holder's name, and every row says NAME MATCH. Installations that closed or have no verified figure
keep an empty cell, never a zero.
"""

from __future__ import annotations

import csv
import gzip
import io
from typing import Any

from ..macrod import xlsx
from ..research.table import col, head, payload, section
from .legal import core_name

NAME_MATCH = "NAME MATCH"
LABEL = "EMISSIONS ONLY, NO SCORE"
YEAR_NOW = 2024  # the newest verified year the Commission had published on 2026-11-25 ("Verified Emissions for 2025" lists installations of 2025 reports from April 2026)
LIST_URL = "https://union-registry-data.ec.europa.eu/api/data-download"
OPERATORS_KEY = "Operators Daily"


def verified_key(year: int) -> str:
    return f"Verified Emissions for {int(year)}"


def parse_download_list(body: Any) -> dict[str, str]:
    """{extract name: url} from the portal's list. Any other shape raises ValueError (the portal changed)."""
    if not isinstance(body, list) or not all(isinstance(x, dict) and "name" in x and "url" in x for x in body):
        raise ValueError("THE UNION REGISTRY DOWNLOAD LIST HAS A NEW SHAPE")
    return {str(x["name"]): str(x["url"]) for x in body}


def parse_operators(gz: bytes) -> list[dict[str, str]]:
    """[{key, installation, country, activity, holder}] for every installation with an account-holder name."""
    try:
        text = gzip.decompress(gz).decode("utf-8")
    except (OSError, UnicodeDecodeError, EOFError) as e:
        raise ValueError(f"THE OPERATORS FILE IS NOT A GZIP CSV: {e}") from e
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        holder = (r.get("ACCOUNT_HOLDER_NAME") or "").strip()
        if holder and r.get("INSTALLATION_IDENTIFIER") and r.get("REGISTRY_CODE"):
            out.append({"key": f"{r['REGISTRY_CODE']}:{r['INSTALLATION_IDENTIFIER'].strip()}", "installation": (r.get("INSTALLATION_NAME") or "").strip(),
                        "country": (r.get("REGISTRY_NAME") or r["REGISTRY_CODE"]).strip(), "activity": (r.get("ACTIVITY_TYPE") or "").strip(), "holder": holder})
    if not out:
        raise ValueError("THE OPERATORS FILE HAS NO ACCOUNT-HOLDER ROWS")
    return out


def _num(v: object) -> float | None:
    """-1 is the file's 'blank' marker; text such as 'Excluded' is not a number."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def parse_verified(workbook: bytes, year: int) -> dict[str, dict[str, Any]]:
    """{key: {name, verified, free, status}} from the 'data' sheet; the header row is the one that starts with REGISTRY_CODE."""
    try:
        grid = xlsx.read_sheet(workbook, "data")
    except xlsx.XlsxError as e:
        raise ValueError(str(e)) from e
    hdr = next((i for i, r in enumerate(grid) if r and r[0] == "REGISTRY_CODE"), None)
    if hdr is None:
        raise ValueError("THE VERIFIED EMISSIONS SHEET HAS NO REGISTRY_CODE HEADER ROW")
    names = [str(x) for x in grid[hdr]]
    try:
        c_reg, c_id, c_name = names.index("REGISTRY_CODE"), names.index("INSTALLATION_IDENTIFIER"), names.index("INSTALLATION_NAME")
        c_ver, c_free = names.index(f"VERIFIED_EMISSIONS_{year}"), names.index(f"ALLOCATION_{year}")
    except ValueError as e:
        raise ValueError(f"THE WORKBOOK HAS NO COLUMNS FOR {year}") from e
    out: dict[str, dict[str, Any]] = {}
    for r in grid[hdr + 1:]:
        if len(r) <= c_ver or r[c_id] in (None, ""):
            continue
        ident = str(int(r[c_id])) if isinstance(r[c_id], float) else str(r[c_id]).strip()
        v = r[c_ver]
        out[f"{r[c_reg]}:{ident}"] = {"name": str(r[c_name] or ""), "verified": _num(v), "free": _num(r[c_free]),
                                      "status": v.strip().upper() if isinstance(v, str) and v.strip() else None}
    return out


def holder_matches(holder: str, core: str) -> bool:
    """The company's core words open the holder's name, word for word ('ALCOA' opens 'Alcoa Norway AS'; 'DOW' does not open 'Dowlais Group')."""
    want, have = core.split(), core_name(holder).split()
    return bool(want) and have[: len(want)] == want


def installations(operators: list[dict[str, str]], verified: dict[str, dict[str, Any]], company: str) -> list[dict[str, Any]]:
    core = core_name(company)
    rows = []
    for o in operators:
        if not holder_matches(o["holder"], core):
            continue
        v = verified.get(o["key"], {})
        rows.append({"installation": o["installation"] or v.get("name") or None, "country": o["country"], "activity": o["activity"] or None, "holder": o["holder"],
                     "tons": v.get("verified"), "free": v.get("free"), "status": v.get("status"), "match": NAME_MATCH})
    rows.sort(key=lambda r: -(r["tons"] or 0.0))
    return rows


def build_payload(symbol: str, company: str, year: int, rows: list[dict[str, Any]], source: str) -> dict:
    cols = [col("installation", "Installation", "text", 32), col("country", "Country", "text", 12), col("activity", "Activity", "text", 28),
            col("tons", "Verified t CO2e", "int"), col("free", "Free allowances", "int"), col("holder", "Account holder", "text", 34), col("match", "Match", "text")]
    total = sum(r["tons"] for r in rows if r["tons"] is not None)
    notes = [f"{LABEL}. EU ETS VERIFIED EMISSIONS (EUROPEAN COMMISSION, UNION REGISTRY) OF INSTALLATIONS WHOSE ACCOUNT-HOLDER NAME OPENS WITH THE COMPANY'S NAME.",
             "THE ACCOUNT HOLDER IS OFTEN A LOCAL SUBSIDIARY, NOT THE LISTED PARENT: A SUBSIDIARY WITH ANOTHER NAME IS MISSING, A UNRELATED FIRM WITH THE SAME OPENING WORDS CAN APPEAR",
             "EMPTY CELL = NO VERIFIED FIGURE FILED (OR 'EXCLUDED' = LEFT OUT OF THE ETS FOR THE YEAR): NEVER READ AS ZERO. NO SCOPE 2/3, NO SITES OUTSIDE THE EU ETS"]
    if not rows:
        notes.append("NO EU ETS ACCOUNT HOLDER STARTS WITH THIS NAME")
    return payload(
        symbol, f"ETS {symbol or company}",
        [head("COMPANY", company), head("MATCHED ON", core_name(company)), head("YEAR", str(year)), head("INSTALLATIONS", str(len(rows))),
         head("VERIFIED t CO2e", f"{total:,.0f}" if rows else "-", total if rows else None)],
        [section("installations", f"EU ETS installations, {year}", cols, rows, f"{LABEL} - {NAME_MATCH}")],
        notes=notes, source=source, status=None,
    )
