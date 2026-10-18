"""FOMC decisions as ECO calendar rows (pure). The statement is released at 14:00 US Eastern on the decision day."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SOURCE = "federalreserve.gov"


def fomc_events(dates: list[str], since: str) -> list[dict[str, Any]]:
    """EcoEvent-shaped dicts for decision dates on or after `since` (YYYY-MM-DD)."""
    out = []
    for d in dates:
        if d < since:
            continue
        ts = datetime.fromisoformat(d + "T14:00:00").replace(tzinfo=NY).timestamp()
        out.append({"date": d, "time": "14:00", "ts": ts, "name": "FOMC DECISION", "agency": "FED", "major": True, "source": SOURCE})
    return out
