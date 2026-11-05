"""Coinbase Exchange public market data (keyless): the CRYP board (USD), candles for the chart and order-book depth for CDEP.

Why it exists: a second crypto exchange for when Binance is blocked in the caller's country (HTTP 451) or down. For candles it ranks
ABOVE Kraken because it can be paged back as far as you like (Kraken keeps only the last 720 candles); for the board it ranks below
Kraken because it needs one call per coin.

Honest limits, all verified live on 2026-11-05 (docs/DATA_SOURCES.md has the numbers):
  - one candles call holds at most 300 candles and the request itself is refused above that ("Count of aggregations ... exceeds 300"),
    so a range is fetched as several windows at once. We cap one request at MAX_BARS candles (14 calls); a longer intraday range raises
    ProviderError("depth"), a longer daily range (10Y / 20Y / MAX) returns the newest MAX_BARS days;
  - only the lengths 1 minute, 5 minutes, 15 minutes, 1 hour (and 6 hours and 1 day) exist. 2m, 30m, 90m, weekly and monthly candles are
    `unsupported` (never rebuilt from other candles);
  - the board has no volume value (Coinbase reports volume in coins, not in USD), so that column is empty;
  - the level-2 order book is the WHOLE book (~20,000 levels, ~1 MB): only the best 100 levels a side are kept;
  - polling only: no WebSocket stream is built for Coinbase (Binance and Yahoo streams are untouched).
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..models import Bars, Coin
from ..world import cryptodepth as cd
from .base import CRYPTO, HISTORY, Provider, ProviderError
from .crypto import BINANCE_BASES
from .cryptoex_parse import (
    bars_wanted,
    depth_text,
    make_bars,
    parse_coinbase_candles,
    parse_coinbase_stats,
    split_pair,
)

DEPTH = "crypto_depth"
API = "https://api.exchange.coinbase.com"
# The app's candle lengths -> Coinbase `granularity` in seconds. Coinbase only has 60 / 300 / 900 / 3600 / 21600 / 86400.
GRANULARITY = {"1m": 60, "5m": 300, "15m": 900, "60m": 3600, "1d": 86400}
WINDOW = 299  # candles per call (the limit is 300; staying one under keeps every window legal)
MAX_BARS = 4000  # the most candles one request pulls: 14 calls
# Board coins with a -USD product on Coinbase (TRX has none; verified from /products on 2026-11-05).
BOARD_BASES = tuple(b for b in BINANCE_BASES if b != "TRX")
_BAR_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "60m": 3600, "1d": 86400}


class CoinbaseProvider(Provider):
    name = "coinbase"
    label = "Coinbase Exchange public market data"
    capabilities = frozenset({CRYPTO, HISTORY, DEPTH})
    markets = ("Spot products against USD, USDT, EUR or GBP (BTC-USD, ETH-USDT): board of 21 coins in USD only, candles 1m / 5m / 15m / 1h / 1d, "
               "order book. A USD pair is not a USDT pair: the quote is shown, never swapped")
    terms = "Public market data, no key (a User-Agent is required). Data by Coinbase. About 10 requests a second per IP."
    rate = (8.0, 12)
    max_wait = 3.0  # a 14-window candle fetch or the 21-coin board is a burst; wait for slots rather than fail over
    timeout = 8.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}
    # Days one request reaches back per candle length (MAX_BARS candles, rounded down). The API itself goes much further back; this is our
    # paging budget. 30m is not a Coinbase length, so it is not declared.
    intraday_days: ClassVar[dict[str, int]] = {"1m": 2, "5m": 13, "15m": 41, "60m": 166}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        if capability not in self.capabilities:
            return False
        if symbol is None or capability == DEPTH:  # depth: an unknown product answers 404 -> not_found
            return True
        if capability == CRYPTO:  # the symbol is the quote currency of the board
            return symbol.upper() == "USD"
        return split_pair(symbol) is not None

    # --- CRYP board -------------------------------------------------------------------------------------------------
    async def crypto(self, vs: str) -> list[Coin]:
        if vs.upper() != "USD":
            raise ProviderError("unsupported", "COINBASE BOARD IS USD ONLY")
        as_of = self.now()

        async def one(base: str) -> Coin | None:
            try:
                body = await self.get_json(f"{API}/products/{base}-USD/stats")
            except ProviderError as e:
                if e.kind == "not_found":  # the product was delisted: leave it off the board rather than fail the whole board
                    return None
                raise
            return parse_coinbase_stats(body, base, "USD", self.source, as_of)

        coins = [c for c in await asyncio.gather(*(one(b) for b in BOARD_BASES)) if c is not None]
        if not coins:
            raise ProviderError("not_found", "COINBASE: NO BOARD PRODUCT ANSWERED")
        return coins

    # --- candles ----------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        pair, gran = split_pair(symbol), GRANULARITY.get(interval)
        if pair is None or gran is None:
            raise ProviderError("unsupported", f"no Coinbase candles for {symbol} {interval}")
        base, quote = pair
        want = bars_wanted(range_, interval)
        if want > MAX_BARS:
            if interval != "1d":  # intraday: say how far one request reaches so the chart can offer a shorter range
                raise ProviderError("depth", depth_text(interval, MAX_BARS * _BAR_SECONDS[interval] / 86400))
            want = MAX_BARS  # daily: 10Y / 20Y / MAX give the newest MAX_BARS days (BTC-USD on Coinbase starts in 2015 anyway)
        # Windows of WINDOW candles walking back from now; each shares its boundary with the next, so no candle falls in a gap.
        end = math.floor(time.time())
        span = WINDOW * gran
        windows = [(end - (i + 1) * span, end - i * span) for i in range(math.ceil((want + 1) / WINDOW))]
        product = f"{base}-{quote}"
        answers = await asyncio.gather(*(self._window(product, gran, a, b) for a, b in windows))
        merged: dict[int, tuple[int, float, float, float, float, float]] = {}
        for rows in answers:
            merged.update((r[0], r) for r in rows)
        if not merged:
            raise ProviderError("not_found", "no candles")
        return make_bars([merged[t] for t in sorted(merged)], symbol.upper(), range_, interval, quote, "Coinbase", self.source, want + 1)

    async def _window(self, product: str, gran: int, start: int, end: int) -> list[tuple[int, float, float, float, float, float]]:
        params = {"granularity": gran, "start": datetime.fromtimestamp(start, UTC).isoformat(), "end": datetime.fromtimestamp(end, UTC).isoformat()}
        body = await self.get_json(f"{API}/products/{product}/candles", params)
        return parse_coinbase_candles(body)

    # --- CDEP order book --------------------------------------------------------------------------------------------
    async def crypto_depth(self, base: str, quote: str) -> dict[str, Any]:
        product = f"{base}-{quote}"
        bids, asks, ts = cd.parse_coinbase_book(await self.get_json(f"{API}/products/{product}/book", {"level": 2}))
        return {**cd.depth_summary(bids, asks, quote), "symbol": product, "venue": "COINBASE SPOT", "ts_ms": ts}

    async def probe(self) -> None:
        await self.get_json(f"{API}/products/BTC-USD/stats")
