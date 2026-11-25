"""EU Emissions Trading System through the European Commission's Union Registry public data (keyless), for ETS.

Two downloads joined by `filings/ets.py`: the portal's own list of extracts (`/api/data-download`, which also gives each file's current URL), the
Operators Daily gz CSV (about 2 MB) and one Verified Emissions workbook (about 7 MB). They change at most daily, so the parsed tables are kept in memory
for 12 hours; the parse runs in a thread (the workbook has 17,000 rows) so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

from ..filings import ets as E
from .base import Provider, ProviderError

CAPABILITY = "eu_ets"
MEMO_S = 12 * 3600.0


class EuEtsProvider(Provider):
    name = "eu_ets"
    label = "EU Emissions Trading System (Union Registry)"
    capabilities = frozenset({CAPABILITY})
    markets = "EU ETS installations: verified emissions and free allowances by account holder (European Commission, CC BY 4.0)"
    terms = "European Commission public data, no key (reuse under CC BY 4.0). Two files of about 9 MB in total, read at most twice a day."
    rate = (1.0, 3)
    max_wait = 5.0
    timeout = 120.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._ops: tuple[float, list[dict[str, str]]] | None = None
        self._ver: dict[int, tuple[float, dict[str, dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def installations(self, company: str, year: int) -> dict[str, Any]:
        """Rows of the installations whose account holder opens with `company`'s core name, for one verified-emissions year."""
        async with self._lock:  # one download at a time: two panels asking at once must not fetch the 9 MB twice
            try:
                listing = E.parse_download_list(await self.get_json(E.LIST_URL))
                now = time.time()
                if self._ops is None or now - self._ops[0] > MEMO_S:
                    self._ops = (now, await asyncio.to_thread(E.parse_operators, await self.get_bytes(listing[E.OPERATORS_KEY])))
                hit = self._ver.get(year)
                if hit is None or now - hit[0] > MEMO_S:
                    url = listing.get(E.verified_key(year))
                    if url is None:
                        raise ProviderError("not_found", f"THE UNION REGISTRY HAS NO VERIFIED EMISSIONS FILE FOR {year}")
                    self._ver[year] = (now, await asyncio.to_thread(E.parse_verified, await self.get_bytes(url), year))
            except KeyError as e:
                raise ProviderError("unavailable", f"THE UNION REGISTRY LIST HAS NO {e}") from e
            except ValueError as e:
                raise ProviderError("unavailable", str(e)) from e
            ops, ver = self._ops[1], self._ver[year][1]
        rows = E.installations(ops, ver, company)
        return {"rows": rows, "year": year, "source": self.source, "as_of": self.now()}

    async def probe(self) -> None:
        E.parse_download_list(await self.get_json(E.LIST_URL))
