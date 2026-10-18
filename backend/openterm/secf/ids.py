"""SECF identifier handling (pure): ISIN / CUSIP / SEDOL / FIGI detection with check digits, and the OpenFIGI mapping parser.

The same shape and check-digit rules live in `frontend/src/functions/secfIds.ts` so the panel decides locally whether a word is an
identifier; this copy is the server's own validation (a bad value never costs a rate-limited upstream request).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ID_TYPES = {"ISIN": "ID_ISIN", "CUSIP": "ID_CUSIP", "SEDOL": "ID_SEDOL", "FIGI": "ID_BB_GLOBAL"}

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_CUSIP = re.compile(r"^[A-Z0-9*@#]{8}[0-9]$")
_SEDOL = re.compile(r"^[0-9B-DF-HJ-NP-TV-Z]{6}[0-9]$")
_FIGI = re.compile(r"^[A-Z]{2}G[A-Z0-9]{8}[0-9]$")
_SPLIT = re.compile(r"[\s,;]+")


@dataclass(frozen=True)
class Ident:
    kind: str  # ISIN | CUSIP | SEDOL | FIGI
    value: str
    valid: bool  # the check digit holds (FIGI: shape only)


def _alnum(c: str) -> int:
    return int(c) if c.isdigit() else ord(c) - 55  # A=10 .. Z=35


def isin_ok(s: str) -> bool:
    if not _ISIN.match(s):
        return False
    digits = "".join(str(_alnum(c)) for c in s[:11])
    total = 0
    for i, ch in enumerate(reversed(digits)):  # Luhn over the expanded string, rightmost digit doubled first
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d // 10 + d % 10
    return (10 - total % 10) % 10 == int(s[11])


def cusip_check(base8: str) -> int:
    total = 0
    for i, c in enumerate(base8):
        v = _alnum(c) if c.isalnum() else {"*": 36, "@": 37, "#": 38}[c]
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10


def cusip_ok(s: str) -> bool:
    return bool(_CUSIP.match(s)) and cusip_check(s[:8]) == int(s[8])


def sedol_ok(s: str) -> bool:
    if not _SEDOL.match(s):
        return False
    weights = (1, 3, 1, 7, 3, 9)
    total = sum(_alnum(c) * w for c, w in zip(s[:6], weights, strict=True))
    return (10 - total % 10) % 10 == int(s[6])


def classify(text: str) -> Ident | None:
    """The identifier a word is, or None when it is a name or ticker. A right shape with a wrong check digit is returned with valid=False."""
    t = text.strip().upper()
    if t.startswith("FIGI:"):
        t = t[5:]
        return Ident("FIGI", t, True) if _FIGI.match(t) else None
    if _ISIN.match(t):
        if isin_ok(t):
            return Ident("ISIN", t, True)
        if t.startswith("BBG") and _FIGI.match(t):
            return Ident("FIGI", t, True)
        return Ident("ISIN", t, False)
    if _CUSIP.match(t) and len(t) == 9:
        return Ident("CUSIP", t, cusip_ok(t))
    if _SEDOL.match(t) and len(t) == 7:
        return Ident("SEDOL", t, sedol_ok(t))
    return None


def split_query(q: str) -> list[str]:
    """Words of a query split on spaces, commas and semicolons, duplicates dropped, order kept."""
    seen: dict[str, None] = {}
    for w in _SPLIT.split(q.strip()):
        if w:
            seen.setdefault(w.upper(), None)
    return list(seen)


def _listing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "figi": row.get("figi"),
        "composite_figi": row.get("compositeFIGI"),
        "share_class_figi": row.get("shareClassFIGI"),
        "ticker": row.get("ticker"),
        "name": row.get("name"),
        "exch_code": row.get("exchCode"),
        "security_type": row.get("securityType"),
        "market_sector": row.get("marketSector"),
        "description": row.get("securityDescription"),
    }


def parse_mapping(jobs: list[Ident], results: list[Any]) -> list[dict[str, Any]]:
    """One item per job, in order: FOUND (listings, composite first), NOT FOUND, or ERROR (upstream said why, or sent too few answers)."""
    items: list[dict[str, Any]] = []
    for i, job in enumerate(jobs):
        res = results[i] if i < len(results) else None
        item: dict[str, Any] = {"kind": job.kind, "id": job.value, "status": "ERROR", "message": None, "listings": []}
        if not isinstance(res, dict):
            item["message"] = "NO ANSWER FROM OPENFIGI FOR THIS IDENTIFIER"
        elif res.get("data"):
            listings = [_listing(r) for r in res["data"] if isinstance(r, dict)]
            listings.sort(key=lambda x: x["figi"] != x["composite_figi"])  # stable: the composite listing first, upstream order otherwise
            item.update(status="FOUND", listings=listings)
        elif "warning" in res:
            item.update(status="NOT FOUND", message=str(res["warning"]))
        else:
            item["message"] = str(res.get("error") or "UNKNOWN ANSWER")[:200]
        items.append(item)
    return items
