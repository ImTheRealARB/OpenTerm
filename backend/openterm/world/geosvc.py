"""Service functions behind the MAP layers (`/api/world/geo/...`): one function per layer, each answering the standard envelope.

The vessels layer has no function here: it reuses `/api/world/ais` (AISstream) unchanged. These are the layers the MAP panel
fetches itself: earthquakes (USGS), natural events (NASA EONET), ports (IMF PortWatch) and the chokepoint boxes (the AIS presets).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..errors import DataError
from . import geo, ports

QUAKES_TTL_S = 120.0  # USGS rebuilds the feed every minute and asks not to be polled faster than that
EVENTS_TTL_S = 600.0
PORTS_TTL_S = 6 * 3600.0  # PortWatch publishes weekly
QUAKES_SOURCE = "USGS EARTHQUAKE HAZARDS PROGRAM (M4.5+, PAST 7 DAYS)"
EVENTS_SOURCE = "NASA EONET (OPEN NATURAL EVENTS, WILDFIRES LEFT OUT)"
PORTS_SOURCE = "IMF PORTWATCH (SATELLITE AIS PORT CALLS; UN GLOBAL PLATFORM / OXFORD)"
CHOKE_SOURCE = "OPENTERM PRESETS: BOXES DRAWN BY EYE, NOT FROM A GAZETTEER"

QUAKES_NOTE = "MAGNITUDES AND POSITIONS ARE USGS'S AND ARE REVISED AFTER THE FIRST REPORT; ONLY M4.5 AND ABOVE ARE LISTED, SO SMALLER QUAKES ARE ABSENT. NOT A FORECAST."
EVENTS_NOTE = ("EONET LISTS EVENTS THAT AN AGENCY HAS REPORTED AS OPEN. WILDFIRES ARE LEFT OUT (OVER 7,000 OPEN FIRE POINTS). "
               "A POINT IS THE EVENT'S NEWEST REPORTED POSITION; A LINE IS ITS EARLIER PATH (STORMS).")
PORTS_NOTE = "DOT SIZE = AVERAGE PORT CALLS PER DAY OVER THE LAST 7 DAYS ON RECORD (SATELLITE AIS, PUBLISHED WEEKLY, USUALLY 6 TO 12 DAYS OLD)."
CHOKE_NOTE = "THE SAME ROUGH BOXES AIS LISTENS TO. SELECT ONE AND PRESS V TO LOAD THE SHIPS INSIDE IT."


async def quakes(svc: Any) -> dict[str, Any]:
    async def fetch() -> dict:
        body, failed = await svc.router.call("geo_quakes", lambda p: p.quakes())
        try:
            data = geo.quakes(body)
        except ValueError as e:
            raise DataError("unavailable", str(e), "") from e
        return {"data": {**data, "note": QUAKES_NOTE}, "source": QUAKES_SOURCE, "fallback_from": failed}

    return await svc.swr("w:geo:quakes", QUAKES_TTL_S, fetch)


async def events(svc: Any) -> dict[str, Any]:
    async def fetch() -> dict:
        body, failed = await svc.router.call("geo_events", lambda p: p.events())
        try:
            data = geo.events(body)
        except ValueError as e:
            raise DataError("unavailable", str(e), "") from e
        return {"data": {**data, "note": EVENTS_NOTE}, "source": EVENTS_SOURCE, "fallback_from": failed}

    return await svc.swr("w:geo:events", EVENTS_TTL_S, fetch)


async def ports_map(svc: Any) -> dict[str, Any]:
    today = datetime.now(UTC).date()

    async def fetch() -> dict:
        got, failed = await svc.router.call("ports_activity", lambda p: p.ports_geo(today))
        try:
            data = geo.ports(got["top"], got["meta"], got["newest"], ports.WINDOW)
        except ValueError as e:
            raise DataError("unavailable", str(e), "") from e
        return {"data": {**data, "note": PORTS_NOTE}, "source": PORTS_SOURCE, "fallback_from": failed}

    return await svc.swr("w:geo:ports", PORTS_TTL_S, fetch)


async def chokepoints(svc: Any) -> dict[str, Any]:
    async def fetch() -> dict:
        return {"data": {"rows": geo.chokepoints(), "note": CHOKE_NOTE}, "source": CHOKE_SOURCE, "fallback_from": []}

    return await svc.swr("w:geo:choke", 3600.0, fetch)
