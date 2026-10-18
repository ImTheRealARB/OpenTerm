"""Japan Ministry of Finance JGB interest rates (daily CSV, no key): 1Y to 40Y for `RATES JPY` and the 1Y leg of FXFA."""

from __future__ import annotations

from typing import ClassVar

from ..rates import parse as rp
from .base import Provider, ProviderError
from .ecb import BROWSER_UA

URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
CURVE_JPY = "curve_jpy"


class MofProvider(Provider):
    name = "mof"
    label = "Japan MoF JGB interest rates (public)"
    capabilities = frozenset({CURVE_JPY})
    markets = "Japanese government bond yields, 1Y to 40Y, daily (the whole history file is downloaded; the newest 40 days are kept)"
    terms = "Public CSV download, no key. Data: Ministry of Finance Japan. Published each Tokyo business day, about one day behind."
    rate = (1.0, 5)
    timeout = 25.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": BROWSER_UA, "Accept": "text/csv,*/*"}

    async def curve_jpy(self) -> dict:
        text = (await self.get_bytes(URL)).decode("utf-8-sig", "replace")
        try:
            return {"curve": rp.parse_mof(text), "source": self.source}
        except rp.RatesParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        await self.curve_jpy()
