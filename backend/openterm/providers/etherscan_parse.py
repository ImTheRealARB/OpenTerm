"""Pure parsers for the Etherscan V2 API (`https://api.etherscan.io/v2/api`). No network, no pandas.

Shapes come from the official endpoint pages (docs.etherscan.io, read 2026-11-05), NOT from recordings (no key was available):
  every answer: {"status": "1" | "0", "message": "OK" | "NOTOK" | ..., "result": ...}; errors are usually HTTP 200 with status "0".
  module=account&action=balance    result = "172774397764084972158218"  (wei, a string)
  module=account&action=txlist     result = [{blockNumber, blockHash, timeStamp, hash, nonce, transactionIndex, from, to, value, gas,
                                              gasPrice, input, methodId, functionName, contractAddress, cumulativeGasUsed,
                                              txreceipt_status, gasUsed, confirmations, isError}]  (every value is a string)
  module=gastracker&action=gasoracle  result = {LastBlock, SafeGasPrice, ProposeGasPrice, FastGasPrice, suggestBaseFee, gasUsedRatio}
                                              (gas prices in gwei, as strings)
Error texts the docs list ("Common Error Messages"): "Invalid API Key", "Max rate limit reached, please use API Key for higher rate limit",
"Too many invalid api key attempts, please try again later", "Free API access is not supported for this chain. Please upgrade your api plan",
"Community Free API limit reached. Resets <time>", "Error! Invalid address format", "Missing or unsupported chainid parameter".
One text is not in the docs: txlist answers status "0" with message "No transactions found" for an address with no transactions
(confirmed live 2026-11-05). It is treated as an empty list. The same day a free key was seen getting "Free API access is not supported
for this chain" for Optimism, Base and BNB Chain (but not Ethereum, Arbitrum, Polygon): see `result_of`.
"""

from __future__ import annotations

import re
from typing import Any

from .base import ProviderError

ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
WEI = 10**18
CHAINS = {"ETH": 1, "ARB": 42161, "OP": 10, "BASE": 8453, "POLY": 137, "BSC": 56}
"""Chain nickname -> chainid. Whether a chain works on the free plan is Etherscan's call; its refusal is shown as written."""


def result_of(body: Any) -> Any:
    """The `result` of an answer, or the ProviderError the answer stands for."""
    if not isinstance(body, dict) or "status" not in body or "result" not in body:
        raise ProviderError("unavailable", "unexpected Etherscan answer shape")
    if str(body["status"]) == "1":
        return body["result"]
    message = str(body.get("message") or "")
    detail = body["result"] if isinstance(body["result"], str) else message
    low = f"{message} {detail}".lower()
    if message == "No transactions found":
        return []
    # Rate texts first: "Too many invalid api key attempts" is a temporary throttle, not a bad key.
    if "rate limit" in low or "too many" in low or "limit reached" in low:
        raise ProviderError("rate_limited", detail[:160] or "Etherscan rate limit")
    if "invalid api key" in low or "missing/invalid api key" in low:
        raise ProviderError("key_required", "Etherscan refused the key (Invalid API Key)")
    if "not supported for this chain" in low:
        # Seen live (2026-11-05): a free key answers this for OP, BASE and BSC (it works for ETH, ARB, POLY). It is a plan limit,
        # not an outage, so it must be `unsupported`: the router gives no circuit-breaker strike for that kind, and a few
        # BASE lookups can no longer take ETH down with them.
        raise ProviderError("unsupported", "THIS CHAIN IS NOT INCLUDED IN THE FREE ETHERSCAN PLAN (A PAID ETHERSCAN KEY ADDS IT)")
    raise ProviderError("unavailable", ("Etherscan: " + (detail or message))[:200])


def eth(wei: Any) -> float:
    """Wei (decimal text) as a number of the chain's native coin. A non-numeric value means the answer is not the documented shape."""
    try:
        return int(wei) / WEI
    except (TypeError, ValueError) as e:
        raise ProviderError("unavailable", "unexpected Etherscan amount") from e


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def balance(result: Any) -> dict:
    if not isinstance(result, str):
        raise ProviderError("unavailable", "unexpected Etherscan balance shape")
    return {"wei": result, "balance": eth(result)}


def transactions(result: Any, address: str) -> list[dict]:
    """Latest-first rows with the direction relative to `address` (IN, OUT, SELF, or CREATE for a contract creation)."""
    if not isinstance(result, list):
        raise ProviderError("unavailable", "unexpected Etherscan transaction list shape")
    me = address.lower()
    rows = []
    for r in result:
        if not isinstance(r, dict) or not r.get("hash"):
            continue
        src, dst = str(r.get("from") or "").lower(), str(r.get("to") or "").lower()
        direction = "CREATE" if not dst else "SELF" if src == dst == me else "OUT" if src == me else "IN"
        gas_used, gas_price = _int(r.get("gasUsed")), _int(r.get("gasPrice"))
        rows.append({
            "hash": r["hash"], "block": _int(r.get("blockNumber")), "time": _int(r.get("timeStamp")), "dir": direction,
            "from": r.get("from"), "to": r.get("to") or None, "value": eth(r.get("value") or "0"),
            "fee": None if gas_used is None or gas_price is None else gas_used * gas_price / WEI,
            "failed": str(r.get("isError")) == "1", "method": (r.get("functionName") or r.get("methodId") or "")[:48],
            "confirmations": _int(r.get("confirmations")),
        })
    return rows


def _gwei(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def gas(result: Any) -> dict:
    if not isinstance(result, dict):
        raise ProviderError("unavailable", "unexpected Etherscan gas oracle shape")
    return {"last_block": _int(result.get("LastBlock")), "safe": _gwei(result.get("SafeGasPrice")),
            "propose": _gwei(result.get("ProposeGasPrice")), "fast": _gwei(result.get("FastGasPrice")),
            "base_fee": _gwei(result.get("suggestBaseFee"))}
