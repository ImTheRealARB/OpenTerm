"""UK Companies House (free key, read-only): company search, profile, officers and filing history for the UK register.

Capability `companies_house`. The key (COMPANIES_HOUSE_KEY, made in the Companies House developer hub for a "REST" application) is sent as
HTTP basic auth: the key is the user name and the password is empty (`Authorization: Basic base64("<key>:")`). It never goes in a URL.
Limit: 600 requests per application per 5 minutes (HTTP 429 once it is used up, until the window ends): this adapter paces itself
at 2 requests a second and a company view costs 3 requests (profile, officers, filings).

With no key `supports()` stays true and every call raises `key_required` BEFORE any network call, so UKCO answers
`KEY REQUIRED: set COMPANIES_HOUSE_KEY in APIKEYS` instead of looking broken. A key Companies House refuses (401 / 403) says the same.

Built from the official resource pages, NOT from recordings (doc-shaped fixtures; see companies_house_parse.py).
"""

from __future__ import annotations

import base64
from typing import Any, ClassVar

import httpx

from ..ratelimit import RateLimited
from ..redact import redact
from . import companies_house_parse as chp
from .base import Provider, ProviderError

BASE = "https://api.company-information.service.gov.uk"
CAPABILITY = "companies_house"
OFFICERS_PER_PAGE = 50
FILINGS_PER_PAGE = 25
SEARCH_PER_PAGE = 20


class CompaniesHouseProvider(Provider):
    name = "companies_house"
    label = "UK Companies House (free key)"
    capabilities = frozenset({CAPABILITY})
    markets = "UK register of companies: profile, officers, filing history, search"
    terms = "Free key (COMPANIES_HOUSE_KEY), 600 requests per 5 minutes. Register data as filed by each company."
    rate = (2.0, 10)
    max_wait = 3.0
    timeout = 10.0
    key_name = "COMPANIES_HOUSE_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.source = "companies house (doc-shaped fixture, NOT A RECORDING)" if self.fixtures else "companies house"
        self._key = ""

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def set_keys(self, values: dict[str, str] | None) -> None:
        self._key = (values or {}).get("COMPANIES_HOUSE_KEY", "")

    async def _api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._key:
            raise ProviderError("key_required", "COMPANIES_HOUSE_KEY is not set")
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        auth = base64.b64encode(f"{self._key}:".encode()).decode("ascii")
        try:
            r = await self.http.get(f"{BASE}{path}", params=params, timeout=self.timeout,
                                    headers={**self.headers, "Authorization": f"Basic {auth}"})
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        if r.status_code == 404:
            raise ProviderError("not_found", "NO SUCH COMPANY")
        if r.status_code == 429:
            raise ProviderError("rate_limited", "COMPANIES HOUSE 429: 600 REQUESTS PER 5 MINUTES USED, WAIT FOR THE WINDOW TO END")
        if r.status_code in (401, 403):
            raise ProviderError("key_required", redact(f"Companies House refused the key ({r.status_code})", [self._key]))
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError("unavailable", "non-JSON response") from e

    async def ch_search(self, query: str) -> dict:
        out = chp.search(await self._api("/search/companies", {"q": query, "items_per_page": SEARCH_PER_PAGE}))
        if not out["items"]:
            raise ProviderError("not_found", "NO COMPANY MATCHES")
        return {**out, "source": self.source}

    async def ch_company(self, number: str) -> dict:
        """Profile (required) plus officers and filings. A section that fails after the profile worked is left empty and says why."""
        out = chp.profile(await self._api(f"/company/{number}"))
        notes: list[str] = []
        sections: dict[str, Any] = {}
        for key, path, params, parse in (
            ("officers", f"/company/{number}/officers", {"items_per_page": OFFICERS_PER_PAGE}, chp.officers),
            ("filings", f"/company/{number}/filing-history", {"items_per_page": FILINGS_PER_PAGE}, chp.filings),
        ):
            try:
                sections[key] = parse(await self._api(path, params))
            except ProviderError as e:
                if e.kind == "key_required":  # the key went bad between calls: say so for the whole view
                    raise
                sections[key] = None
                why = "NONE PUBLISHED FOR THIS COMPANY" if e.kind == "not_found" else redact(str(e), [self._key])
                notes.append(f"{key.upper()} NOT LOADED: {why}")
        return {"profile": out, **sections, "notes": notes, "source": self.source}
