"""FINRA Reg SHO daily short sale volume files (SI): one pipe-delimited text file per trading day on cdn.finra.org.

Each file is ~550 KB for all US symbols. A parsed day is kept in memory (12 days), so a second symbol costs no download.
A weekday with no file (holiday, or the file is not published yet) is a 404 and is skipped; only the newest `DAYS` found
days are returned. FINRA publishes the consolidated file after the close, so "today" usually has none.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta

from ..research.corp_parse import parse_short_volume
from ..symbols import is_us_plain
from .base import Provider, ProviderError

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{}.txt"
SHORT_VOLUME = "short_volume"


class FinraProvider(Provider):
    name = "finra"
    label = "FINRA Reg SHO daily short volume"
    capabilities = frozenset({SHORT_VOLUME})
    markets = "US-listed stocks and ETFs: daily short sale volume (consolidated NMS), plain tickers"
    terms = "Public FINRA data files. Short sale volume is not short interest."
    rate = (6.0, 12)
    max_wait = 5.0
    timeout = 20.0
    DAYS = 10
    LOOKBACK_DAYS = 21
    KEEP = 12

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._days: OrderedDict[str, dict[str, tuple[float, float, float]]] = OrderedDict()

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and (symbol is None or is_us_plain(symbol))

    def today(self) -> date:
        return datetime.now(UTC).date()

    async def _day(self, d: date) -> dict[str, tuple[float, float, float]] | None:
        key = d.strftime("%Y%m%d")
        if key in self._days:
            self._days.move_to_end(key)
            return self._days[key]
        try:
            r = await self._request(URL.format(key), None, None)
        except ProviderError as e:
            if e.kind == "not_found":
                return None
            raise
        parsed = parse_short_volume(r.text)
        self._days[key] = parsed
        while len(self._days) > self.KEEP:
            self._days.popitem(last=False)
        return parsed

    async def short_volume(self, symbol: str) -> dict:
        today = self.today()
        days = [today - timedelta(days=i) for i in range(self.LOOKBACK_DAYS)]
        days = [d for d in days if d.weekday() < 5]
        sem = asyncio.Semaphore(4)

        async def one(d: date):
            async with sem:
                return await self._day(d)

        results = await asyncio.gather(*(one(d) for d in days), return_exceptions=True)
        rows, errors = [], []
        for d, res in zip(days, results):
            if isinstance(res, ProviderError):
                errors.append(res)
            elif isinstance(res, BaseException):
                raise res
            elif res and symbol in res:
                sv, sx, tv = res[symbol]
                rows.append({"date": d.isoformat(), "short_volume": sv, "short_exempt": sx, "total_volume": tv})
        rows = rows[: self.DAYS]  # days run newest first
        if not rows:
            if errors:
                raise errors[0]
            raise ProviderError("not_found", "no FINRA daily file with this symbol in the look-back window")
        return {"rows": rows, "source": self.source, "failed_days": len(errors)}

    async def probe(self) -> None:
        if not await self._day(self.today() - timedelta(days=4)):
            raise ProviderError("unavailable", "probe found no file")
