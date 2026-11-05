"""ADDR: an EVM address's balance and latest transactions, and the gas price (Etherscan V2, read only).

`ADDR 0x...` = balance + last 20 transactions + gas; `ADDR GAS` = just the gas price; a chain nickname (ETH ARB OP BASE POLY BSC) picks the chain,
Ethereum by default. Without ETHERSCAN_KEY the provider raises `key_required` and the route answers 424
`KEY REQUIRED: set ETHERSCAN_KEY in APIKEYS`. An address is public information, but it is still sent to Etherscan: nothing is sent anywhere else.
"""

from __future__ import annotations

from typing import Any

from ..providers.etherscan_parse import ADDRESS, CHAINS
from ..service import DataError

TTL_S = 30.0  # blocks come every few seconds; half a minute keeps a refresh from burning the 3-calls-a-second limit
COINS = {"ETH": "ETH", "ARB": "ETH", "OP": "ETH", "BASE": "ETH", "POLY": "POL", "BSC": "BNB"}
NOTE = "ETHERSCAN: ON-CHAIN DATA, READ ONLY. AMOUNTS ARE IN THE CHAIN'S NATIVE COIN; NO PRICES OR FIAT VALUES ARE SHOWN."


async def addr(svc: Any, q: str) -> dict[str, Any]:
    chain, address, gas_only = "ETH", None, False
    for w in (q or "").split():
        if w.upper() in CHAINS:
            chain = w.upper()
        elif w.upper() == "GAS":
            gas_only = True
        elif ADDRESS.match(w):
            address = w.lower()
        else:
            raise DataError("bad_request", f"NOT AN ADDRESS (0x + 40 HEX CHARACTERS), GAS OR A CHAIN ({' '.join(CHAINS)}): {w[:24]}")
    if address is None and not gas_only:
        raise DataError("bad_request", "GIVE AN ADDRESS (0x + 40 HEX CHARACTERS) OR GAS")
    chainid = CHAINS[chain]

    async def fetch() -> dict:
        if address is None:
            out, failed = await svc.router.call("chain", lambda p: p.chain_gas_view(chainid))
            data = {"mode": "GAS", "gas": out["gas"], "txs": None, "balance": None, "notes": []}
            source = out["source"]
        else:
            out, failed = await svc.router.call("chain", lambda p: p.chain_address(address, chainid))
            data = {"mode": "ADDRESS", **out}
            source = out["source"]
        data.update(chain=chain, chainid=chainid, coin=COINS[chain], address=address, note=NOTE)
        return {"data": data, "fallback_from": failed, "source": source}

    return await svc._swr(f"w:addr:{chainid}:{address or 'gas'}", TTL_S, fetch)
