"""Crypto boards: CoinGecko markets (rank, market cap, 1h/24h/7d), Binance 24h tickers as fallback."""

import asyncio
import re
import time
from bisect import bisect_right
from datetime import datetime
from typing import Any, ClassVar

import orjson

from ..models import Bars, Coin
from ..ranges import _RANGE_DAYS
from .base import CRYPTO, HISTORY, Provider, ProviderError
from .yahoo import UA

# Quote currencies offered on CRYP (CoinGecko supports more; CRYP keeps to common ones).
VS = {"USD", "EUR", "GBP", "JPY", "INR", "AUD", "CAD", "CHF", "CNY", "HKD", "SGD", "KRW", "BRL", "BTC", "ETH"}
# Binance fallback universe (spot, against USDT). Every pair must exist or Binance rejects the call.
BINANCE_BASES = (
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK", "DOT",
    "TON", "SHIB", "LTC", "BCH", "UNI", "NEAR", "XLM", "ATOM", "ETC", "SUI", "APT",
)


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _iso(s: str | None) -> float | None:
    try:
        return datetime.fromisoformat(s or "").timestamp()
    except ValueError:
        return None


class CoinGeckoProvider(Provider):
    name = "coingecko"
    label = "CoinGecko public API"
    capabilities = frozenset({CRYPTO})
    markets = "Top 50 coins by market cap; quotes in USD, EUR, INR and other fiat"
    terms = "Free public API, no key (roughly 5-30 calls/min). Data by CoinGecko."
    rate = (0.25, 3)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    async def crypto(self, vs: str) -> list[Coin]:
        body = await self.get_json("https://api.coingecko.com/api/v3/coins/markets", {
            "vs_currency": vs.lower(), "order": "market_cap_desc", "per_page": 50, "page": 1,
            "price_change_percentage": "1h,24h,7d",
        })
        if not isinstance(body, list) or not body:
            raise ProviderError("not_found", "no markets")
        now = self.now()
        return [
            Coin(
                symbol=str(c.get("symbol", "")).upper(), name=c.get("name"), rank=c.get("market_cap_rank"),
                quote=vs.upper(), price=_f(c.get("current_price")),
                change_pct_1h=_f(c.get("price_change_percentage_1h_in_currency")),
                change_pct_24h=_f(c.get("price_change_percentage_24h_in_currency", c.get("price_change_percentage_24h"))),
                change_pct_7d=_f(c.get("price_change_percentage_7d_in_currency")),
                high_24h=_f(c.get("high_24h")), low_24h=_f(c.get("low_24h")), volume_24h=_f(c.get("total_volume")),
                market_cap=_f(c.get("market_cap")), updated=_iso(c.get("last_updated")), source=self.source, as_of=now,
            )
            for c in body
            if c.get("symbol")
        ]

    async def probe(self) -> None:
        await self.get_json("https://api.coingecko.com/api/v3/ping")


class BinanceProvider(Provider):
    name = "binance"
    label = "Binance public market data"
    capabilities = frozenset({CRYPTO})
    markets = f"{len(BINANCE_BASES)} major coins against USDT (spot). No rank or market cap"
    terms = "Public market-data host data-api.binance.vision, no key. Prices are in USDT, not USD."
    rate = (5.0, 10)
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and (symbol is None or symbol.upper() in ("USD", "USDT"))

    async def crypto(self, vs: str) -> list[Coin]:
        pairs = orjson.dumps([f"{b}USDT" for b in BINANCE_BASES]).decode()
        body = await self.get_json("https://data-api.binance.vision/api/v3/ticker/24hr", {"symbols": pairs})
        if not isinstance(body, list) or not body:
            raise ProviderError("not_found", "no tickers")
        now = self.now()
        order = {f"{b}USDT": i for i, b in enumerate(BINANCE_BASES)}
        body = sorted(body, key=lambda t: order.get(t.get("symbol"), len(order)))
        return [
            Coin(
                symbol=t["symbol"].removesuffix("USDT"), quote="USDT", price=_f(t.get("lastPrice")),
                change_pct_24h=_f(t.get("priceChangePercent")), high_24h=_f(t.get("highPrice")),
                low_24h=_f(t.get("lowPrice")), volume_24h=_f(t.get("quoteVolume")),
                updated=t["closeTime"] / 1000 if isinstance(t.get("closeTime"), (int, float)) else None,
                source=self.source, as_of=now,
            )
            for t in body
            if str(t.get("symbol", "")).endswith("USDT")
        ]

    async def probe(self) -> None:
        await self.get_json("https://data-api.binance.vision/api/v3/ping")


# --- Phase 12: Binance candles for the backtester (spot via the public market-data host, USD-M perpetuals) ---
_BINANCE_SPOT = "https://data-api.binance.vision/api/v3/klines"
_BINANCE_PERP = "https://fapi.binance.com/fapi/v1/klines"
_BINANCE_FUNDING = "https://fapi.binance.com/fapi/v1/fundingRate"
_BINANCE_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "1h", "1d": "1d", "1wk": "1w", "1mo": "1M"}
_BAR_DAYS = {"1m": 1 / 1440, "5m": 5 / 1440, "15m": 15 / 1440, "30m": 30 / 1440, "60m": 1 / 24, "1d": 1.0, "1wk": 7.0,
             "1mo": 30.4375}
_FUNDING_INTERVALS = ("1d", "1wk", "1mo")
_PAIR = re.compile(r"^([A-Z0-9]{2,12})(?:-?USDT)(\.P)?$")
_PAGE = 1000
_MAX_PAGES = 12


class BinanceKlinesProvider(Provider):
    """Candles for `BTCUSDT` / `BTC-USDT` (spot) and `BTCUSDT.P` (USD-M perpetual, with the funding rate per bar)."""

    name = "binance_klines"
    label = "Binance candles (spot + USD-M perpetuals)"
    capabilities = frozenset({HISTORY})
    markets = "USDT pairs: BTCUSDT / BTC-USDT spot, BTCUSDT.P perpetual with funding. Volume is truncated to a whole number"
    terms = "Public market data, no key. fapi.binance.com refuses some regions (HTTP 451): the perp then shows PROVIDER DOWN."
    rate = (5.0, 10)
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and symbol is not None and _PAIR.match(symbol.upper()) is not None

    async def _json(self, url: str, params: dict[str, Any]) -> Any:
        try:
            return await self.get_json(url, params)
        except ProviderError as e:
            if str(e) == "HTTP 400":  # Binance answers an unknown symbol with 400 (-1121)
                raise ProviderError("not_found", "unknown symbol") from e
            raise

    async def _pages(self, url: str, params: dict[str, Any], time_key: str, end_key: str, want: int) -> list:
        """Rows oldest first, paged backwards with endTime until `want` rows, the start of history, or a page that
        adds nothing new."""
        rows: dict[int, Any] = {}
        end: int | None = None
        for _ in range(_MAX_PAGES):
            page = await self._json(url, {**params, "limit": _PAGE, **({"endTime": end} if end is not None else {})})
            if not isinstance(page, list):
                raise ProviderError("unavailable", "unexpected payload")
            fresh = [r for r in page if (r[0] if isinstance(r, list) else r[time_key]) not in rows]
            if not fresh:
                break
            for r in fresh:
                rows[r[0] if isinstance(r, list) else r[time_key]] = r
            if len(page) < _PAGE or len(rows) >= want:
                break
            end = min(rows) - 1
        return [rows[k] for k in sorted(rows)]

    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        m = _PAIR.match(symbol.upper())
        bi = _BINANCE_INTERVAL.get(interval)
        if m is None or bi is None:
            raise ProviderError("unsupported", f"no Binance candles for {symbol} {interval}")
        pair, perp = f"{m.group(1)}USDT", m.group(2) is not None
        want = max(2, int(_RANGE_DAYS.get(range_, 366) / _BAR_DAYS[interval]) + 1)
        params = {"symbol": pair, "interval": bi}
        with_funding = perp and interval in _FUNDING_INTERVALS
        jobs = [self._pages(_BINANCE_PERP if perp else _BINANCE_SPOT, params, "", "", want)]
        if with_funding:
            jobs.append(self._pages(_BINANCE_FUNDING, {"symbol": pair}, "fundingTime", "", int(want * 3.2)))
        got = await asyncio.gather(*jobs)
        klines = got[0][-want:]
        if not klines:
            raise ProviderError("not_found", "no candles")
        opens = [int(r[0]) for r in klines]
        fund = None
        if with_funding:
            span = int(_BAR_DAYS[interval] * 86_400_000)
            sums, counts = [0.0] * len(opens), [0] * len(opens)
            for f in got[1]:
                ft = int(f["fundingTime"])
                i = bisect_right(opens, ft) - 1
                if i >= 0 and ft < opens[i] + span:
                    sums[i] += float(f["fundingRate"])
                    counts[i] += 1
            fund = [s / c if c else None for s, c in zip(sums, counts, strict=True)]
        return Bars.model_construct(
            symbol=symbol.upper(), range=range_, interval=interval, currency="USDT",
            exchange="Binance USD-M Futures" if perp else "Binance", tz="UTC",
            t=[o // 1000 for o in opens], o=[float(r[1]) for r in klines], h=[float(r[2]) for r in klines],
            l=[float(r[3]) for r in klines], c=[float(r[4]) for r in klines], v=[int(float(r[5])) for r in klines],
            fund=fund, source=self.source, as_of=time.time(),
        )

    async def probe(self) -> None:
        await self.get_json(_BINANCE_SPOT, {"symbol": "BTCUSDT", "interval": "1d", "limit": 1})
