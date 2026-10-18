"""Deribit public API (no key): BTC / ETH / SOL / XRP option book summaries with the exchange's own mark IV, for OVDV and SKEW on crypto.
Deribit quotes IV directly, so nothing is solved here; each instrument also carries the underlying (forward) price of its expiry.
"""

from __future__ import annotations

from ..options import chain as ch
from .base import Provider, ProviderError

BASE = "https://www.deribit.com/api/v2/public"
CRYPTO_OPTIONS = "crypto_options"
CURRENCIES = ("BTC", "ETH", "SOL", "XRP")


class DeribitProvider(Provider):
    name = "deribit"
    label = "Deribit public API"
    capabilities = frozenset({CRYPTO_OPTIONS})
    markets = "BTC, ETH, SOL and XRP options (exchange mark IV and per-expiry forward)"
    terms = "Public market data, no key. Mark IV is Deribit's own model value, not a trade."
    rate = (5.0, 10)
    timeout = 8.0

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and (symbol is None or symbol.upper() in CURRENCIES)

    async def crypto_options(self, currency: str) -> dict:
        cur = currency.upper()
        if cur not in CURRENCIES:
            raise ProviderError("unsupported", f"{cur}: OPTIONS ONLY FOR {' '.join(CURRENCIES)}")
        book = await self.get_json(f"{BASE}/get_book_summary_by_currency", {"currency": cur, "kind": "option"})
        index = await self.get_json(f"{BASE}/get_index_price", {"index_name": f"{cur.lower()}_usd"})
        return ch.parse_deribit(book, index, cur, self.source)
