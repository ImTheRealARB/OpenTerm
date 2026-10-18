"""Current policy rates for CENB from four keyless sources (FRED CSV for the Fed, ECB data portal, Bank of England IADB, Bank of Canada Valet).

One bank failing does not fail the others: its entry carries `error` and the panel shows the reason. All four failing is `unavailable`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from ..world import cenb
from .base import Provider, ProviderError
from .boe import MONTHS
from .boe import URL as BOE_URL
from .ecb import BROWSER_UA

POLICY_RATES = "policy_rates"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ECB_URL = "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.MRR_FR.LEV"
BOC_URL = "https://www.bankofcanada.ca/valet/observations/V39079/json"


class PolicyRatesProvider(Provider):
    name = "policy_rates"
    label = "Central bank policy rates (FRED, ECB, BoE, BoC)"
    capabilities = frozenset({POLICY_RATES})
    markets = "Fed target upper bound, ECB main refinancing rate, Bank of England Bank Rate, Bank of Canada overnight target"
    terms = "Public data, no key. Sources: FRED (St. Louis Fed), ECB data portal, Bank of England database, Bank of Canada Valet."
    rate = (2.0, 8)
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": BROWSER_UA, "Accept": "*/*"}

    async def _one(self, bank: str) -> dict[str, Any]:
        if bank == "FED":
            d, v = cenb.parse_fred_csv_last((await self.get_bytes(FRED_CSV, {"id": "DFEDTARU"})).decode("utf-8", "replace"))
        elif bank == "ECB":
            d, v = cenb.parse_ecb_last(await self.get_json(ECB_URL, {"format": "jsondata", "lastNObservations": 1}))
        elif bank == "BOC":
            d, v = cenb.parse_boc_last(await self.get_json(BOC_URL, {"recent": 1}))
        else:
            today = datetime.now(UTC).date()
            frm = today - timedelta(days=30)
            params = {"csv.x": "yes", "Datefrom": f"{frm.day:02d}/{MONTHS[frm.month - 1]}/{frm.year}", "Dateto": f"{today.day:02d}/{MONTHS[today.month - 1]}/{today.year}",
                      "SeriesCodes": "IUDBEDR", "CSVF": "TN", "UsingCodes": "Y"}
            d, v = cenb.parse_boe_last((await self.get_bytes(BOE_URL, params)).decode("utf-8-sig", "replace"))
        return {"rate": v, "as_of": d}

    async def policy_rates(self) -> dict[str, dict[str, Any]]:
        banks = list(cenb.RATE_SOURCES)
        got = await asyncio.gather(*(self._one(b) for b in banks), return_exceptions=True)
        out: dict[str, dict[str, Any]] = {}
        for b, g in zip(banks, got, strict=True):
            if isinstance(g, ProviderError):
                out[b] = {"error": f"{g.kind.upper()}: {g}"[:120]}
            elif isinstance(g, BaseException):
                raise g
            else:
                out[b] = g
        if all("error" in v for v in out.values()):
            raise ProviderError("unavailable", "NO POLICY RATE SOURCE ANSWERED")
        return out

    async def probe(self) -> None:
        await self.policy_rates()


def today_utc() -> date:
    return datetime.now(UTC).date()
