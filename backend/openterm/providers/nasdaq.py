"""api.nasdaq.com public quote endpoints. Zero-key fallback for plain US tickers; daily history only."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from ..models import Bars, Profile, Quote
from ..ranges import range_days
from ..symbols import is_us_plain
from .base import HISTORY, PROFILE, QUOTES, Provider, ProviderError
from .yahoo import UA

BASE = "https://api.nasdaq.com/api/quote"
NY = ZoneInfo("America/New_York")


def num(s: Any) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace("$", "").replace(",", "").replace("%", "").strip()
    if s in ("", "N/A", "NA", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_trade_time(s: str | None) -> int | None:
    if not s:
        return None
    s = s.replace(" ET", "").replace("DATA AS OF ", "").strip()
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=NY).timestamp())
        except ValueError:
            continue
    return None


def quote_from_info(d: dict[str, Any], source: str, as_of: float) -> Quote:
    p = d.get("primaryData") or {}
    price = num(p.get("lastSalePrice"))
    chg = num(p.get("netChange"))
    prev = price - chg if price is not None and chg is not None else None
    lo52 = hi52 = None
    rng = ((d.get("keyStats") or {}).get("fiftyTwoWeekHighLow") or {}).get("value")
    if rng and " - " in rng:
        lo52, hi52 = (num(x) for x in rng.split(" - ", 1))
    day_lo = day_hi = None
    dr = ((d.get("keyStats") or {}).get("dayrange") or {}).get("value")
    if dr and " - " in dr:
        day_lo, day_hi = (num(x) for x in dr.split(" - ", 1))
    vol = num(p.get("volume"))
    return Quote(
        symbol=d["symbol"].upper(),
        name=d.get("companyName"),
        currency="USD",
        exchange=d.get("exchange"),
        tz="America/New_York",
        price=price,
        prev_close=prev,
        change=chg,
        change_pct=num(p.get("percentageChange")),
        high=day_hi,
        low=day_lo,
        volume=int(vol) if vol is not None else None,
        high_52w=hi52,
        low_52w=lo52,
        market_time=parse_trade_time(p.get("lastTradeTimestamp")),
        source=source,
        as_of=as_of,
    )


def bars_from_rows(symbol: str, rows: list[dict[str, Any]], range_: str, source: str, as_of: float) -> Bars:
    t, o, h, lo, c, v = [], [], [], [], [], []
    for r in reversed(rows):  # API returns newest first
        m, dd, y = (int(x) for x in r["date"].split("/"))
        t.append(int(datetime(y, m, dd, tzinfo=UTC).timestamp()))
        o.append(num(r.get("open")))
        h.append(num(r.get("high")))
        lo.append(num(r.get("low")))
        c.append(num(r.get("close")))
        vol = num(r.get("volume"))
        v.append(int(vol) if vol is not None else None)
    return Bars.model_construct(
        symbol=symbol, range=range_, interval="1d", currency="USD", exchange=None,
        tz="America/New_York", t=t, o=o, h=h, l=lo, c=c, v=v, source=source, as_of=as_of,
    )


class NasdaqProvider(Provider):
    name = "nasdaq"
    label = "Nasdaq.com public API"
    capabilities = frozenset({QUOTES, HISTORY, PROFILE})
    markets = "US-listed stocks and ETFs (plain tickers only); daily history only"
    terms = "Public website API; personal use. Quotes are delayed. Undocumented: may change."
    rate = (2.0, 4)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and (symbol is None or is_us_plain(symbol))

    async def _get(self, symbol: str, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        for asset in ("stocks", "etf"):
            body = await self.get_json(f"{BASE}/{symbol}/{path}", {"assetclass": asset, **params})
            data = body.get("data") if isinstance(body, dict) else None
            if data:
                return data
        return None

    async def _one(self, symbol: str) -> Quote | None:
        data = await self._get(symbol, "info", {})
        if not data or not (data.get("primaryData") or {}).get("lastSalePrice"):
            return None
        return quote_from_info(data, self.source, self.now())

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        found = await asyncio.gather(*(self._one(s) for s in symbols))
        return [q for q in found if q is not None]

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        if interval != "1d":
            raise ProviderError("unsupported", "nasdaq: daily bars only")
        today = date.today()
        if range_ == "ytd":
            start = date(today.year, 1, 1)
        else:
            start = today - timedelta(days=min(range_days(range_), 3653))
        data = await self._get(
            symbol, "historical",
            {"fromdate": start.isoformat(), "todate": today.isoformat(), "limit": 9999},
        )
        rows = ((data or {}).get("tradesTable") or {}).get("rows") or []
        if not rows:
            raise ProviderError("not_found", "no rows")
        return bars_from_rows(symbol, rows, range_, self.source, self.now())

    async def profile(self, symbol: str) -> Profile:
        body = await self.get_json(f"https://api.nasdaq.com/api/company/{symbol}/company-profile")
        d = (body or {}).get("data") if isinstance(body, dict) else None
        if not d:
            raise ProviderError("not_found", "no profile")

        def v(k: str) -> str | None:
            return ((d.get(k) or {}).get("value")) or None

        return Profile(
            symbol=symbol, name=v("CompanyName"), sector=v("Sector"), industry=v("Industry"),
            country=v("Region"), website=v("CompanyUrl"), description=v("CompanyDescription"),
            currency="USD", source=self.source, as_of=self.now(),
        )

    async def probe(self) -> None:
        if not await self._one("AAPL"):
            raise ProviderError("unavailable", "probe returned no data")
