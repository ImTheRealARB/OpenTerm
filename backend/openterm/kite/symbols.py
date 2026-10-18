"""Yahoo-style symbols <-> Kite `EXCHANGE:TRADINGSYMBOL` keys (spec "Instruments"). Pure."""

from __future__ import annotations

INDEX_KEYS = {"^NSEI": "NSE:NIFTY 50", "^NSEBANK": "NSE:NIFTY BANK"}
SUFFIX_EXCHANGE = {".NS": "NSE", ".BO": "BSE", ".NFO": "NFO", ".MCX": "MCX"}
FUTURES_EXCHANGES = ("NFO", "MCX")
#: the spot instrument an index option or future is quoted against (name in the dump -> Kite key)
UNDERLYING_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "FINNIFTY": "NSE:NIFTY FIN SERVICE",
                   "MIDCPNIFTY": "NSE:NIFTY MID SELECT"}


def to_kite(symbol: str) -> str | None:
    """`RELIANCE.NS` -> `NSE:RELIANCE`, `.BO` -> `BSE:`, `^NSEI` -> `NSE:NIFTY 50`, `NIFTY26OCTFUT.NFO` -> `NFO:NIFTY26OCTFUT`.
    None for anything Kite does not serve (US names, FX, synthetic test symbols)."""
    s = symbol.strip().upper()
    if s in INDEX_KEYS:
        return INDEX_KEYS[s]
    for suffix, exchange in SUFFIX_EXCHANGE.items():
        if s.endswith(suffix) and len(s) > len(suffix):
            return f"{exchange}:{s[: -len(suffix)]}"
    return None


def split_key(key: str) -> tuple[str, str]:
    exchange, _, trading = key.partition(":")
    return exchange, trading


def to_yahoo(key: str) -> str | None:
    """The reverse map for ticks: `NSE:RELIANCE` -> `RELIANCE.NS`, `NSE:NIFTY 50` -> `^NSEI`, `NFO:...` -> `....NFO`."""
    for sym, k in INDEX_KEYS.items():
        if k == key:
            return sym
    exchange, trading = split_key(key)
    for suffix, ex in SUFFIX_EXCHANGE.items():
        if ex == exchange and trading:
            return f"{trading}{suffix}"
    return None


def derivative_root(symbol: str) -> tuple[str, str] | None:
    """`NIFTY.NFO` -> ("NFO", "NIFTY"); None for anything that is not an NFO / MCX symbol."""
    s = symbol.strip().upper()
    for suffix in (".NFO", ".MCX"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return suffix[1:], s[: -len(suffix)]
    return None
