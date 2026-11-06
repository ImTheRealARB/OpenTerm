"""Service function behind MF (`/api/world/mf`): Indian mutual fund search and NAV history from MFapi.in.

`q` is either a scheme code (4 to 7 digits: the fund, with its NAV history and returns) or words (a search of scheme names). Parsing and return
maths are in `mfund.py`; fetching is in `providers/mfapi.py`. Both answers go through the shared stale-while-revalidate cache (`svc.swr`), so a
repeated keystroke, a panel reload or a second panel costs no call to the free upstream. The 40,000-scheme list is never downloaded.
"""

from __future__ import annotations

from typing import Any

from ..errors import DataError
from . import mfund

SEARCH_TTL_S = 3600.0  # scheme names almost never change
FUND_TTL_S = 1800.0  # a new NAV lands once a day (evening); half an hour keeps the "latest" fresh without hammering a free service


async def mf(svc: Any, q: str) -> dict[str, Any]:
    """The MF payload for `q` (see `mfund.fund_payload` / `mfund.search_payload`). Raises DataError for bad words, an unknown code or a provider failure."""
    try:
        kind, text = mfund.norm_query(q)
    except mfund.MfundError as e:
        raise DataError("bad_request", str(e)) from e

    if kind == "code":
        async def fetch_fund() -> dict:
            fund, failed = await svc.router.call("mf_nav", lambda p: p.mf_nav(int(text)))
            if fund is None:
                # MFapi answers an unknown code with HTTP 200 and an empty fund: say so in plain words instead of showing an empty table.
                raise DataError("not_found", f"NO FUND WITH SCHEME CODE {text}: SEARCH BY NAME WITH MF <WORDS>", "")
            return {"data": mfund.fund_payload(fund), "source": mfund.SOURCE, "fallback_from": failed}

        return await svc.swr(f"w:mf:fund:{text}", FUND_TTL_S, fetch_fund)

    async def fetch_search() -> dict:
        items, failed = await svc.router.call("mf_search", lambda p: p.mf_search(text))
        return {"data": mfund.search_payload(text, items), "source": mfund.SOURCE, "fallback_from": failed}

    return await svc.swr(f"w:mf:search:{text.lower()}", SEARCH_TTL_S, fetch_search)
