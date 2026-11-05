"""Provider catalog. Keyless adapters are always on; keyed ones appear on SOURCES with their status."""

import httpx

from ..config import Settings
from .base import Provider
from .crypto import BinanceKlinesProvider, BinanceProvider, CoinGeckoProvider
from .fixtures import fixture_transport
from .nasdaq import NasdaqProvider
from .news import GdeltProvider, RssProvider, YahooRssProvider
from .synthetic import SyntheticProvider
from .yahoo import YahooProvider

ADAPTERS: dict[str, type[Provider]] = {
    "yahoo": YahooProvider, "nasdaq": NasdaqProvider, "rss": RssProvider, "yahoo_rss": YahooRssProvider,
    "gdelt": GdeltProvider, "coingecko": CoinGeckoProvider, "binance": BinanceProvider,
    "binance_klines": BinanceKlinesProvider,
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

# --- Phase 13: research (Yahoo quoteSummary modules for EE, EEO, ANR, MGMT, ETF info; dividend/split events) ---
from .research_yahoo import YahooResearchProvider

ADAPTERS["yahoo_research"] = YahooResearchProvider
from .finra import FinraProvider
from .research_nasdaq import NasdaqResearchProvider

ADAPTERS.update({"nasdaq_research": NasdaqResearchProvider, "finra": FinraProvider})
from .sec_funds import Sec13fProvider, SecNportProvider

ADAPTERS.update({"sec_nport": SecNportProvider, "sec_13f": Sec13fProvider})
# Keyed (APIKEYS): inert without a key (supports() is false), so they are always built and appear on SOURCES.
from .alpaca import AlpacaProvider
from .finnhub import FinnhubProvider

ADAPTERS.update({"finnhub": FinnhubProvider, "alpaca": AlpacaProvider})

# --- Phase 14: options (Yahoo chains; Tradier sandbox is a keyed fallback, inert without a token) ---
from .options_yahoo import YahooOptionsProvider
from .tradier import TradierProvider

ADAPTERS.update({"yahoo_options": YahooOptionsProvider, "tradier": TradierProvider})

# --- Phase 14 step 5: crypto options (Deribit public API, no key) ---
from .deribit import DeribitProvider

ADAPTERS["deribit"] = DeribitProvider

# --- Phase 14 step 6: rates views (public data, no key) ---
from .boc import BocProvider
from .boe import BoeProvider
from .ecb import EcbProvider
from .fred_oas import FredOasProvider
from .mof import MofProvider
from .treasurydirect import TreasuryDirectProvider

ADAPTERS.update({"ecb": EcbProvider, "boe": BoeProvider, "boc": BocProvider, "mof": MofProvider, "fred_oas": FredOasProvider,
                 "treasurydirect": TreasuryDirectProvider})

# --- Phase 14 step 7: futures, COT and FOMC dates (public data, no key) ---
from .futures import CftcProvider, FomcProvider, YahooFuturesProvider

ADAPTERS.update({"yahoo_futures": YahooFuturesProvider, "cftc": CftcProvider, "fomc": FomcProvider})

# --- Phase 15 step 4: Fama-French factors for FACT (Ken French library, no key) ---
from .kenfrench import KenFrenchProvider

ADAPTERS["kenfrench"] = KenFrenchProvider

# --- Phase 15 steps 6-7: Zerodha Kite Connect bars (read-only; inert until a key is set and a login is made) ---
from .kite import KiteProvider

ADAPTERS["kite"] = KiteProvider

# --- Source hierarchy step 1: Upstox (free read-only Analytics Token; inert without one) ---
from .upstox import UpstoxProvider

ADAPTERS["upstox"] = UpstoxProvider

# --- Phase 19 (keyless): SECF identifier mapping ---
from .openfigi import OpenFigiProvider

ADAPTERS["openfigi"] = OpenFigiProvider
from .nager import NagerProvider
from .policy_rates import PolicyRatesProvider
from .worldstats import DbnomicsProvider, WorldBankProvider

ADAPTERS.update({"nager": NagerProvider, "worldbank": WorldBankProvider, "dbnomics": DbnomicsProvider, "policy_rates": PolicyRatesProvider})
from .nws import NwsProvider
from .openmeteo import OpenMeteoProvider

ADAPTERS.update({"openmeteo": OpenMeteoProvider, "nws": NwsProvider})

# --- Phase 19 step 8: PRED (prediction markets, read only) ---
from .kalshi import KalshiMarketsProvider
from .polymarket import PolymarketProvider

ADAPTERS.update({"polymarket": PolymarketProvider, "kalshi": KalshiMarketsProvider})

# --- Phase 19 step 9: non-US zero-key data (NSE archive end-of-day bars, AMFI mutual fund NAV) ---
from .amfi import AmfiProvider
from .nse_archive import NseArchiveProvider

ADAPTERS.update({"nse_archive": NseArchiveProvider, "amfi": AmfiProvider})

# --- Phase 19 step 7: crypto depth, funding, liquidations, stablecoins, yields (Binance first, OKX when Binance answers 451) ---
from .binance_deriv import BinanceDerivProvider
from .defillama import DefiLlamaProvider
from .okx import OkxProvider

ADAPTERS.update({"binance_deriv": BinanceDerivProvider, "okx": OkxProvider, "defillama": DefiLlamaProvider})

# --- Trade + US macro family (free keys, read only): TRADE and USMAC. The key is read per call, so nothing to wire in main.on_key_change ---
from .tradeus import BeaProvider, BlsProvider, CensusProvider, ComtradeProvider

ADAPTERS.update({"comtrade": ComtradeProvider, "bls": BlsProvider, "bea": BeaProvider, "census": CensusProvider})

# --- SHIP: IMF PortWatch (keyless) ---
from .portwatch import PortWatchProvider

ADAPTERS.update({"portwatch": PortWatchProvider})

# --- More free read-only sources: Frankfurter (ECB FX fixes, keyless), UK Companies House, Marketaux news, Etherscan (free keys; inert until set) ---
from .companies_house import CompaniesHouseProvider
from .etherscan import EtherscanProvider
from .frankfurter import FrankfurterProvider
from .marketaux import MarketauxProvider

ADAPTERS.update({"frankfurter": FrankfurterProvider, "companies_house": CompaniesHouseProvider,
                 "marketaux": MarketauxProvider, "etherscan": EtherscanProvider})
