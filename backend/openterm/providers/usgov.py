"""US government data adapters: USASpending and the Federal Register (no key), OpenFEC and Congress.gov (free api.data.gov key).

Four small providers in one file because they share the same job: fetch JSON, map HTTP trouble to `ProviderError`, hand the body to the pure parser in
`world/` (`usaspending.py`, `fedreg.py`, `fec.py`, `congress.py`). They only fetch; the shapes and the maths are documented next to the parsers.

Capabilities: `usaspending`, `federal_register`, `openfec`, `congress_gov`.

The keyed pair (FEC_API_KEY, CONGRESS_API_KEY) both come from https://api.data.gov/signup/. The key is sent in the `X-Api-Key` header, never in the URL
(a URL ends up in logs and error text). With no key `supports()` stays true and every call raises `key_required` BEFORE any network call, so the panel
says `KEY REQUIRED: set FEC_API_KEY in APIKEYS` instead of looking broken; a key the gateway refuses (HTTP 403 API_KEY_INVALID) says the same.
Checked live on 2026-11-05: the gateway answers 403 `API_KEY_MISSING` for no key and 403 `API_KEY_INVALID` for a made-up key sent in `X-Api-Key`.
Success shapes of FEC and Congress.gov are DOC-SHAPED (no key was available); USASpending and the Federal Register were run live.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import httpx

from ..ratelimit import RateLimited
from ..redact import redact
from ..world import congress, fec, fedreg, usaspending
from ..world.usgov import UsGovError
from .base import Provider, ProviderError

USASPENDING_BASE = "https://api.usaspending.gov/api/v2/search"
FEDREG_URL = "https://www.federalregister.gov/api/v1/documents.json"
FEC_BASE = "https://api.open.fec.gov/v1"
CONGRESS_BASE = "https://api.congress.gov/v3"
UA = {"User-Agent": "OpenTerm (open-source terminal)", "Accept": "application/json"}


def _wrap(fn):
    """Run a pure parser; a shape the docs do not promise becomes `unavailable` (the panel shows ERR and the reason), never an empty table."""
    try:
        return fn()
    except UsGovError as e:
        raise ProviderError("unavailable", str(e)) from e


class UsaSpendingProvider(Provider):
    name = "usaspending"
    label = "USASpending.gov (US federal awards, keyless)"
    capabilities = frozenset({"usaspending"})
    markets = "US federal contracts, grants and other awards: top recipients, largest awards, top awarding agencies (obligations in USD)"
    terms = "Public US government data, no key. Amounts are obligations (commitments), self-reported by agencies; dates before 2007-10-01 are not searchable."
    rate = (1.0, 3)  # gentle: each keyword view makes two POSTs
    max_wait = 3.0
    timeout = 60.0  # the recipient and award searches can take several seconds on a wide keyword
    headers: ClassVar[dict[str, str]] = {**UA, "Content-Type": "application/json"}

    async def usasp_keyword(self, text: str, window: dict[str, str]) -> dict[str, Any]:
        """Top recipients (required) plus the largest awards. If the awards call fails after the recipients worked, `awards` is None and a note says why."""
        body = await self.post_json(f"{USASPENDING_BASE}/spending_by_category/recipient/", usaspending.recipient_body(window, text))
        recipients = _wrap(lambda: usaspending.parse_recipients(body))
        notes: list[str] = []
        awards: list[dict] | None
        try:
            ab = await self.post_json(f"{USASPENDING_BASE}/spending_by_award/", usaspending.awards_body(window, text))
            awards = _wrap(lambda: usaspending.parse_awards(ab))
        except ProviderError as e:
            awards = None
            notes.append(f"AWARDS NOT LOADED: {redact(str(e))}")
        return {"recipients": recipients, "awards": awards, "notes": notes}

    async def usasp_agencies(self, window: dict[str, str]) -> list[dict]:
        body = await self.post_json(f"{USASPENDING_BASE}/spending_by_category/awarding_agency/", usaspending.agency_body(window))
        return _wrap(lambda: usaspending.parse_agencies(body))

    async def usasp_agency_recipients(self, agency: str, window: dict[str, str]) -> list[dict]:
        body = await self.post_json(f"{USASPENDING_BASE}/spending_by_category/recipient/", usaspending.recipient_in_agency_body(window, agency))
        return _wrap(lambda: usaspending.parse_recipients(body))

    async def probe(self) -> None:
        """Liveness: the cheapest documented call (one agency)."""
        today = date.today()
        body = await self.post_json(f"{USASPENDING_BASE}/spending_by_category/awarding_agency/",
                                    {**usaspending.agency_body(usaspending.fiscal_window(today, 1)), "limit": 1})
        _wrap(lambda: usaspending.parse_agencies(body))


class FederalRegisterProvider(Provider):
    name = "federalregister"
    label = "Federal Register (US rules and notices, keyless)"
    capabilities = frozenset({"federal_register"})
    markets = "US Federal Register: final rules, proposed rules, notices and presidential documents, newest first"
    terms = "Public US government data, no key. Documents as published; the abstract is the agency's own summary."
    rate = (2.0, 4)
    max_wait = 2.0
    timeout = 30.0
    headers: ClassVar[dict[str, str]] = UA

    async def fedreg_search(self, type_code: str | None, words: str) -> dict[str, Any]:
        body = await self.get_json(FEDREG_URL, fedreg.params(type_code, words))  # a list of pairs: the API wants repeated `fields[]` keys
        return _wrap(lambda: fedreg.parse(body, type_code, words))

    async def probe(self) -> None:
        out = await self.fedreg_search(None, "")
        if not out["items"]:
            raise ProviderError("unavailable", "FEDERAL REGISTER RETURNED NO DOCUMENTS")


class _DataGovProvider(Provider):
    """An api.data.gov keyed API: key in the `X-Api-Key` header, `key_required` before any network call when it is missing."""

    key_name = ""
    base = ""
    timeout = 20.0
    rate = (2.0, 6)
    max_wait = 3.0
    headers: ClassVar[dict[str, str]] = UA
    fixture_label = ""

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        self.fixtures = (source or "").endswith(":fixture")
        self.source = f"{self.fixture_label} (doc-shaped fixture, NOT A RECORDING)" if self.fixtures else self.fixture_label
        self._key = ""

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def set_keys(self, values: dict[str, str] | None) -> None:
        self._key = (values or {}).get(self.key_name, "")

    async def _api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._key:
            raise ProviderError("key_required", f"{self.key_name} is not set")
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        try:
            r = await self.http.get(f"{self.base}{path}", params=params, timeout=self.timeout, headers={**self.headers, "X-Api-Key": self._key})
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        if r.status_code == 404:
            raise ProviderError("not_found", "404")
        if r.status_code == 429:
            raise ProviderError("rate_limited", f"{self.label}: 429 OVER_RATE_LIMIT, WAIT AND RETRY (THE LIMIT IS PER KEY PER HOUR)")
        if r.status_code in (401, 403):
            raise ProviderError("key_required", redact(f"api.data.gov refused the key ({r.status_code})", [self._key]))
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError("unavailable", "non-JSON response") from e


class OpenFecProvider(_DataGovProvider):
    name = "openfec"
    label = "OpenFEC (US campaign finance, free key)"
    capabilities = frozenset({"openfec"})
    markets = "US federal campaign finance: candidates, committees and their receipts / disbursements by 2-year cycle"
    terms = "Free key (FEC_API_KEY from api.data.gov), 1,000 calls per hour per key. Figures as reported to the FEC on filings."
    key_name = "FEC_API_KEY"
    base = FEC_BASE
    fixture_label = "openfec"

    async def fec_search(self, text: str) -> dict[str, Any]:
        """Candidates and committees whose name matches. One kind failing (not the key) leaves the other and a note; both failing raises."""
        out: dict[str, Any] = {"candidates": [], "committees": [], "notes": []}
        errors: list[ProviderError] = []
        for key, path, parse in (("candidates", "/candidates/search/", fec.parse_candidates), ("committees", "/committees/", fec.parse_committees)):
            try:
                body = await self._api(path, {"q": text, "per_page": fec.SEARCH_LIMIT})
                out[key] = _wrap(lambda parse=parse, body=body: parse(body))
            except ProviderError as e:
                if e.kind == "key_required":  # a bad key fails the whole view, not one half of it
                    raise
                errors.append(e)
                out["notes"].append(f"{key.upper()} NOT LOADED: {redact(str(e), [self._key])}")
        if len(errors) == 2:
            raise errors[0]
        return out

    async def fec_entity(self, kind: str, ident: str) -> dict[str, Any]:
        """Name plus the newest cycles' totals of one candidate or committee. An id the FEC does not know is `not_found`."""
        seg = "candidate" if kind == "CANDIDATE" else "committee"
        head = await self._api(f"/{seg}/{ident}/")
        name = _wrap(lambda: fec.parse_name(head))
        if name is None:
            raise ProviderError("not_found", f"NO {seg.upper()} WITH ID {ident}")
        totals = await self._api(f"/{seg}/{ident}/totals/", {"sort": "-cycle", "per_page": fec.CYCLES_SHOWN})
        return {"name": name, "cycles": _wrap(lambda: fec.parse_totals(totals))}


class CongressProvider(_DataGovProvider):
    name = "congressgov"
    label = "Congress.gov API (US bills, free key)"
    capabilities = frozenset({"congress_gov"})
    markets = "US Congress bills: the most recently updated bills and one bill's sponsor and latest action"
    terms = "Free key (CONGRESS_API_KEY from api.data.gov), 5,000 calls per hour per key. Library of Congress data."
    key_name = "CONGRESS_API_KEY"
    base = CONGRESS_BASE
    fixture_label = "congress.gov"

    async def cg_list(self, limit: int) -> list[dict]:
        """The `limit` most recently updated bills (the list carries no sponsor)."""
        body = await self._api("/bill", congress.list_params(limit))
        return _wrap(lambda: congress.parse_list(body))

    async def cg_bill(self, session: int, typ: str, number: int) -> dict:
        """One bill with its sponsor. `session` is the Congress number (119 = 2025-2026). An unknown bill is `not_found`."""
        body = await self._api(f"/bill/{session}/{typ.lower()}/{number}", {"format": "json"})
        return _wrap(lambda: congress.parse_bill(body))
