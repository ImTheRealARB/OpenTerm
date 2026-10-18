"""Yahoo option chains (`v7/finance/options`): strikes, bid/ask, volume, open interest and Yahoo's own IV, for OMON, PCR, OV, OVDV,
SKEW, HIVG and OSA. A subclass of the ownership adapter so it reuses the cookie + crumb flow, under its own name (`yahoo_options`)
so its health shows separately on SOURCES. Yahoo sends no Greeks: they are computed in options/chain.py and labelled so.
"""

from __future__ import annotations

from ..options import chain as ch
from .base import ProviderError
from .ownership import YahooOwnProvider
from .yahoo import BASE

OPTION_CHAIN = "option_chain"


class YahooOptionsProvider(YahooOwnProvider):
    name = "yahoo_options"
    label = "Yahoo Finance option chains (unofficial)"
    capabilities = frozenset({OPTION_CHAIN})
    markets = "US listed equity and ETF options (delayed ~15 minutes), a few index options"
    terms = "Unofficial v7/finance/options endpoint; personal use. IV is Yahoo's; Greeks are computed here."

    async def option_chain(self, symbol: str, expiry: int | None = None) -> dict:
        params: dict = {}
        if expiry is not None:
            params["date"] = int(expiry)
        body = None
        for attempt in range(2):
            crumb = await self._get_crumb(refresh=attempt > 0)
            try:
                body = await self.get_json(f"{BASE}/v7/finance/options/{symbol}", {**params, "crumb": crumb})
                break
            except ProviderError as e:
                if attempt == 0 and "401" in str(e):
                    continue   # crumb expired: fetch a new one once
                raise
        return ch.parse_yahoo_chain(body or {}, expiry, self.source)
