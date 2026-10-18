"""FRED credit spreads (ICE BofA option-adjusted spreads) from the keyless fredgraph.csv, for `RATES SPRD`.
FRED hangs on a browser User-Agent, so this adapter sends a plain client one (like fred_csv)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from ..rates import parse as rp
from ..rates.tables import OAS_NAMES
from .base import Provider, ProviderError

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CREDIT_SPREADS = "credit_spreads"
KEEP_DAYS = 430   # one year of window plus the 21-observation change


class FredOasProvider(Provider):
    name = "fred_oas"
    label = "FRED credit spreads, ICE BofA OAS (keyless CSV)"
    capabilities = frozenset({CREDIT_SPREADS})
    markets = "US investment grade, high yield, BBB, BB and CCC option-adjusted spreads (last three years only: FRED's ICE licence)"
    terms = "Public download, no key. Data: ICE Data Indices via FRED, Federal Reserve Bank of St. Louis; cite both."
    rate = (3.0, 20)
    max_wait = 4.0
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/1.0 (personal research)", "Accept": "text/csv,*/*"}

    async def _one(self, sid: str, cosd: str) -> tuple[str, list[tuple[str, float]]]:
        text = (await self.get_bytes(FRED_CSV, {"id": sid, "cosd": cosd})).decode("utf-8", "replace")
        try:
            return sid, rp.parse_oas_csv(text, sid)
        except rp.RatesParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def credit_spreads(self) -> dict:
        cosd = (datetime.now(UTC).date() - timedelta(days=KEEP_DAYS)).isoformat()
        results = await asyncio.gather(*(self._one(sid, cosd) for sid in OAS_NAMES), return_exceptions=True)
        series: dict[str, list[tuple[str, float]]] = {}
        failed: list[str] = []
        for sid, r in zip(OAS_NAMES, results, strict=True):
            if isinstance(r, ProviderError):
                failed.append(f"{sid} ({r.kind})")
            elif isinstance(r, BaseException):
                raise r
            else:
                series[sid] = r[1]
        if not series:
            raise ProviderError("unavailable", "no OAS series answered: " + ", ".join(failed))
        return {"series": series, "failed": failed, "source": self.source}

    async def probe(self) -> None:
        await self._one("BAMLC0A0CM", (datetime.now(UTC).date() - timedelta(days=10)).isoformat())
