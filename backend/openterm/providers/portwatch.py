"""IMF PortWatch (keyless): daily ship transits through 28 sea chokepoints (Suez, Panama, Hormuz and so on).

Data comes from the public ArcGIS service the PortWatch site itself reads. Ships are counted from satellite
AIS signals by the UN Global Platform and the University of Oxford for the IMF; it is published weekly.
Terms: free; the dataset's metadata asks for the citation "IMF PortWatch (portwatch.imf.org)".
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, ClassVar

from ..world import shipping
from .base import Provider, ProviderError

SHIPPING = "shipping_chokepoints"
URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"
HISTORY_DAYS = 40  # covers the 7-day window, the 21-day base and the 8 to 12 day publishing lag
PAGE = 1000  # the service returns at most 1000 rows per call
MAX_PAGES = 5  # 28 chokepoints x 40 days = 1120 rows, so 2 pages; 5 is a hard stop against a runaway loop
ATTEMPTS = 6  # see shipping.FLAKY_MESSAGES: about 2 of 3 calls hit a bad node, so a few tries are needed


class PortWatchProvider(Provider):
    name = "portwatch"
    label = "IMF PortWatch (ship transits at chokepoints)"
    capabilities = frozenset({SHIPPING})
    markets = "28 sea chokepoints: daily ship counts by type (tanker, container, dry bulk), weekly update"
    terms = "Free, no key. Cite: IMF PortWatch (portwatch.imf.org). Satellite AIS counts, 8 to 12 days behind."
    rate = (1.0, 3)
    timeout = 20.0  # ArcGIS answers in 1 to 10 s
    max_wait = 3.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def _page(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """One page, retried only when the service reports its known node glitch. Real errors raise at once."""
        last: shipping.PortWatchError | None = None
        for attempt in range(ATTEMPTS):
            try:
                return shipping.check_body(await self.get_json(URL, params))
            except shipping.PortWatchError as e:
                if not e.flaky:
                    raise ProviderError("unavailable", str(e)) from e
                last = e
                await asyncio.sleep(0.3 * (attempt + 1))  # short, growing pause before asking again
        raise ProviderError("unavailable", f"{last} (STILL FAILING AFTER {ATTEMPTS} TRIES)")

    async def chokepoints(self, today: date) -> list[dict[str, Any]]:
        """Daily rows of all chokepoints since `today - HISTORY_DAYS`, paged by resultOffset."""
        since = (today - timedelta(days=HISTORY_DAYS)).isoformat()
        base = {"f": "json", "returnGeometry": "false", "where": f"date >= DATE '{since}'",
                "outFields": shipping.FIELDS, "orderByFields": "portid,date", "resultRecordCount": PAGE}
        rows: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            got = await self._page({**base, "resultOffset": page * PAGE})
            rows += got
            if len(got) < PAGE:
                return rows
        raise ProviderError("unavailable", "PORTWATCH RETURNED MORE ROWS THAN EXPECTED (WINDOW TOO WIDE?)")

    async def probe(self) -> None:
        await self._page({"f": "json", "returnGeometry": "false", "where": "portid='chokepoint1'", "outFields": "date",
                          "resultRecordCount": 1})
