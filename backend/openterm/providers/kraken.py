"""Kraken public market data (keyless): the CRYP board, candles for the chart and order-book depth for CDEP.

Why it exists: a second crypto exchange for when Binance is blocked in the caller's country (HTTP 451) or down. It ranks below Binance,
Yahoo and Coinbase in the source hierarchy (providers/hierarchy.py) and answers only when the sources above it cannot.

Honest limits, all verified live on 2026-11-05 (docs/DATA_SOURCES.md has the numbers):
  - the OHLC endpoint returns only the LAST 720 candles of a length (12 hours of 1 minute, 30 days of hourly, 720 days of daily) and
    `since=` cannot page further back, so a longer request raises ProviderError("depth") instead of returning a short answer;
    weekly candles are the exception: they reach back to 2013, so all of them come back;
  - there is no 2 minute, 90 minute or monthly candle, so those lengths are `unsupported` (never rebuilt from other candles);
  - the board has no 24 hour price change (Kraken only gives today's open since 00:00 UTC, a different window), so that column is empty;
  - polling only: no WebSocket stream is built for Kraken (Binance and Yahoo streams are untouched).
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..models import Bars, Coin
from ..world import cryptodepth as cd
from .base import CRYPTO, HISTORY, Provider, ProviderError
from .crypto import BINANCE_BASES
from .cryptoex_parse import (
    bars_wanted,
    depth_text,
    kraken_pair,
    kraken_unwrap,
    make_bars,
    parse_kraken_ohlc,
    parse_kraken_ticker,
    split_pair,
)

DEPTH = "crypto_depth"
API = "https://api.kraken.com/0/public"
# The app's candle lengths -> Kraken's `interval` in minutes. 2m, 90m and 1mo do not exist on Kraken.
INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1d": 1440, "1wk": 10080}
MAX_BARS = 720  # what one OHLC answer holds, whatever the length
BOARD_QUOTES = ("USD", "EUR")  # every board coin is listed against both; GBP is missing for several, so it is not offered
_BAR_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1d": 1440}


class KrakenProvider(Provider):
    name = "kraken"
    label = "Kraken public market data"
    capabilities = frozenset({CRYPTO, HISTORY, DEPTH})
    markets = ("Spot pairs against USD, USDT, EUR or GBP (BTC-USD, ETH-USDT, SOL-EUR): board of 22 coins in USD / EUR, candles 1m-1wk, order book. "
               "A USD pair is not a USDT pair: the quote is shown, never swapped")
    terms = "Public market data, no key. Data by Kraken. Candles: only the last 720 of each length (weekly: all since 2013)."
    rate = (1.0, 5)  # Kraken's public REST allows roughly one call a second
    max_wait = 1.5
    timeout = 8.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}
    # Days of history per candle length that one answer covers (720 candles, rounded down). 1m (12 hours) is under a day: not declared.
    intraday_days: ClassVar[dict[str, int]] = {"5m": 2, "15m": 7, "30m": 15, "60m": 30}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        if capability not in self.capabilities:
            return False
        if symbol is None or capability == DEPTH:  # depth: the pair is checked by Kraken itself (unknown pair -> not_found)
            return True
        if capability == CRYPTO:  # the symbol is the quote currency of the board
            return symbol.upper() in BOARD_QUOTES
        return split_pair(symbol) is not None  # history: a crypto pair in the app's spelling

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        return await self.get_json(f"{API}/{path}", params)

    # --- CRYP board -------------------------------------------------------------------------------------------------
    async def crypto(self, vs: str) -> list[Coin]:
        vs = vs.upper()
        if vs not in BOARD_QUOTES:
            raise ProviderError("unsupported", f"KRAKEN BOARD QUOTES: {' '.join(BOARD_QUOTES)}")
        pairs = ",".join(kraken_pair(b, vs) for b in BINANCE_BASES)
        body = await self._get("Ticker", {"pair": pairs})
        return parse_kraken_ticker(body, BINANCE_BASES, vs, self.source, self.now())

    # --- candles ----------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        pair, minutes = split_pair(symbol), INTERVAL.get(interval)
        if pair is None or minutes is None:
            raise ProviderError("unsupported", f"no Kraken candles for {symbol} {interval}")
        base, quote = pair
        want = bars_wanted(range_, interval)
        if interval != "1wk" and want > MAX_BARS:
            # Too deep for one answer. A deeper source above (Coinbase pages further back) may have answered already; if none did,
            # this sentence reaches the user and the chart offers a shorter range.
            raise ProviderError("depth", depth_text(interval, MAX_BARS * _BAR_MINUTES[interval] / 1440))
        body = await self._get("OHLC", {"pair": kraken_pair(base, quote), "interval": minutes})
        rows = parse_kraken_ohlc(body)
        return make_bars(rows, symbol.upper(), range_, interval, quote, "Kraken", self.source, want + 1)

    # --- CDEP order book --------------------------------------------------------------------------------------------
    async def crypto_depth(self, base: str, quote: str) -> dict[str, Any]:
        pair = kraken_pair(base, quote)
        bids, asks, ts = cd.parse_kraken_book(await self._get("Depth", {"pair": pair, "count": 100}))
        return {**cd.depth_summary(bids, asks, quote), "symbol": pair, "venue": "KRAKEN SPOT", "ts_ms": ts}

    async def probe(self) -> None:
        kraken_unwrap(await self._get("Ticker", {"pair": "XBTUSD"}), "TICKER")
