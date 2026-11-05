"""Service function behind PORTS (`/api/world/ports`): daily port activity from IMF PortWatch.

Bare call = the 25 busiest ports of the newest 7 days. With words (`rotterdam`, `japan`, `port said`) = the biggest 20 ports
whose name or country contains every word. See `ports.py` for why it never downloads the whole layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..redact import redact
from ..service import DataError
from . import ports

PORTS_TTL_S = 6 * 3600.0  # PortWatch publishes weekly, so asking more often only costs ArcGIS calls
PORTS_SOURCE = "IMF PORTWATCH (SATELLITE AIS PORT CALLS; UN GLOBAL PLATFORM / OXFORD)"
NOTE = ("PORT CALLS COUNTED FROM SATELLITE AIS SIGNALS, PUBLISHED WEEKLY: THE NEWEST DAY IS USUALLY 6 TO 12 DAYS OLD. "
        "7D = AVERAGE CALLS PER DAY OVER THE LAST 7 DAYS ON RECORD; VS 21D = CHANGE AGAINST THE 21 DAYS BEFORE THEM. "
        "IMPORT AND EXPORT ARE PORTWATCH'S OWN MODELLED DAILY TRADE ESTIMATES (THE LAYER DOES NOT STATE A UNIT; PORTWATCH PUBLISHES "
        "THEM AS METRIC TONS), NOT MEASURED CARGO. NOT A PRICE OR A FORECAST.")


async def ports_board(svc: Any, query: str) -> dict[str, Any]:
    """The PORTS board for `query` ("" = busiest 25). Raises DataError for bad words, no data or a provider failure."""
    try:
        words = ports.words_of(query)
    except ValueError as e:
        raise DataError("bad_request", str(e), "") from e
    today = datetime.now(UTC).date()

    async def fetch() -> dict:
        got, failed = await svc.router.call("ports_activity", lambda p: p.ports_activity(today, words))
        if words and not got["daily"]:
            # A search that matches nothing is a clear answer for the user, not a data fault: say so in plain words.
            raise DataError("not_found", f"NO PORT MATCHES {' '.join(words)}: TRY A PORT NAME (ROTTERDAM) OR A COUNTRY (JAPAN)", "")
        try:
            rows, missing = ports.board(got["daily"], got["meta"], today)
        except ValueError as e:
            raise DataError("unavailable", redact(str(e)), "") from e
        newest = max(r["date"] for r in rows)
        mode = "search" if words else "top"
        return {"data": {"rows": rows, "newest": newest, "mode": mode, "query": " ".join(words), "no_daily_rows": missing, "note": NOTE},
                "source": PORTS_SOURCE, "fallback_from": failed}

    return await svc._swr(f"w:ports:{' '.join(words)}", PORTS_TTL_S, fetch)
