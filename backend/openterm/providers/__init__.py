"""Provider catalog. Keyless adapters are always on; keyed ones appear on SOURCES with their status."""

import httpx

from ..config import Settings
from .base import Provider
from .fixtures import fixture_transport
from .nasdaq import NasdaqProvider
from .synthetic import SyntheticProvider
from .yahoo import YahooProvider

ADAPTERS: dict[str, type[Provider]] = {"yahoo": YahooProvider, "nasdaq": NasdaqProvider}

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
