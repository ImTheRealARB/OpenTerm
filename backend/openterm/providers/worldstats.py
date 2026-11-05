"""World statistics sources (ECST, WECO), both keyless: World Bank API v2 first, DBnomics (IMF WEO mirror) as the second source.

IMF WEO series on DBnomics include IMF projections for future years; the answer says so. IMF's own JSON API is not used (unreliable).
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..world import dbsearch, stats
from .base import Provider, ProviderError

WORLDSTATS = "worldstats"
WORLDSTATS_LATEST = "worldstats_latest"
WORLDSTATS_COUNTRIES = "worldstats_countries"
WORLDSTATS_DBN = "worldstats_dbn"
WORLDSTATS_SEARCH = "worldstats_search"  # DBSRCH: find DBnomics datasets and series by words
DBN_DATASET_PAGE = 20  # rows per page; scripts/record_dbsearch.py records fixtures with the same sizes
DBN_SERIES_PAGE = 30
WB = "https://api.worldbank.org/v2"
DBN = "https://api.db.nomics.world/v22"


class WorldBankProvider(Provider):
    name = "worldbank"
    label = "World Bank Open Data (API v2)"
    capabilities = frozenset({WORLDSTATS, WORLDSTATS_LATEST, WORLDSTATS_COUNTRIES})
    markets = "Annual country indicators (GDP, inflation, unemployment, population, debt, current account, trade)"
    terms = "Free API, no key. Data: The World Bank (CC BY 4.0). Annual, published with a lag of months to years; the data year is always shown."
    rate = (4.0, 8)
    timeout = 15.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def worldstats(self, iso3: str, ind: stats.Indicator) -> dict[str, Any]:
        body = await self.get_json(f"{WB}/country/{iso3}/indicator/{ind.wb}", {"format": "json", "per_page": 200})
        out = stats.parse_wb_series(body, ind, iso3)
        out["source"] = self.source
        return out

    async def worldstats_latest(self, countries: list[str], ind: stats.Indicator) -> dict[str, dict[str, Any]]:
        body = await self.get_json(f"{WB}/country/{';'.join(countries)}/indicator/{ind.wb}", {"format": "json", "mrnev": 1, "per_page": 100})
        return stats.parse_wb_latest(body)

    async def worldstats_countries(self, countries: list[str]) -> dict[str, str]:
        return stats.parse_wb_countries(await self.get_json(f"{WB}/country/{';'.join(countries)}", {"format": "json", "per_page": 100}))

    async def probe(self) -> None:
        await self.worldstats("USA", stats.INDICATORS["GDPG"])


class DbnomicsProvider(Provider):
    name = "dbnomics"
    label = "DBnomics (IMF, OECD, ECB, Eurostat mirror)"
    capabilities = frozenset({WORLDSTATS, WORLDSTATS_DBN, WORLDSTATS_SEARCH})
    markets = "IMF World Economic Outlook headline indicators for any country; any DBnomics series by DBN:<provider>/<dataset>/<series>"
    terms = "Free API, no key. Data stays under each provider's own licence (DBnomics aggregates; cite the original provider). IMF WEO includes projections."
    rate = (3.0, 6)
    timeout = 15.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def worldstats(self, iso3: str, ind: stats.Indicator) -> dict[str, Any]:
        if not ind.imf:
            raise ProviderError("unsupported", f"NO IMF WEO SERIES FOR {ind.alias}")
        body = await self.get_json(f"{DBN}/series/IMF/WEO:latest/{iso3}.{ind.imf}", {"observations": 1, "format": "json"})
        out = stats.parse_dbn_series(body, ind.label, ind.unit, ind.imf_scale, iso3, ind.alias)
        out["source"] = f"{self.source} · IMF WEO (INCLUDES IMF PROJECTIONS FOR FUTURE YEARS)"
        return out

    async def worldstats_dbn(self, provider: str, dataset: str, series: str) -> dict[str, Any]:
        body = await self.get_json(f"{DBN}/series/{provider}/{dataset}/{series}", {"observations": 1, "format": "json"})
        out = stats.parse_dbn_series(body, None, "", 1.0, series, "DBN")
        out["source"] = f"{self.source} · {provider}/{dataset}"
        return out

    async def search_datasets(self, q: str, offset: int = 0) -> dict[str, Any]:
        """DBSRCH step 1: datasets whose text matches every word of `q` (the API's own relevance order)."""
        body = await self.get_json(f"{DBN}/search", {"q": q, "limit": DBN_DATASET_PAGE, "offset": offset})
        return dbsearch.parse_datasets(body)

    async def search_series(self, provider: str, dataset: str, q: str = "", offset: int = 0) -> dict[str, Any]:
        """DBSRCH step 2: series of one dataset that match `q`. `observations=0&metadata=0` keeps the answer small (about 1 KB per series)."""
        params: dict[str, Any] = {"limit": DBN_SERIES_PAGE, "offset": offset, "observations": 0, "metadata": 0}
        if q:
            params["q"] = q
        body = await self.get_json(f"{DBN}/series/{provider}/{dataset}", params)
        return dbsearch.parse_series(body, provider, dataset)

    async def probe(self) -> None:
        await self.worldstats("USA", stats.INDICATORS["GDPG"])
