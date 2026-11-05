"""Frankfurter: ECB reference FX rates (keyless), as a `history` and `quotes` fallback for FX pairs such as EURUSD=X.

What it is: the European Central Bank publishes ONE reference rate per business day, around 16:00 Central European time, for the
major currencies. Frankfurter (https://frankfurter.dev) serves those rates over a free API, back to 4 January 1999. v2 of the API
is used with `providers=ecb`, so only genuine ECB fixes come back (no weekend rows, no blended providers).

Why it sits BELOW Yahoo in providers/hierarchy.py: a Yahoo FX chart has real open/high/low/close and live prices; the ECB gives
one fix a day. So this adapter is only a fallback when Yahoo is down, and it says so on the chart:
  - history: daily bars only (`1d`); open = high = low = close = the day's fix, volume is empty. The source text says
    "ECB daily fix: open = high = low = close". Weekly and monthly candles are not built here (Yahoo serves those).
  - quotes: the last fix and the one before it. `market_time` is the fix date, so the age shows how old it is (up to 3 days at a weekend).
Cross rates (INRJPY=X and so on) are computed by Frankfurter from the ECB's euro rates; a currency the ECB does not publish answers
404, which becomes `not_found` here (no circuit-breaker strike).

Rates: no key, no quota; the docs say requests are rate limited "to prevent abuse", so this adapter paces itself at 2 a second.
Fixture: `frankfurter_rates_eur_usd_inr` is a REAL recording (2026-11-05), see tests/fixtures.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

from ..models import Bars, Quote
from ..ranges import range_days
from . import frankfurter_parse as fp
from .base import HISTORY, QUOTES, Provider, ProviderError

BASE = "https://api.frankfurter.dev/v2"
QUOTE_LOOKBACK_DAYS = 10  # enough to find the last two fixes across a long weekend or a holiday week


class FrankfurterProvider(Provider):
    name = "frankfurter"
    label = "Frankfurter (ECB reference rates)"
    capabilities = frozenset({HISTORY, QUOTES})
    markets = "FX pairs the ECB publishes: one daily reference rate per business day, back to 1999 (no intraday, no high/low)"
    terms = "Free, keyless API (frankfurter.dev) serving ECB reference rates. Rate limited against abuse; no quota stated."
    rate = (2.0, 4)
    max_wait = 1.0
    timeout = 15.0  # a 20-year daily series is about 5,000 rows
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        # symbol None = "is the capability on at all" (Router.quotes asks that first), so it must be True there.
        return capability in self.capabilities and (symbol is None or fp.pair_of(symbol) is not None)

    @staticmethod
    def _today() -> date:
        return datetime.now(UTC).date()

    async def _rates(self, start: date, base: str, quotes: list[str]) -> list:
        return await self.get_json(f"{BASE}/rates", {"from": start.isoformat(), "base": base, "quotes": ",".join(quotes), "providers": "ecb"})

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        pair = fp.pair_of(symbol)
        if pair is None:
            raise ProviderError("unsupported", "not an FX pair")
        if interval != "1d":
            raise ProviderError("unsupported", f"the ECB publishes one rate a day: {interval} candles are not available here")
        base, quote = pair
        today = self._today()
        if range_ == "ytd":
            start = date(today.year, 1, 1)
        elif range_ == "max":
            start = fp.FIRST_DAY
        else:
            start = max(fp.FIRST_DAY, today - timedelta(days=range_days(range_)))
        ts, rates = fp.series(await self._rates(start, base, [quote]), base, quote)
        if not ts:
            raise ProviderError("not_found", "no ECB rates for this pair")
        n = len(ts)
        return Bars(symbol=symbol, range=range_, interval="1d", currency=quote, exchange="ECB", tz="UTC",
                    t=ts, o=rates, h=rates, l=rates, c=rates, v=[None] * n,
                    source="frankfurter (ECB daily fix: open = high = low = close)", as_of=self.now())

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        # One request per base currency, asking for every quote currency needed from it.
        wanted: dict[str, dict[str, list[str]]] = {}  # base -> quote -> [symbols]
        for s in symbols:
            pair = fp.pair_of(s)
            if pair:
                wanted.setdefault(pair[0], {}).setdefault(pair[1], []).append(s)
        out: list[Quote] = []
        start = self._today() - timedelta(days=QUOTE_LOOKBACK_DAYS)
        for base, by_quote in wanted.items():
            rows = await self._rates(start, base, list(by_quote))
            for quote, syms in by_quote.items():
                got = fp.latest_two(*fp.series(rows, base, quote))
                if got is None:
                    continue  # the router records "not_found" for symbols with no quote
                ts, price, prev = got
                for sym in syms:
                    out.append(Quote(symbol=sym, name=f"{base}/{quote} ECB reference rate", currency=quote, exchange="ECB", tz="UTC",
                                     price=price, prev_close=prev,
                                     change=None if prev is None else price - prev,
                                     change_pct=None if not prev else (price - prev) / prev * 100,
                                     market_time=ts, source="frankfurter (ECB daily fix)", as_of=self.now()))
        return out

    async def probe(self) -> None:
        await self._rates(self._today() - timedelta(days=QUOTE_LOOKBACK_DAYS), "EUR", ["USD"])
