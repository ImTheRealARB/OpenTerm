"""Four free, read-only, keyed data sources: UN Comtrade (trade by product), BLS (US jobs and prices), BEA (US GDP, trade, industry),
US Census (retail sales, goods trade). One thin adapter each; the parsing is pure code in `world/` (comtrade, bls, bea, census).

Unlike Finnhub, these adapters hold no key. The key is read from the key store (`app.state.keys`) when a request arrives and passed
into the method, so a key saved in APIKEYS works at once with no restart (docs/ADDING_A_PROVIDER.md, "Keyed providers" rule 2).
A request without a key never gets here: the service raises KEY REQUIRED first. A key the source refuses becomes
ProviderError("key_required"), which the router does not count against health.

Where the key travels (the sources decide, not us): Comtrade in a header, BLS in the JSON body, BEA and Census in the query string.
The key store registers every key with `redact`, so logs and error text mask it; every text from upstream is redacted again here.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import orjson

from ..ratelimit import RateLimited
from ..redact import redact
from .base import Provider, ProviderError

COMTRADE = "comtrade"
BLS = "bls"
BEA = "bea"
CENSUS = "census"


class _KeyedHost(Provider):
    key_name = ""
    host_label = ""
    rate = (1.0, 3)
    max_wait = 3.0
    timeout = 20.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}

    async def _send(self, method: str, url: str, key: str, *, params: dict[str, Any] | None = None,
                    headers: dict[str, str] | None = None, body: Any = None) -> Any:
        """One call. Returns the parsed JSON. The key is only ever used to build the request and to redact error text."""
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        try:
            r = await self.http.request(method, url, params=params, headers={**self.headers, **(headers or {})}, json=body,
                                        timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        if r.status_code in (401, 403):
            raise ProviderError("key_required", redact(f"{self.host_label} refused the key ({r.status_code})", [key]))
        if r.status_code == 429:
            raise ProviderError("rate_limited", f"429 from {self.host_label} (daily or per-minute quota)")
        if r.status_code in (204, 404):
            raise ProviderError("not_found", f"{self.host_label}: no data ({r.status_code})")
        if r.status_code >= 400:
            raise ProviderError("unavailable", redact(f"HTTP {r.status_code}: {r.text[:120]}", [key]))
        try:
            return orjson.loads(r.content)
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", redact(f"{self.host_label}: answer is not JSON ({r.text[:60]!r})", [key])) from e

    def _wrap(self, body: Any) -> dict[str, Any]:
        return {"body": body, "source": self.source}


class ComtradeProvider(_KeyedHost):
    name = "comtrade"
    label = "UN Comtrade (free key)"
    capabilities = frozenset({COMTRADE})
    markets = "Trade flows between any two countries by HS product, annual, as each country reports them"
    terms = "Free key (UN_COMTRADE_KEY): 500 calls a day, 100,000 records a call. Data: UN Statistics Division."
    key_name = "UN_COMTRADE_KEY"
    host_label = "UN Comtrade"
    rate = (0.5, 2)

    async def comtrade(self, key: str, url: str, params: dict[str, str]) -> dict[str, Any]:
        return self._wrap(await self._send("GET", url, key, params=params, headers={"Ocp-Apim-Subscription-Key": key}))


class BlsProvider(_KeyedHost):
    name = "bls"
    label = "BLS Public Data API v2 (free key)"
    capabilities = frozenset({BLS})
    markets = "US CPI, PPI, jobs, wages, job openings (series ids from the BLS)"
    terms = "Free key (BLS_API_KEY): 500 queries a day, 50 series a query. Data: US Bureau of Labor Statistics."
    key_name = "BLS_API_KEY"
    host_label = "BLS"

    async def bls(self, key: str, url: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._wrap(await self._send("POST", url, key, body=body))


class BeaProvider(_KeyedHost):
    name = "bea"
    label = "BEA data API (free key)"
    capabilities = frozenset({BEA})
    markets = "US GDP and consumption (NIPA), trade balances (ITA), value added by industry"
    terms = "Free key (BEA_API_KEY, a UserID). Data: US Bureau of Economic Analysis."
    key_name = "BEA_API_KEY"
    host_label = "BEA"

    async def bea(self, key: str, url: str, params: dict[str, str]) -> dict[str, Any]:
        return self._wrap(await self._send("GET", url, key, params=params))


class CensusProvider(_KeyedHost):
    name = "census"
    label = "US Census API (free key)"
    capabilities = frozenset({CENSUS})
    markets = "US monthly retail sales; US goods exports and imports by country and HS chapter"
    terms = "Free key (CENSUS_API_KEY). Data: US Census Bureau."
    key_name = "CENSUS_API_KEY"
    host_label = "Census"
    rate = (2.0, 5)

    async def census(self, key: str, url: str, params: dict[str, str]) -> dict[str, Any]:
        return self._wrap(await self._send("GET", url, key, params=params))
