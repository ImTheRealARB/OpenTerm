"""Provider catalog. Keyless adapters are always on; keyed ones appear on SOURCES with their status."""

import httpx

from ..config import Settings
from .base import Provider
from .crypto import BinanceProvider, CoinGeckoProvider
from .fixtures import fixture_transport
from .nasdaq import NasdaqProvider
from .news import GdeltProvider, RssProvider, YahooRssProvider
from .synthetic import SyntheticProvider
from .yahoo import YahooProvider

ADAPTERS: dict[str, type[Provider]] = {
    "yahoo": YahooProvider, "nasdaq": NasdaqProvider, "rss": RssProvider, "yahoo_rss": YahooRssProvider,
    "gdelt": GdeltProvider, "coingecko": CoinGeckoProvider, "binance": BinanceProvider,
}

# Keyed providers planned for later phases: name -> (settings attribute, phase, purpose).
KEYED = {
    "finnhub": ("finnhub_api_key", 3, "Streaming quotes, news, earnings calendar"),
    "twelvedata": ("twelvedata_api_key", 3, "Quotes/history fallback incl. some non-US"),
    "alphavantage": ("alphavantage_api_key", 6, "Fundamentals fallback"),
    "fred": ("fred_api_key", 7, "Macro series, rates"),
    "fmp": ("fmp_api_key", 6, "Fundamentals, screener universe"),
    "polygon": ("polygon_api_key", 3, "US quotes/history fallback"),
}

# Removed from the default chain, with the reason shown on SOURCES.
RETIRED = {
    "stooq": "Download endpoints now serve a JavaScript bot check (verified 2026-10-17). "
    "OpenTerm does not bypass bot protection.",
}


def build(
    settings: Settings, http: httpx.AsyncClient, fixtures: bool = False, synthetic: bool = False
) -> dict[str, Provider]:
    if fixtures:
        # Offline replay of recorded responses for tests and the bench. Tagged so the UI shows it.
        fx = httpx.AsyncClient(transport=fixture_transport())
        out: dict[str, Provider] = {name: cls(fx, source=f"{name}:fixture") for name, cls in ADAPTERS.items()}
    else:
        out = {name: cls(http) for name, cls in ADAPTERS.items()}
    if synthetic:
        out["synthetic"] = SyntheticProvider()
    return out


def keyed_status(settings: Settings) -> list[dict]:
    out = [
        {
            "name": name,
            "status": "NOT BUILT" if getattr(settings, attr) else "KEY REQUIRED",
            "note": f"{purpose}. Phase {phase}." + ("" if getattr(settings, attr) else f" Set {attr.upper()} in .env."),
        }
        for name, (attr, phase, purpose) in KEYED.items()
    ]
    out += [{"name": n, "status": "RETIRED", "note": why} for n, why in RETIRED.items()]
    return out


# --- Phase 6: SEC EDGAR + Yahoo ownership ---
from .ownership import YahooOwnProvider
from .sec import SecProvider

ADAPTERS["sec"] = SecProvider
ADAPTERS["yahoo_own"] = YahooOwnProvider

# --- Phase 7: macro (FRED, Treasury curve, earnings and release calendars) ---
from .macro import (
    AgencyCalendarProvider,
    FredApiProvider,
    FredCsvProvider,
    NasdaqEarningsProvider,
    TreasuryProvider,
)

ADAPTERS.update({
    "fred": FredApiProvider, "fred_csv": FredCsvProvider, "treasury": TreasuryProvider,
    "nasdaq_earnings": NasdaqEarningsProvider, "agency_ics": AgencyCalendarProvider,
})
# FRED is built now: a real adapter (inactive without FRED_API_KEY), no longer a planned keyed entry.
KEYED.pop("fred", None)
_keyed_status_before_phase7 = keyed_status


def keyed_status(settings: Settings) -> list[dict]:
    out = _keyed_status_before_phase7(settings)
    if not settings.fred_api_key:
        out.insert(0, {
            "name": "fred", "status": "KEY REQUIRED",
            "note": "FRED API: series titles/units, MACRO search, ECO fallback. Values work keyless via fred_csv. "
            "Set FRED_API_KEY in .env (free).",
        })
    return out

# --- Phase 9: screener (EQS) and peers (COMP) ---
from .screener import NasdaqScreenerProvider, YahooPeersProvider

ADAPTERS.update({"nasdaq_screener": NasdaqScreenerProvider, "yahoo_peers": YahooPeersProvider})

# --- Phase 11: keyed rows come from the key store (APIKEYS) ---
from ..keys import KEY_SPECS

for _name in KEY_SPECS:
    KEYED.pop(_name, None)
_keyed_status_before_phase11 = _keyed_status_before_phase7


def keyed_status(settings: Settings, keys=None) -> list[dict]:
    """One row per KEY_SPECS provider (state from the key store, never the value), then planned and retired ones."""
    rows = []
    for st in keys.statuses() if keys is not None else []:
        spec = KEY_SPECS[st["name"]]
        if st["present"]:
            note = f"{spec.purpose}. Key from {st['source']}." + (f" {st['detail']}" if st["detail"] else "")
            rows.append({"name": spec.name, "status": st["state"], "note": note})
        else:
            rows.append({"name": spec.name, "status": "KEY REQUIRED",
                         "note": f"{spec.purpose}. Phase {spec.phase}. Set {spec.label} in APIKEYS."})
    return rows + _keyed_status_before_phase11(settings)
