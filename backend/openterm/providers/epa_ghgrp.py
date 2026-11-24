"""US EPA Greenhouse Gas Reporting Program (GHGRP) through the Envirofacts REST API (data.epa.gov/efservice), for ESG. Keyless.

One request joins two tables: `PUB_DIM_FACILITY` (facility, place, parent-company text) filtered by `PARENT_COMPANY CONTAINING <name>` and one
`YEAR`, with `PUB_FACTS_SECTOR_GHG_EMISSION` (CO2-equivalent tonnes per sector and gas). Envirofacts answers a join as one flat row per emission
record. A name with no match is an empty list (HTTP 200); the same goes for a year not yet published (2024 was empty on 2026-11-24).
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from ..filings import esg as E
from .base import Provider, ProviderError

CAPABILITY = "ghg_facilities"
BASE = "https://data.epa.gov/efservice"
KEEP = ("facility_id", "facility_name", "city", "state", "year", "parent_company", "sector_id", "subsector_id", "gas_id", "co2e_emission")


class EpaGhgrpProvider(Provider):
    name = "epa_ghgrp"
    label = "US EPA Greenhouse Gas Reporting Program"
    capabilities = frozenset({CAPABILITY})
    markets = "US facilities over 25,000 t CO2e a year: reported emissions by parent-company text (emissions only, no score)"
    terms = "US government data, no key. Envirofacts REST API; answers can be slow (the join takes several seconds)."
    rate = (1.0, 3)
    max_wait = 3.0
    timeout = 90.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm"}

    async def facilities(self, core_name: str, year: int) -> dict[str, Any]:
        """Joined emission rows for facilities whose parent text contains `core_name` in reporting `year`."""
        url = (f"{BASE}/PUB_DIM_FACILITY/PARENT_COMPANY/CONTAINING/{quote(core_name)}/YEAR/{int(year)}"
               f"/PUB_FACTS_SECTOR_GHG_EMISSION/rows/0:{E.ROW_CAP - 1}/JSON")
        body = await self.get_json(url)
        if not isinstance(body, list):
            raise ProviderError("unavailable", "EPA ANSWERED WITH SOMETHING OTHER THAN A LIST")
        if not body:
            raise ProviderError("not_found", f"NO GHGRP FACILITY HAS {core_name} IN ITS PARENT TEXT FOR {year}")
        rows = [{k: r.get(k) for k in KEEP} for r in body]
        return {"rows": rows, "capped": len(body) >= E.ROW_CAP, "year": year, "source": self.source, "as_of": self.now()}

    async def probe(self) -> None:
        await self.get_json(f"{BASE}/PUB_DIM_SECTOR/rows/0:0/JSON")
