"""Service function behind SHIP (`/api/world/ship`): the chokepoint board from IMF PortWatch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..service import DataError
from . import shipping

SHIP_TTL_S = 6 * 3600.0  # PortWatch publishes weekly, so asking more often only costs ArcGIS calls
SHIP_SOURCE = "IMF PORTWATCH (SATELLITE AIS SHIP COUNTS; UN GLOBAL PLATFORM / OXFORD)"
NOTE = ("SHIPS COUNTED FROM SATELLITE AIS SIGNALS, PUBLISHED WEEKLY: THE NEWEST DAY IS USUALLY 8 TO 12 DAYS OLD. "
        "7D = AVERAGE OF THE LAST 7 DAYS ON RECORD; VS 21D = CHANGE AGAINST THE 21 DAYS BEFORE THEM. A TRANSIT COUNT IS NOT A PRICE OR A FORECAST.")


async def ship(svc: Any) -> dict[str, Any]:
    today = datetime.now(UTC).date()

    async def fetch() -> dict:
        attrs, failed = await svc.router.call("shipping_chokepoints", lambda p: p.chokepoints(today))
        try:
            rows = shipping.board(attrs, today)
        except ValueError as e:
            raise DataError("unavailable", str(e), "") from e
        newest = max(r["date"] for r in rows)
        return {"data": {"rows": rows, "newest": newest, "note": NOTE}, "source": SHIP_SOURCE, "fallback_from": failed}

    return await svc._swr("w:ship", SHIP_TTL_S, fetch)
