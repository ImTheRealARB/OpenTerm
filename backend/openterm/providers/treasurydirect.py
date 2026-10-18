"""TreasuryDirect securities API (no key): recent auction results and announced upcoming auctions for `RATES AUCT`."""

from __future__ import annotations

from typing import ClassVar

from ..rates import parse as rp
from .base import Provider, ProviderError
from .ecb import BROWSER_UA

BASE = "https://www.treasurydirect.gov/TA_WS/securities"
AUCTIONS = "auctions"


class TreasuryDirectProvider(Provider):
    name = "treasurydirect"
    label = "TreasuryDirect auctions (public)"
    capabilities = frozenset({AUCTIONS})
    markets = "US Treasury bill, note, bond, TIPS and FRN auction results (last 30 days) and upcoming announced auctions"
    terms = "Public US government API, no key. Data: U.S. Department of the Treasury, Bureau of the Fiscal Service."
    rate = (2.0, 10)
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": BROWSER_UA, "Accept": "application/json"}

    async def auctions(self) -> dict:
        done = await self.get_json(f"{BASE}/auctioned", {"format": "json", "days": "30"})
        upcoming = await self.get_json(f"{BASE}/upcoming", {"format": "json"})
        if not isinstance(done, list) or not isinstance(upcoming, list):
            raise ProviderError("unavailable", "TreasuryDirect answered something other than a list")
        return {"results": rp.newest_first(rp.parse_auctions(done)), "upcoming": rp.soonest_first(rp.parse_auctions(upcoming)),
                "source": self.source}

    async def probe(self) -> None:
        await self.get_json(f"{BASE}/upcoming", {"format": "json"})
