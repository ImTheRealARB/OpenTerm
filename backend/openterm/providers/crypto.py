"""Crypto boards: CoinGecko markets (rank, market cap, 1h/24h/7d), Binance 24h tickers as fallback."""

from datetime import datetime
from typing import Any, ClassVar

import orjson

from ..models import Coin
from .base import CRYPTO, Provider, ProviderError
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
