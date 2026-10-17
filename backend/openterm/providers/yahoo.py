"""Yahoo Finance public chart/spark/search endpoints. Unofficial: can change or block without notice.
v7/quote needs a session crumb (401 without), so quotes are built from spark/chart metadata."""

import asyncio
from typing import Any, ClassVar

from ..models import Bars, Quote, SearchHit
from .base import HISTORY, QUOTES, SEARCH, Provider, ProviderError

BASE = "https://query1.finance.yahoo.com"
SEARCH_BASE = "https://query2.finance.yahoo.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
SPARK_CHUNK = 20


def quote_from_meta(meta: dict[str, Any], source: str, as_of: float, day_open: float | None = None) -> Quote:
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose", meta.get("chartPreviousClose"))
    change = price - prev if price is not None and prev is not None else None
    pct = change / prev * 100 if change is not None and prev else None
    vol = meta.get("regularMarketVolume")
    return Quote(
        symbol=meta["symbol"],
        name=meta.get("longName") or meta.get("shortName"),
        currency=meta.get("currency"),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        tz=meta.get("exchangeTimezoneName"),
        price=price,
        prev_close=prev,
        change=change,
        change_pct=pct,
        open=day_open,
        high=meta.get("regularMarketDayHigh"),
        low=meta.get("regularMarketDayLow"),
        volume=int(vol) if vol is not None else None,
        high_52w=meta.get("fiftyTwoWeekHigh"),
        low_52w=meta.get("fiftyTwoWeekLow"),
        market_time=meta.get("regularMarketTime"),
        source=source,
        as_of=as_of,
    )


def bars_from_chart(result: dict[str, Any], range_: str, interval: str, source: str, as_of: float) -> Bars:
    meta = result["meta"]
    t = result.get("timestamp") or []
    q = (result.get("indicators", {}).get("quote") or [{}])[0]
    n = len(t)

    def col(k: str) -> list:
        v = q.get(k)
        return v if v is not None and len(v) == n else [None] * n

    vol = col("volume")
    return Bars.model_construct(
        symbol=meta["symbol"],
        range=range_,
        interval=interval,
        currency=meta.get("currency"),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        tz=meta.get("exchangeTimezoneName"),
        t=t,
        o=col("open"),
        h=col("high"),
        l=col("low"),
        c=col("close"),
        v=[int(x) if x is not None else None for x in vol],
        source=source,
        as_of=as_of,
    )


class YahooProvider(Provider):
    name = "yahoo"
    label = "Yahoo Finance (unofficial)"
    capabilities = frozenset({QUOTES, HISTORY, SEARCH})
    markets = "Global equities/ETFs (suffixes .NS .BO .L .T .HK ...), indices (^), FX (=X), crypto (-USD)"
    terms = "Unofficial endpoints; personal use. Data delayed per exchange. May break or block without notice."
    rate = (4.0, 8)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    async def _chart(self, symbol: str, range_: str, interval: str) -> dict[str, Any]:
        body = await self.get_json(
            f"{BASE}/v8/finance/chart/{symbol}",
            {"range": range_, "interval": interval, "includePrePost": "false"},
        )
        chart = body.get("chart") or {}
        if chart.get("error") or not chart.get("result"):
            raise ProviderError("not_found", (chart.get("error") or {}).get("description", "no data"))
        return chart["result"][0]

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        result = await self._chart(symbol, range_, interval)
        if not result.get("timestamp"):
            raise ProviderError("not_found", "no bars")
        return bars_from_chart(result, range_, interval, self.source, self.now())

    async def _spark(self, symbols: list[str]) -> list[Quote]:
        body = await self.get_json(
            f"{BASE}/v7/finance/spark", {"symbols": ",".join(symbols), "range": "1d", "interval": "1d"}
        )
        as_of = self.now()
        out = []
        for item in (body.get("spark") or {}).get("result") or []:
            resp = item.get("response") or []
            if resp and resp[0].get("meta", {}).get("regularMarketPrice") is not None:
                out.append(quote_from_meta(resp[0]["meta"], self.source, as_of))
        return out

    async def _quote_via_chart(self, symbol: str) -> Quote | None:
        try:
            result = await self._chart(symbol, "1d", "1d")
        except ProviderError as e:
            if e.kind == "not_found":
                return None
            raise
        opens = ((result.get("indicators", {}).get("quote") or [{}])[0].get("open")) or [None]
        return quote_from_meta(result["meta"], self.source, self.now(), opens[0])

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        chunks = [symbols[i : i + SPARK_CHUNK] for i in range(0, len(symbols), SPARK_CHUNK)]
        try:
            parts = await asyncio.gather(*(self._spark(c) for c in chunks))
            return [q for part in parts for q in part]
        except ProviderError as e:
            if e.kind == "rate_limited":
                raise
        # Spark refused (format change or block): fall back to one chart call per symbol.
        found = await asyncio.gather(*(self._quote_via_chart(s) for s in symbols))
        return [q for q in found if q is not None]

    async def search(self, query: str) -> list[SearchHit]:
        body = await self.get_json(
            f"{SEARCH_BASE}/v1/finance/search",
            {"q": query, "quotesCount": 10, "newsCount": 0, "listsCount": 0},
        )
        return [
            SearchHit(
                symbol=q["symbol"],
                name=q.get("longname") or q.get("shortname"),
                exchange=q.get("exchDisp") or q.get("exchange"),
                type=q.get("typeDisp") or q.get("quoteType"),
                source=self.source,
            )
            for q in body.get("quotes") or []
            if q.get("symbol")
        ]

    async def probe(self) -> None:
        await self._chart("SPY", "1d", "1d")
