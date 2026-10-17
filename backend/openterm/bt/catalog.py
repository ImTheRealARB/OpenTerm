"""Engine catalog (pure, server side): which engine a symbol needs, which engines are built, default costs."""

from __future__ import annotations

BUILT = {"us", "uk", "hk", "ca", "india", "crypto", "forex", "futures", "composite"}
"""Engines `bt.engine` can run. China A, China futures, Korea, Vietnam and Brazil are not built (spec decision C)."""

SLIPPAGE_KEYS = {
    "us": ("slippage_us",), "uk": ("slippage_uk",), "hk": ("slippage_hk",), "ca": ("slippage_ca",),
    "india": ("slippage",), "crypto": ("slippage",), "futures": ("slippage",),
    "composite": ("slippage_us", "slippage_uk", "slippage_hk", "slippage_ca", "slippage"),
}
"""Config keys `SLIP=<bps>` sets per engine. Forex has none: its cost is a spread and slippage in pips."""
DEFAULT_SLIP_BPS = {"us": 5.0, "uk": 5.0, "hk": 10.0, "ca": 5.0, "india": 10.0, "crypto": 5.0, "futures": 3.0}
COSTS = {
    "us": "ZERO COMMISSION",
    "uk": "SDRT 0.5% ON PURCHASES",
    "hk": "STAMP 0.1% + COMMISSION 0.015% + LEVIES",
    "ca": "NO COMMISSION MODEL",
    "india": "STT 0.1% BOTH SIDES + EXCHANGE 0.00297% + SEBI + STAMP 0.015% BUY + GST 18%",
    "crypto": "TAKER 0.05% OPEN, MAKER 0.02% CLOSE, FUNDING ON PERPETUALS",
    "forex": "HALF SPREAD + 0.3 PIP SLIPPAGE, DAILY SWAP",
    "futures": "USD 2.25-2.50 PER CONTRACT PER SIDE",
    "composite": "EACH MARKET'S OWN COST STACK",
}


def bars_per_year(engine: str, interval: str) -> int:
    """Annualisation factor for Sharpe and friends: crypto trades every day of the year."""
    if interval == "1W":
        return 52
    return 365 if engine == "crypto" else 252


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
