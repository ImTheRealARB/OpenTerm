"""AMFI mutual fund NAV (Phase 19 step 9): `NAVAll.txt`, the daily net asset value of every Indian mutual fund scheme. Keyless.

`www.amfiindia.com/spages/NAVAll.txt` answers 302 to `portal.amfiindia.com/spages/NAVAll.txt`; one hop to a host of amfiindia.com is followed
(the shared HTTP client does not follow redirects on its own, and a hop anywhere else is refused). The file is about 1.5 MB, `;`-separated,
with category and AMC header lines between the scheme rows; `world/india.py` parses it. NAV is an end-of-day value per unit, published by AMFI
in the evening: it is not a market price.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlparse

from ..world.india import parse_amfi
from .base import Provider, ProviderError

MFNAV = "mfnav"
URL = "https://www.amfiindia.com/spages/NAVAll.txt"
MAX_BYTES = 12_000_000


class AmfiProvider(Provider):
    name = "amfi"
    label = "AMFI mutual fund NAV"
    capabilities = frozenset({MFNAV})
    markets = "Indian mutual funds: scheme code, ISIN, plan, option and the latest daily NAV for about 14,000 schemes"
    terms = "Public AMFI file (amfiindia.com/spages/NAVAll.txt), no key. End-of-day NAV, published in the evening."
    rate = (0.5, 2)
    max_wait = 2.0
    timeout = 60.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "text/plain,*/*"}

    async def navall(self) -> dict[str, Any]:
        r = await self._request(URL, None, None)
        if r.status_code in (301, 302, 303, 307, 308):
            where = r.headers.get("location", "")
            host = urlparse(where).hostname or ""
            if not (host == "amfiindia.com" or host.endswith(".amfiindia.com")) or urlparse(where).scheme != "https":
                raise ProviderError("unavailable", "AMFI REDIRECTED SOMEWHERE ELSE: NOT FOLLOWED")
            r = await self._request(where, None, None)
        if r.status_code != 200 or len(r.content) > MAX_BYTES:
            raise ProviderError("unavailable", f"HTTP {r.status_code}, {len(r.content)} bytes")
        table = parse_amfi(r.content.decode("utf-8", "replace"))
        if not table["rows"]:
            raise ProviderError("unavailable", "NAVAll.txt HAS NO SCHEME ROWS (CHANGED FORMAT?)")
        table["source"] = self.source
        return table

    async def probe(self) -> None:
        await self.navall()
