"""IMF PortWatch (keyless): daily ship transits through 28 sea chokepoints (Suez, Panama, Hormuz and so on).

Data comes from the public ArcGIS service the PortWatch site itself reads. Ships are counted from satellite
AIS signals by the UN Global Platform and the University of Oxford for the IMF; it is published weekly.
Terms: free; the dataset's metadata asks for the citation "IMF PortWatch (portwatch.imf.org)".
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, ClassVar

from ..world import ports, shipping
from .base import Provider, ProviderError

SHIPPING = "shipping_chokepoints"
PORTS = "ports_activity"  # PORTS panel: daily port calls at ports (second capability of this provider)
_BASE = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/"
URL = _BASE + "Daily_Chokepoints_Data/FeatureServer/0/query"
PORTS_DAILY_URL = _BASE + "Daily_Ports_Data/FeatureServer/0/query"  # one row per port per day
PORTS_LIST_URL = _BASE + "PortWatch_ports_database/FeatureServer/0/query"  # one row per port: name, country, lat, lon
PORTS_TIMEOUT = 45.0  # a first (uncached) ports query took 12 to 19 s on 2026-11-05, the repeat 0 s: 20 s timed out
HISTORY_DAYS = 40  # covers the 7-day window, the 21-day base and the 8 to 12 day publishing lag
PAGE = 1000  # the service returns at most 1000 rows per call
MAX_PAGES = 5  # 28 chokepoints x 40 days = 1120 rows, so 2 pages; 5 is a hard stop against a runaway loop
ATTEMPTS = 6  # see shipping.FLAKY_MESSAGES: about 2 of 3 calls hit a bad node, so a few tries are needed


class PortWatchProvider(Provider):
    name = "portwatch"
    label = "IMF PortWatch (ship transits at chokepoints)"
    capabilities = frozenset({SHIPPING, PORTS})
    markets = ("28 sea chokepoints: daily ship counts by type (tanker, container, dry bulk); "
               "about 1,600 ports: daily port calls and trade estimates; weekly update")
    terms = "Free, no key. Cite: IMF PortWatch (portwatch.imf.org). Satellite AIS counts, 8 to 12 days behind."
    rate = (1.0, 3)
    timeout = 20.0  # ArcGIS answers in 1 to 10 s
    max_wait = 3.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def _page(self, params: dict[str, Any], url: str = URL, timeout: float | None = None) -> list[dict[str, Any]]:
        """One page, retried only when the service reports its known node glitch. Real errors raise at once."""
        last: shipping.PortWatchError | None = None
        for attempt in range(ATTEMPTS):
            try:
                return shipping.check_body(await self.get_json(url, params, timeout))
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

    async def _daily(self, ids: list[str], today: date) -> list[dict[str, Any]]:
        """Daily rows of the given ports (at most 25 ports x 40 days, so one page; the loop is a hard stop, not an expectation)."""
        since = today - timedelta(days=ports.HISTORY_DAYS)
        base = {"f": "json", "returnGeometry": "false", "where": ports.daily_where(ids, since), "outFields": ports.DAILY_FIELDS,
                "orderByFields": "portid,date", "resultRecordCount": PAGE}
        rows: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            got = await self._page({**base, "resultOffset": page * PAGE}, PORTS_DAILY_URL, PORTS_TIMEOUT)
            rows += got
            if len(got) < PAGE:
                return rows
        raise ProviderError("unavailable", "PORTWATCH RETURNED MORE ROWS THAN EXPECTED (TOO MANY PORTS?)")

    async def ports_activity(self, today: date, words: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Daily rows for a small set of ports: the busiest 25 (no words) or the biggest 20 matching the words. Never the whole layer.
        Returns {"daily": rows, "meta": port-list rows (empty for the busiest-25 case)}."""
        meta: list[dict[str, Any]] = []
        if words:
            meta = await self._page({"f": "json", "returnGeometry": "false", "where": ports.ports_where(words),
                                     "outFields": ports.PORT_FIELDS, "orderByFields": "vessel_count_total DESC",
                                     "resultRecordCount": ports.MATCH_N}, PORTS_LIST_URL, PORTS_TIMEOUT)
            ids = ports.match_ids(meta)
            if not ids:
                return {"daily": [], "meta": []}  # nothing matches: the caller says so, it is not an error
        else:
            # Step 1: which day is the newest on record? Step 2: a server-side sum of port calls over those 7 days, 25 biggest.
            newest = ports.newest_day(await self._page({"f": "json", "where": "1=1", "outStatistics": ports.NEWEST_STATS},
                                                         PORTS_DAILY_URL, PORTS_TIMEOUT))
            since = ports.top_window_start(newest)
            top = await self._page({"f": "json", "where": f"date > DATE '{since.isoformat()}'", "groupByFieldsForStatistics": "portid",
                                    "outStatistics": ports.TOP_STATS, "orderByFields": "calls7 DESC", "resultRecordCount": ports.TOP_N},
                                   PORTS_DAILY_URL, PORTS_TIMEOUT)
            ids = ports.top_ids(top)
        return {"daily": await self._daily(ids, today), "meta": meta}

    async def probe(self) -> None:
        await self._page({"f": "json", "returnGeometry": "false", "where": "portid='chokepoint1'", "outFields": "date",
                          "resultRecordCount": 1})
