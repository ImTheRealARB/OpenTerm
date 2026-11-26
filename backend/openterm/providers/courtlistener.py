"""CourtListener (Free Law Project): federal court dockets from the RECAP archive, for LEGAL.

Capability `court_dockets`. A free account makes a token (https://www.courtlistener.com/help/api/rest/); it is sent as `Authorization: Token <key>`
and never in the URL. Without a key `supports()` stays true and a call raises `key_required` BEFORE any network call, so LEGAL shows
`KEY REQUIRED: set COURTLISTENER_API_KEY in APIKEYS` for the court section while its SEC section still answers.

DOC-SHAPED: written from the API v4 docs on 2026-11-24 and never run against a live key (the fixtures are `courtlistener_*_docshape`, labelled NOT A
RECORDING). The first real key should be used to record a fixture and check the `q` syntax and the field names in `filings/legal.parse_dockets`.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..filings import legal as L
from .base import ProviderError
from .keyed import KeyedProvider

BASE = "https://www.courtlistener.com/api/rest/v4"
CAPABILITY = "court_dockets"


class CourtListenerProvider(KeyedProvider):
    name = "courtlistener"
    label = "CourtListener court dockets (free key)"
    capabilities = frozenset({CAPABILITY})
    markets = "US federal court dockets (RECAP archive): case name, court, filing date, docket number"
    terms = "Free key (COURTLISTENER_API_KEY). Free Law Project; rate limits apply per account. Court records as filed, not checked by OpenTerm."
    rate = (1.0, 5)
    max_wait = 3.0
    timeout = 15.0
    key_name = "COURTLISTENER_API_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}
    hide_without_key = False  # supports() stays true: a missing key answers KEY REQUIRED instead of looking broken
    msg_rate_limited = "COURTLISTENER 429: SLOW DOWN, THE FREE KEY HAS A RATE LIMIT"
    msg_refused = "CourtListener refused the key ({code})"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        self.source = "courtlistener (doc-shaped fixture, NOT A RECORDING)" if self.fixture else "courtlistener"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self._key}"}

    async def dockets(self, company: str) -> dict[str, Any]:
        """RECAP dockets whose case name contains the company's core name, newest first (the caller still filters by name)."""
        core = L.core_name(company)
        body = await self.get_json(f"{BASE}/search/", {"q": f'caseName:"{core}"', "type": "r", "order_by": "dateFiled desc"})
        try:
            rows = L.parse_dockets(body)
        except ValueError as e:
            raise ProviderError("unavailable", str(e)) from e
        return {"dockets": rows, "source": self.source, "as_of": self.now()}

    async def probe(self) -> None:
        await self.get_json(f"{BASE}/courts/", {"page_size": "1"})
