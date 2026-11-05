"""MFapi.in (keyless): Indian mutual fund search and daily NAV history, for the MF panel.

MFapi.in is a free community service that republishes the NAV (net asset value per unit) AMFI collects from the fund houses. It is not an official
AMFI API and may lag AMFI by a day, so every payload names it as the source. We only use two of its endpoints, never `GET /mf` (the whole
list of about 40,000 schemes): a search per query and one fund's history per open, both cached by the service layer. Shapes are documented
in `world/mfund.py`, which also holds the parsing; this file only fetches and maps parse failures to `ProviderError`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..world import mfund
from .base import Provider, ProviderError

MF_SEARCH = "mf_search"
MF_NAV = "mf_nav"
BASE = "https://api.mfapi.in/mf"


class MfapiProvider(Provider):
    name = "mfapi"
    label = "MFapi.in (Indian mutual fund NAV history)"
    capabilities = frozenset({MF_SEARCH, MF_NAV})
    markets = "Indian mutual funds: scheme search by name and the full daily NAV history of one scheme (about 14 years for older funds)"
    terms = ("Free community service, no key (mfapi.in). Data comes from AMFI but this is NOT an official AMFI API and can lag a day. "
             "End-of-day NAV per unit, not a market price.")
    rate = (2.0, 4)  # a few calls a second is plenty for a human typing commands, and gentle for a free service
    max_wait = 2.0
    timeout = 30.0  # one fund's full history is about 130 KB; the service answers in well under a second, this is the safety net
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def mf_search(self, query: str) -> list[dict[str, Any]]:
        """Schemes whose name contains every word of `query`, as `[{code, name}]` in the service's own order."""
        body = await self.get_json(f"{BASE}/search", {"q": query})
        try:
            return mfund.parse_search(body)
        except mfund.MfundError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def mf_nav(self, code: int) -> dict[str, Any] | None:
        """One scheme with its whole NAV history (ascending), or None when the service does not know the code."""
        body = await self.get_json(f"{BASE}/{int(code)}")
        try:
            return mfund.parse_fund(body)
        except mfund.MfundError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        """Cheap liveness check: the one-row `latest` answer of a long-lived scheme (Parag Parikh Flexi Cap Direct)."""
        body = await self.get_json(f"{BASE}/122639/latest")
        if not isinstance(body, dict) or not body.get("data"):
            raise ProviderError("unavailable", "MFAPI LATEST HAS NO NAV ROW")
