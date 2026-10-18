"""DefiLlama stablecoin supply and yield pools (keyless). The yields answer is ~11 MB / 20 000 pools: it is parsed here, cut to pools with TVL above
US$1M and a few fields, and never leaves this module whole. Emissions (token unlocks) sit behind DefiLlama's paid API (HTTP 402), so UNLK is not built."""

from __future__ import annotations

from typing import Any, ClassVar

import orjson

from ..world import cryptodepth as cd
from .base import Provider, ProviderError

STABLECOINS = "stablecoins"
YIELDS = "yields"


class DefiLlamaProvider(Provider):
    name = "defillama"
    label = "DefiLlama stablecoins + yields"
    capabilities = frozenset({STABLECOINS, YIELDS})
    markets = "Stablecoin supply by coin and chain; DeFi yield pools (TVL > US$1M)"
    terms = "Free public endpoints, no key (emissions / unlocks are paid and not used)."
    rate = (1.0, 4)
    max_wait = 1.0
    timeout = 25.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}

    async def stablecoins(self, chain: str) -> dict[str, Any]:
        body = await self.get_json("https://stablecoins.llama.fi/stablecoins", {"includePrices": "true"})
        return cd.parse_stablecoins(body, chain)

    async def yields(self) -> list[dict[str, Any]]:
        raw = await self.get_bytes("https://yields.llama.fi/pools", None, 40.0)
        try:
            body = orjson.loads(raw)
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", "non-JSON response") from e
        del raw
        return cd.filter_pools(body)

    async def probe(self) -> None:
        await self.get_bytes("https://stablecoins.llama.fi/stablecoinchains")
