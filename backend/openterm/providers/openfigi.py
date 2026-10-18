"""OpenFIGI v3 mapping (SECF): ISIN / CUSIP / SEDOL / FIGI -> listings. Keyless; the unkeyed limit is 25 requests a minute and
10 jobs a request (the `ratelimit-*` headers of the answer say `25;w=60`), which this adapter obeys itself: a request the
bucket cannot cover is refused with `rate_limited` before anything is sent. A key would only raise those limits and is not used.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..secf.ids import ID_TYPES, Ident, parse_mapping
from .base import Provider, ProviderError

URL = "https://api.openfigi.com/v3/mapping"
FIGI = "figi"
JOBS_PER_REQUEST = 10


class OpenFigiProvider(Provider):
    name = "openfigi"
    label = "OpenFIGI identifier mapping"
    capabilities = frozenset({FIGI})
    markets = "Global: ISIN, CUSIP, SEDOL and FIGI to listings (ticker, exchange code, security type)"
    terms = "Free OpenFIGI API (Bloomberg-run, Open Symbology). Unkeyed limit 25 requests a minute, 10 identifiers a request."
    rate = (25 / 60, 25)
    max_wait = 0.0  # never sleep for a slot: say RATE LIMITED and let the user retry
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json", "User-Agent": "OpenTerm"}

    async def figi(self, idents: list[Ident]) -> dict[str, Any]:
        bad = [i.value for i in idents if not i.valid]
        if bad:
            raise ProviderError("unsupported", f"BAD CHECK DIGIT: {', '.join(bad[:3])}")
        items: list[dict[str, Any]] = []
        for start in range(0, len(idents), JOBS_PER_REQUEST):
            chunk = idents[start:start + JOBS_PER_REQUEST]
            body = [{"idType": ID_TYPES[i.kind], "idValue": i.value} for i in chunk]
            answer = await self.post_json(URL, body)
            if not isinstance(answer, list):
                raise ProviderError("unavailable", "OpenFIGI answered with something other than a list")
            items.extend(parse_mapping(chunk, answer))
        return {"items": items, "source": self.source}

    async def probe(self) -> None:
        await self.figi([Ident("ISIN", "US0378331005", True)])
