"""Service function behind FLT (`/api/world/flt`): live aircraft from OpenSky.

Parsing is in `flights.py`, fetching (and the credit guard rails: 30 s memory per box, no calls after a 429) in `providers/opensky.py`. The result also goes
through the shared stale-while-revalidate cache for 30 s, so a repeat keystroke or a second panel costs no OpenSky credits.
"""

from __future__ import annotations

from typing import Any

from ..errors import DataError
from ..router import AllFailed
from . import flights

TTL_S = 30.0  # OpenSky's anonymous resolution is 10 s and credits are metered: nothing is gained by asking sooner


async def flt(svc: Any, q: str) -> dict[str, Any]:
    """The FLT payload for `q`. Raises DataError for bad input, a spent credit allowance (the message says when to retry) or a provider failure."""
    try:
        kind, label, box, prefix = flights.parse_args(q)
    except flights.FlightsError as e:
        raise DataError("bad_request", str(e)) from e

    async def fetch() -> dict:
        try:
            meta, failed = await svc.router.call(flights.FLIGHTS, lambda p: p.flights(box))
        except AllFailed as e:
            # A spent credit allowance is not an outage, and the generic "PROVIDER DOWN" would hide WHEN to try again: pass the provider's own words on.
            if e.errors and all(err.kind == "rate_limited" for _, err in e.errors):
                raise DataError("unavailable", str(e.errors[0][1])) from e
            raise
        return {"data": flights.payload(kind, label, box, prefix, meta), "source": flights.SOURCE, "fallback_from": failed}

    return await svc.swr(f"w:flt:{label}", TTL_S, fetch)
