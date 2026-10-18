"""Exchange holidays for the market lights: NYSE / Nasdaq by rule, everything else from Nager.Date public holidays (labelled; the exchange may differ)."""

from __future__ import annotations

import time
from typing import Any

from ..service import DataError
from . import nyse_holidays as nyse

MARKET_COUNTRY = {"LN": "GB", "TK": "JP", "HK": "HK", "IN": "IN"}
MARKETS = ("NY", *MARKET_COUNTRY)
TTL_S = 7 * 86400.0
NYSE_LABEL = "NYSE / NASDAQ HOLIDAYS BY RULE (CHECKED AGAINST THE PUBLISHED LIST 2024-2027)"
NAGER_LABEL = "PUBLIC HOLIDAYS (EXCHANGE MAY DIFFER)"


def parse_nager(body: Any) -> list[dict[str, Any]]:
    """Public holidays sorted by date; `national` is False for a holiday that applies only to some regions."""
    if not isinstance(body, list):
        return []
    out = []
    for r in body:
        if not isinstance(r, dict) or not r.get("date"):
            continue
        types = r.get("types") or ["Public"]
        if "Public" not in types:
            continue
        out.append({"date": str(r["date"])[:10], "name": r.get("name") or r.get("localName") or "", "national": bool(r.get("global", True))})
    return sorted(out, key=lambda x: x["date"])


def national_dates(rows: list[dict[str, Any]]) -> set[str]:
    return {r["date"] for r in rows if r["national"]}


def nyse_payload(year: int) -> dict[str, Any]:
    return {
        "mkt": "NY", "year": year, "basis": "rules", "label": NYSE_LABEL,
        "holidays": [{"date": d.isoformat(), "name": n, "national": True} for d, n in nyse.holidays(year).items()],
        "early": [{"date": d.isoformat(), "name": n} for d, n in nyse.early_closes(year).items()],
        "source": "nyse_rules",
    }


async def calendar(svc: Any, mkt: str, year: int) -> dict[str, Any]:
    mkt = mkt.upper()
    if mkt not in MARKETS:
        raise DataError("bad_request", f"MKT MUST BE ONE OF {' '.join(MARKETS)}")
    if not 2000 <= year <= 2040:
        raise DataError("bad_request", "YEAR: 2000-2040")
    if mkt == "NY":
        return {"data": nyse_payload(year), "source": "nyse_rules", "as_of": time.time(), "age_s": 0.0, "stale": False, "fallback_from": []}
    cc = MARKET_COUNTRY[mkt]

    async def fetch() -> dict:
        rows, failed = await svc.router.call("holidays", lambda p: p.holidays(cc, year))
        return {"data": {"mkt": mkt, "year": year, "basis": "public", "label": NAGER_LABEL, "holidays": parse_nager(rows), "early": [],
                         "source": "nager"}, "fallback_from": failed, "source": "nager"}

    return await svc._swr(f"w:hol:{mkt}:{year}", TTL_S, fetch)
