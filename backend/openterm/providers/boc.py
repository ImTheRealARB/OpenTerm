"""Bank of Canada Valet API (no key): Government of Canada benchmark bond yields (2, 3, 5, 7, 10 years) for `RATES CAD`."""

from __future__ import annotations

from typing import ClassVar

from ..rates import parse as rp
from .base import Provider, ProviderError
from .ecb import BROWSER_UA

URL = "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json"
CURVE_CAD = "curve_cad"


class BocProvider(Provider):
    name = "boc"
    label = "Bank of Canada Valet (public)"
    capabilities = frozenset({CURVE_CAD})
    markets = "Government of Canada benchmark bond yields: 2, 3, 5, 7 and 10 years (long-term and real return series are not curve points)"
    terms = "Public API, no key. Data: Bank of Canada (see bankofcanada.ca/terms). Daily, about one business day behind."
    rate = (2.0, 10)
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": BROWSER_UA, "Accept": "application/json"}

    async def curve_cad(self) -> dict:
        body = await self.get_json(URL, {"recent": "10"})
        try:
            return {"curve": rp.parse_boc(body), "source": self.source}
        except rp.RatesParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        await self.curve_cad()
