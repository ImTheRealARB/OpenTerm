"""Yahoo-style symbols <-> Kite `EXCHANGE:TRADINGSYMBOL` keys (spec "Instruments"). Pure."""

from __future__ import annotations

INDEX_KEYS = {"^NSEI": "NSE:NIFTY 50", "^NSEBANK": "NSE:NIFTY BANK", "^BSESN": "BSE:SENSEX"}
SUFFIX_EXCHANGE = {".NS": "NSE", ".BO": "BSE", ".NFO": "NFO", ".BFO": "BFO", ".MCX": "MCX", ".CDS": "CDS"}
FUTURES_EXCHANGES = ("NFO", "MCX")
#: the spot instrument an index option or future is quoted against (name in the dump -> Kite key)
UNDERLYING_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "FINNIFTY": "NSE:NIFTY FIN SERVICE",
                   "MIDCPNIFTY": "NSE:NIFTY MID SELECT"}
#: BFO (BSE derivatives) names whose spot is a BSE index; anything else on BFO is quoted as `BSE:<NAME>`
BSE_UNDERLYING_KEYS = {"SENSEX": "BSE:SENSEX", "BANKEX": "BSE:BANKEX", "SENSEX50": "BSE:SENSEX50"}
#: exchanges whose chains and futures tables (OMON / CT) we serve. The root is the dump's `name` column (`SENSEX`, `USDINR`, `CRUDEOIL`)
CHAIN_EXCHANGES = ("NFO", "BFO", "MCX", "CDS")
#: exchanges with no spot instrument to quote against: the option's underlying is the nearest future (MCX commodities, CDS currencies)
FUTURE_SPOT_EXCHANGES = ("MCX", "CDS")


def spot_key(exchange: str, name: str) -> str | None:
    """The Kite key of the spot an option on `name` is priced against, or None when the nearest future stands in (MCX, CDS)."""
    if exchange == "NFO":
        return UNDERLYING_KEYS.get(name, f"NSE:{name}")
    if exchange == "BFO":
        return BSE_UNDERLYING_KEYS.get(name, f"BSE:{name}")
    return None


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
    """`NIFTY.NFO` -> ("NFO", "NIFTY"), `SENSEX.BFO` -> ("BFO", "SENSEX"), `USDINR.CDS` -> ("CDS", "USDINR"); None for anything else."""
    s = symbol.strip().upper()
    for exchange in CHAIN_EXCHANGES:
        suffix = f".{exchange}"
        if s.endswith(suffix) and len(s) > len(suffix):
            return exchange, s[: -len(suffix)]
    return None
