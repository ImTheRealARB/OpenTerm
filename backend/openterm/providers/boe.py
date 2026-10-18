"""Bank of England Interactive Database (plain CSV GET, no key): nominal par yields at 5, 10 and 20 years for `RATES GBP`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

from ..rates import parse as rp
from .base import Provider, ProviderError
from .ecb import BROWSER_UA

URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
CURVE_GBP = "curve_gbp"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def iadb_date(d: date) -> str:
    """The database wants DD/Mon/YYYY."""
    return f"{d.day:02d}/{MONTHS[d.month - 1]}/{d.year}"


class BoeProvider(Provider):
    name = "boe"
    label = "Bank of England yield data (public)"
    capabilities = frozenset({CURVE_GBP})
    markets = "UK gilt nominal par yields at 5, 10 and 20 years only (the free CSV series), daily"
    terms = "Public database download, no key. Data: Bank of England (cite the source). Only three maturities are offered keyless."
    rate = (1.0, 5)
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": BROWSER_UA, "Accept": "text/csv,*/*"}

    async def curve_gbp(self) -> dict:
        today = datetime.now(UTC).date()
        params = {"csv.x": "yes", "Datefrom": iadb_date(today - timedelta(days=45)), "Dateto": iadb_date(today),
                  "SeriesCodes": ",".join(rp.BOE_SERIES), "CSVF": "TN", "UsingCodes": "Y"}
        text = (await self.get_bytes(URL, params)).decode("utf-8-sig", "replace")
        try:
            return {"curve": rp.parse_boe(text), "source": self.source}
        except rp.RatesParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        await self.curve_gbp()
