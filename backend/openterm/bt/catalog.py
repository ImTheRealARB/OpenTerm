"""Engine catalog (pure, server side): which engine a symbol needs, which engines are built, default costs."""

from __future__ import annotations

BUILT = {"us", "uk", "hk", "ca"}
"""Engines `bt.engine` can run now. india, crypto, forex, futures and composite arrive in Phase 12 step 5."""

SLIPPAGE_KEY = {"us": "slippage_us", "uk": "slippage_uk", "hk": "slippage_hk", "ca": "slippage_ca"}
DEFAULT_SLIP_BPS = {"us": 5.0, "uk": 5.0, "hk": 10.0, "ca": 5.0, "india": 10.0, "crypto": 5.0, "futures": 3.0}
COSTS = {
    "us": "ZERO COMMISSION",
    "uk": "SDRT 0.5% ON PURCHASES",
    "hk": "STAMP 0.1% + COMMISSION 0.015% + LEVIES",
    "ca": "NO COMMISSION MODEL",
}
BARS_PER_YEAR = {"crypto": 365}


def detect(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".L"):
        return "uk"
    if s.endswith(".HK"):
        return "hk"
    if s.endswith((".TO", ".V")):
        return "ca"
    if s.endswith((".NS", ".BO")) or s in ("^NSEI", "^BSESN"):
        return "india"
    if s.endswith((".P", "USDT", "-USD")):
        return "crypto"
    if s.endswith("=X"):
        return "forex"
    if s.endswith("=F"):
        return "futures"
    return "us"


def engine_for(symbols: list[str], override: str | None = None) -> str:
    if override:
        return override.lower()
    found = {detect(s) for s in symbols}
    return found.pop() if len(found) == 1 else "composite"
