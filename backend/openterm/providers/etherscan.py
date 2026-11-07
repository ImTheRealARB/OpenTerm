"""Etherscan V2 (free key, read-only): an address's native-coin balance, its latest transactions, and the gas price oracle.

Capability `chain`. One key covers many EVM chains through the `chainid` parameter (1 = Ethereum). The free plan allows 3 calls a
second and 100,000 a day, on selected chains only: a chain it refuses answers "Free API access is not supported for this chain", which is
shown as written. The key travels as the `apikey` query parameter (the only method the docs describe); it is registered with redact.py
and no error text here contains a URL.

With no key `supports()` stays true and every call raises `key_required` BEFORE any network call: ADDR answers
`KEY REQUIRED: set ETHERSCAN_KEY in APIKEYS`. Nothing here sends a transaction or signs anything: read-only GET calls.

Checked live on 2026-11-05 with a real key (fixtures `etherscan_real_*`). A free key worked for Ethereum, Arbitrum and Polygon but got
"Free API access is not supported for this chain" for Optimism, Base and BNB Chain: that is `unsupported` (a plan limit), never `unavailable`.
Fixture-mode routes for Ethereum still use the doc-shaped answers.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import orjson

from ..redact import redact
from . import etherscan_parse as ep
from .base import ProviderError
from .keyed import KeyedProvider

URL = "https://api.etherscan.io/v2/api"
CAPABILITY = "chain"
TX_COUNT = 20


class EtherscanProvider(KeyedProvider):
    name = "etherscan"
    label = "Etherscan V2 (free key)"
    capabilities = frozenset({CAPABILITY})
    markets = "EVM chains (Ethereum first): address balance, recent transactions, gas price"
    terms = "Free key (ETHERSCAN_KEY), 3 calls a second and 100,000 a day, selected chains only."
    rate = (2.5, 3)  # the plan allows 3 a second; stay just under it
    max_wait = 2.0
    timeout = 10.0
    key_name = "ETHERSCAN_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm", "Accept": "application/json"}
    hide_without_key = False  # supports() stays true: a missing key answers KEY REQUIRED instead of looking broken
    msg_rate_limited = "Etherscan 429"
    msg_refused = "Etherscan refused the key ({code})"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, fixture: bool = False):
        super().__init__(http, source, fixture)
        self.source = "etherscan (doc-shaped fixture, NOT A RECORDING)" if self.fixture else "etherscan"

    def auth_params(self) -> dict[str, str]:
        return {"apikey": self._key}  # the only way the docs describe; the key is registered with redact.py

    async def _api(self, chainid: int, module: str, action: str, **extra: Any) -> Any:
        params = {"chainid": str(chainid), "module": module, "action": action, **extra}
        r = await self._request(URL, params, None)
        try:
            body = orjson.loads(r.content)
        except orjson.JSONDecodeError as e:
            raise ProviderError("unavailable", "non-JSON response") from e
        try:
            return ep.result_of(body)
        except ProviderError as e:
            raise ProviderError(e.kind, redact(str(e), [self._key])) from e

    async def chain_balance(self, address: str, chainid: int) -> dict:
        return ep.balance(await self._api(chainid, "account", "balance", address=address, tag="latest"))

    async def chain_txs(self, address: str, chainid: int) -> list[dict]:
        rows = await self._api(chainid, "account", "txlist", address=address, startblock="0", endblock="99999999", page="1",
                               offset=str(TX_COUNT), sort="desc")
        return ep.transactions(rows, address)

    async def chain_gas(self, chainid: int) -> dict:
        return ep.gas(await self._api(chainid, "gastracker", "gasoracle"))

    async def chain_gas_view(self, chainid: int) -> dict:
        return {"gas": await self.chain_gas(chainid), "source": self.source}

    async def chain_address(self, address: str, chainid: int) -> dict:
        """Balance (required), then the latest transactions and the gas price. A part that fails after the balance worked is left
        empty and the reason is listed in `notes`, so the panel shows what it has and says what is missing."""
        out: dict[str, Any] = {"balance": await self.chain_balance(address, chainid), "txs": None, "gas": None}
        notes: list[str] = []
        for key, call in (("txs", lambda: self.chain_txs(address, chainid)), ("gas", lambda: self.chain_gas(chainid))):
            try:
                out[key] = await call()
            except ProviderError as e:
                if e.kind == "key_required":
                    raise
                notes.append(f"{'TRANSACTIONS' if key == 'txs' else 'GAS'} NOT LOADED: {e}")
        return {**out, "notes": notes, "source": self.source}
