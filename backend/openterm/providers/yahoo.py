"""Yahoo Finance public chart/spark/search endpoints. Unofficial: can change or block without notice.
v7/quote needs a session crumb (401 without), so quotes are built from spark/chart metadata."""

import asyncio
from typing import Any, ClassVar

import httpx

from ..models import Bars, Profile, Quote, SearchHit
from .base import HISTORY, PROFILE, QUOTES, SEARCH, Provider, ProviderError

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


def _raw(module: dict[str, Any] | None, key: str) -> Any:
    v = (module or {}).get(key)
    return v.get("raw") if isinstance(v, dict) else v


def profile_from_summary(symbol: str, r: dict[str, Any], source: str, as_of: float) -> Profile:
    ap, sd, ks, pr = (r.get(m) or {} for m in ("assetProfile", "summaryDetail", "defaultKeyStatistics", "price"))
    emp = ap.get("fullTimeEmployees")
    return Profile(
        symbol=symbol,
        name=pr.get("longName") or pr.get("shortName"),
        exchange=pr.get("exchangeName"),
        currency=pr.get("currency") or sd.get("currency"),
        quote_type=pr.get("quoteType"),
        sector=ap.get("sector"),
        industry=ap.get("industry"),
        country=ap.get("country"),
        website=ap.get("website"),
        employees=int(emp) if isinstance(emp, (int, float)) else None,
        description=ap.get("longBusinessSummary"),
        market_cap=_raw(sd, "marketCap") or _raw(pr, "marketCap"),
        enterprise_value=_raw(ks, "enterpriseValue"),
        pe=_raw(sd, "trailingPE"),
        forward_pe=_raw(sd, "forwardPE") or _raw(ks, "forwardPE"),
        eps=_raw(ks, "trailingEps"),
        forward_eps=_raw(ks, "forwardEps"),
        dividend_yield=_raw(sd, "dividendYield"),
        beta=_raw(sd, "beta") or _raw(ks, "beta"),
        shares_out=_raw(ks, "sharesOutstanding"),
        float_shares=_raw(ks, "floatShares"),
        high_52w=_raw(sd, "fiftyTwoWeekHigh"),
        low_52w=_raw(sd, "fiftyTwoWeekLow"),
        avg_volume=_raw(sd, "averageVolume"),
        price_to_book=_raw(ks, "priceToBook"),
        delay_min=pr.get("exchangeDataDelayedBy"),
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
    adj = ((result.get("indicators", {}).get("adjclose") or [{}])[0] or {}).get("adjclose")  # Phase 9
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
        adj=adj if adj is not None and len(adj) == n else None,
        source=source,
        as_of=as_of,
    )


class YahooProvider(Provider):
    name = "yahoo"
    label = "Yahoo Finance (unofficial)"
    capabilities = frozenset({QUOTES, HISTORY, SEARCH, PROFILE})
    markets = "Global equities/ETFs (suffixes .NS .BO .L .T .HK ...), indices (^), FX (=X), crypto (-USD)"
    terms = "Unofficial endpoints; personal use. Data delayed per exchange. May break or block without notice."
    rate = (4.0, 8)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._crumb: str | None = None
        self._crumb_lock = asyncio.Lock()

    async def _get_crumb(self, refresh: bool = False) -> str:
        """quoteSummary needs the session crumb a browser gets: a cookie from fc.yahoo.com, then getcrumb."""
        async with self._crumb_lock:
            if self._crumb and not refresh:
                return self._crumb
            try:
                # Answers 404 but sets the session cookie; only network errors matter here.
                # getcrumb returns text/plain and answers 406 to "Accept: application/json".
                plain = {"User-Agent": UA, "Accept": "*/*"}
                await self.http.get("https://fc.yahoo.com", headers=plain, timeout=6.0)
                r = await self.http.get(f"{BASE}/v1/test/getcrumb", headers=plain, timeout=6.0)
            except httpx.HTTPError as e:
                raise ProviderError("unavailable", f"crumb: {type(e).__name__}") from e
            if r.status_code != 200 or not r.text or "<" in r.text:
                raise ProviderError("unavailable", f"crumb HTTP {r.status_code}")
            self._crumb = r.text.strip()
            return self._crumb

    async def profile(self, symbol: str) -> Profile:
        modules = "assetProfile,summaryDetail,defaultKeyStatistics,price"
        for attempt in range(2):
            crumb = await self._get_crumb(refresh=attempt > 0)
            try:
                body = await self.get_json(
                    f"{SEARCH_BASE}/v10/finance/quoteSummary/{symbol}", {"modules": modules, "crumb": crumb}
                )
                break
            except ProviderError as e:
                if attempt == 0 and "401" in str(e):
                    continue  # crumb expired: fetch a new one once
                raise
        result = (body.get("quoteSummary") or {}).get("result")
        if not result:
            raise ProviderError("not_found", "no summary")
        return profile_from_summary(symbol, result[0], self.source, self.now())

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
