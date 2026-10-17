"""Symbol layer. Canonical form is Yahoo-style (AAPL, RELIANCE.NS, BTC-USD, EURUSD=X, ^GSPC)."""

import re

ALIASES = {
    "SPX": "^GSPC", "INDU": "^DJI", "DJI": "^DJI", "NDX": "^NDX", "RTY": "^RUT", "VIX": "^VIX",
    "NIFTY": "^NSEI", "SENSEX": "^BSESN", "BANKNIFTY": "^NSEBANK",
    "UKX": "^FTSE", "FTSE": "^FTSE", "DAX": "^GDAXI", "CAC": "^FCHI", "NKY": "^N225", "HSI": "^HSI",
}
CURRENCIES = {
    "USD", "EUR", "JPY", "GBP", "INR", "CHF", "AUD", "CAD", "CNY", "HKD", "SGD", "NZD", "SEK", "NOK",
}
CRYPTO = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "LTC", "DOT", "AVAX"}
CRYPTO_QUOTES = ("USDT", "USD", "EUR", "INR")
_US_PLAIN = re.compile(r"^[A-Z]{1,5}$")
SYNTHETIC_RE = re.compile(r"^SYN\d{4}$")
"""Load-test instruments; only exist when OPENTERM_SYNTHETIC=1."""


def resolve(raw: str) -> str:
    s = raw.strip().upper()
    if s in ALIASES:
        return ALIASES[s]
    if len(s) == 6 and s[:3] in CURRENCIES and s[3:] in CURRENCIES:
        return s + "=X"
    for q in CRYPTO_QUOTES:
        base = s[: -len(q)]
        if s.endswith(q) and base in CRYPTO:
            return f"{base}-{q}"
    return s


def kind(symbol: str) -> str:
    if symbol.startswith("^"):
        return "index"
    if symbol.endswith("=X"):
        return "fx"
    if "-" in symbol and symbol.split("-")[0] in CRYPTO:
        return "crypto"
    if symbol.endswith("=F"):
        return "future"
    return "equity"


def is_us_plain(symbol: str) -> bool:
    """Plain US listing with no suffix: the only form the Nasdaq API understands."""
    return bool(_US_PLAIN.match(symbol))
