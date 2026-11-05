"""Keyless geo feeds for the MAP panel: USGS earthquakes and NASA EONET natural events.

Both answer plain JSON over HTTPS with no key. The adapters only fetch; `world/geo.py` turns the bodies into map rows.

USGS: the "summary" GeoJSON feeds are rebuilt every minute and meant to be polled (their page asks for no more than once a minute).
EONET: NASA's Earth Observatory Natural Event Tracker. Wildfires are left out on purpose: over 7,000 open fire events make a 5 MB
answer that takes ~8 s, and a map of that many dots says nothing; the panel states the omission.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Provider

QUAKES = "geo_quakes"
EVENTS = "geo_events"

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
# Every EONET category except wildfires (see the module note). Names are EONET's own category ids.
EONET_CATEGORIES = ("severeStorms,volcanoes,floods,seaLakeIce,earthquakes,landslides,drought,dustHaze,manmade,snow,tempExtremes,waterColor")
EONET_LIMIT = 100


class UsgsProvider(Provider):
    name = "usgs"
    label = "USGS earthquakes (M4.5+, past 7 days)"
    capabilities = frozenset({QUAKES})
    markets = "Worldwide earthquakes of magnitude 4.5 and above over the last 7 days; the feed refreshes every minute"
    terms = "Free, no key. US Geological Survey data is public domain; cite: U.S. Geological Survey (earthquake.usgs.gov). Poll at most once a minute."
    rate = (1.0, 2)
    timeout = 15.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def quakes(self) -> Any:
        return await self.get_json(USGS_URL)


class EonetProvider(Provider):
    name = "eonet"
    label = "NASA EONET (open natural events, without wildfires)"
    capabilities = frozenset({EVENTS})
    markets = "Open natural events worldwide: storms, volcanoes, floods, sea and lake ice, dust and more (wildfires left out: thousands of points)"
    terms = "Free, no key. NASA data is public domain; cite: NASA EONET (eonet.gsfc.nasa.gov). Each event also names its own source agency."
    rate = (1.0, 2)
    timeout = 20.0  # 0.9 s measured on 2026-11-05 with the category filter
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def events(self) -> Any:
        return await self.get_json(EONET_URL, {"status": "open", "limit": EONET_LIMIT, "category": EONET_CATEGORIES})
