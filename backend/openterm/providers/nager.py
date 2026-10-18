"""Nager.Date public holidays (keyless). Used for the market lights of London, Tokyo, Hong Kong and India (labelled PUBLIC HOLIDAYS: an exchange can differ).

Nager answers 204 (no body) for a country it has no data for (India in 2026): that is `not_found`, never an empty calendar.
"""

from __future__ import annotations

from typing import Any, ClassVar

import orjson

from .base import Provider, ProviderError

HOLIDAYS = "holidays"
URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{cc}"


class NagerProvider(Provider):
    name = "nager"
    label = "Nager.Date public holidays"
    capabilities = frozenset({HOLIDAYS})
    markets = "Public holidays for about 100 countries (not exchange calendars)"
    terms = "Free public API, no key (date.nager.at)."
    rate = (2.0, 6)
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def holidays(self, cc: str, year: int) -> Any:
        r = await self._request(URL.format(year=year, cc=cc), None, None)
        if r.status_code == 204 or not r.content:
            raise ProviderError("not_found", f"NO HOLIDAY DATA FROM NAGER FOR {cc} {year}")
        try:
            return orjson.loads(r.content)
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", "non-JSON response") from e

    async def probe(self) -> None:
        await self.holidays("GB", 2026)
