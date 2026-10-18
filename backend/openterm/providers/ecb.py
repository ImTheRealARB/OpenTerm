"""ECB Data Portal (SDMX, no key): the euro area AAA government spot curve, 3M to 30Y, for `RATES EUR`, `RATES NS EUR` and FXFA."""

from __future__ import annotations

from typing import ClassVar

from ..rates import parse as rp
from .base import Provider, ProviderError

BASE = "https://data-api.ecb.europa.eu/service/data/YC"
CURVE_EUR = "curve_eur"
TENORS = ("3M", "6M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y")
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


class EcbProvider(Provider):
    name = "ecb"
    label = "ECB Data Portal yield curve (public)"
    capabilities = frozenset({CURVE_EUR})
    markets = "Euro area AAA government spot yield curve (Svensson fit), 3M to 30Y, daily"
    terms = "Public SDMX API, no key. Data: European Central Bank (reuse with attribution). An estimated curve, not traded yields."
    rate = (2.0, 10)
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": BROWSER_UA, "Accept": "application/json"}

    async def curve_eur(self) -> dict:
        key = "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_" + "+SR_".join(TENORS)
        body = await self.get_json(f"{BASE}/{key}", {"lastNObservations": "10", "format": "jsondata"})
        try:
            return {"curve": rp.parse_ecb(body), "source": self.source}
        except rp.RatesParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        await self.curve_eur()
