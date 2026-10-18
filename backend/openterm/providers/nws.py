"""US National Weather Service active alerts (api.weather.gov, keyless). NWS requires a User-Agent that names a contact: it is
taken from SEC_USER_AGENT (the same setting SEC EDGAR uses; never written into the repo). Without it the adapter raises
`key_required` and WETR labels the alerts SKIPPED instead of sending an anonymous agent."""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..world import weather
from .base import Provider, ProviderError

ALERTS = "nws_alerts"
URL = "https://api.weather.gov/alerts/active"
NEEDS_UA = "SET SEC_USER_AGENT IN .ENV (NAME AND CONTACT): WEATHER.GOV REQUIRES A USER-AGENT THAT NAMES A CONTACT"


class NwsProvider(Provider):
    name = "nws"
    label = "NWS active alerts (weather.gov)"
    capabilities = frozenset({ALERTS})
    markets = "US weather alerts by point or state (warnings, watches, advisories)"
    terms = "US government data, no key. Needs a User-Agent with contact info (SEC_USER_AGENT)."
    rate = (1.0, 3)
    timeout = 10.0

    async def nws_alerts(self, lat: float, lon: float) -> list[dict[str, Any]]:
        ua = (get_settings().sec_user_agent or "").strip()
        if not ua:
            raise ProviderError("key_required", NEEDS_UA)
        self.headers = {"User-Agent": ua, "Accept": "application/geo+json"}
        return weather.parse_alerts(await self.get_json(URL, {"point": f"{lat:.4f},{lon:.4f}"}))

    async def probe(self) -> None:
        if not (get_settings().sec_user_agent or "").strip():
            raise ProviderError("key_required", NEEDS_UA)
        await self.nws_alerts(29.76, -95.37)
