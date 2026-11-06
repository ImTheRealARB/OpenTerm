"""Provider catalog. Keyless adapters are always on; keyed ones appear on SOURCES with their status.

`ADAPTERS` is the list of every source the app can build (name -> class). Which of them answers first for a given kind of data
is a different question, answered in one place: `providers/hierarchy.py` (`DEFAULT_ORDER`). To add a source, write the adapter,
import it here, add it to `ADAPTERS`, and name it in `DEFAULT_ORDER` for each capability it serves.
"""

import httpx

from ..config import Settings
from ..keys import KEY_SPECS
from .aisstream import AisStreamProvider
from .alpaca import AlpacaProvider
from .amfi import AmfiProvider
from .base import Provider
from .binance_deriv import BinanceDerivProvider
from .boc import BocProvider
from .boe import BoeProvider
from .coinbase import CoinbaseProvider
from .companies_house import CompaniesHouseProvider
from .crypto import BinanceKlinesProvider, BinanceProvider, CoinGeckoProvider
from .defillama import DefiLlamaProvider
from .deribit import DeribitProvider
from .ecb import EcbProvider
from .etherscan import EtherscanProvider
from .finnhub import FinnhubProvider
from .finra import FinraProvider
from .fixtures import fixture_transport
from .frankfurter import FrankfurterProvider
from .fred_oas import FredOasProvider
from .futures import CftcProvider, FomcProvider, YahooFuturesProvider
from .geo import EonetProvider, UsgsProvider
from .kalshi import KalshiMarketsProvider
from .kenfrench import KenFrenchProvider
from .kite import KiteProvider
from .kraken import KrakenProvider
from .macro import (
    AgencyCalendarProvider,
    FredApiProvider,
    FredCsvProvider,
    NasdaqEarningsProvider,
    TreasuryProvider,
)
from .marketaux import MarketauxProvider
from .mfapi import MfapiProvider
from .mof import MofProvider
from .nager import NagerProvider
from .nasdaq import NasdaqProvider
from .news import GdeltProvider, RssProvider, YahooRssProvider
from .nse_archive import NseArchiveProvider
from .nws import NwsProvider
from .okx import OkxProvider
from .openfigi import OpenFigiProvider
from .openmeteo import OpenMeteoProvider
from .opensky import OpenSkyProvider
from .options_yahoo import YahooOptionsProvider
from .ownership import YahooOwnProvider
from .policy_rates import PolicyRatesProvider
from .polymarket import PolymarketProvider
from .portwatch import PortWatchProvider
from .research_nasdaq import NasdaqResearchProvider
from .research_yahoo import YahooResearchProvider
from .screener import NasdaqScreenerProvider, YahooPeersProvider
from .sec import SecProvider
from .sec_funds import Sec13fProvider, SecNportProvider
from .synthetic import SyntheticProvider
from .tradeus import BeaProvider, BlsProvider, CensusProvider, ComtradeProvider
from .tradier import TradierProvider
from .treasurydirect import TreasuryDirectProvider
from .usgov import CongressProvider, FederalRegisterProvider, OpenFecProvider, UsaSpendingProvider
from .worldstats import DbnomicsProvider, WorldBankProvider
from .yahoo import YahooProvider

# Every source the app can build. The ORDER of this dict is the order of the rows on SOURCES, so keep it stable.
ADAPTERS: dict[str, type[Provider]] = {
    # Core market data, news and crypto
    "yahoo": YahooProvider, "nasdaq": NasdaqProvider, "rss": RssProvider, "yahoo_rss": YahooRssProvider,
    "gdelt": GdeltProvider, "coingecko": CoinGeckoProvider, "binance": BinanceProvider,
    "binance_klines": BinanceKlinesProvider,
    # SEC EDGAR filings and Yahoo ownership
    "sec": SecProvider, "yahoo_own": YahooOwnProvider,
    # Macro: FRED (official API needs a key, CSV is keyless), Treasury curve, earnings and release calendars
    "fred": FredApiProvider, "fred_csv": FredCsvProvider, "treasury": TreasuryProvider,
    "nasdaq_earnings": NasdaqEarningsProvider, "agency_ics": AgencyCalendarProvider,
    # Screener (EQS) and peers (COMP)
    "nasdaq_screener": NasdaqScreenerProvider, "yahoo_peers": YahooPeersProvider,
    # Research functions: Yahoo quoteSummary modules, Nasdaq calendars, FINRA short volume, SEC funds (N-PORT, 13F)
    "yahoo_research": YahooResearchProvider, "nasdaq_research": NasdaqResearchProvider, "finra": FinraProvider,
    "sec_nport": SecNportProvider, "sec_13f": Sec13fProvider,
    # Keyed (APIKEYS): inert without a key (supports() is false), so they are always built and appear on SOURCES
    "finnhub": FinnhubProvider, "alpaca": AlpacaProvider,
    # Options chains (Yahoo; Tradier is a keyed fallback) and crypto options (Deribit)
    "yahoo_options": YahooOptionsProvider, "tradier": TradierProvider, "deribit": DeribitProvider,
    # Rates views (public data, no key)
    "ecb": EcbProvider, "boe": BoeProvider, "boc": BocProvider, "mof": MofProvider, "fred_oas": FredOasProvider,
    "treasurydirect": TreasuryDirectProvider,
    # Futures, COT and FOMC dates; Fama-French factors
    "yahoo_futures": YahooFuturesProvider, "cftc": CftcProvider, "fomc": FomcProvider, "kenfrench": KenFrenchProvider,
    # Zerodha Kite Connect bars (read-only; inert until a key is set and a login is made)
    "kite": KiteProvider,
    # SECF identifier mapping, holidays, world statistics, policy rates, weather
    "openfigi": OpenFigiProvider, "nager": NagerProvider, "worldbank": WorldBankProvider, "dbnomics": DbnomicsProvider,
    "policy_rates": PolicyRatesProvider, "openmeteo": OpenMeteoProvider, "nws": NwsProvider,
    # PRED: prediction markets (read only)
    "polymarket": PolymarketProvider, "kalshi": KalshiMarketsProvider,
    # Non-US zero-key data: NSE archive end-of-day bars, AMFI mutual fund NAV
    "nse_archive": NseArchiveProvider, "amfi": AmfiProvider,
    # Crypto depth, funding, liquidations, stablecoins, yields (Binance first, OKX when Binance answers 451)
    "binance_deriv": BinanceDerivProvider, "okx": OkxProvider, "defillama": DefiLlamaProvider,
    # Trade + US macro family (free keys, read only): TRADE and USMAC. The key is read per call, so nothing to wire in main.on_key_change
    "comtrade": ComtradeProvider, "bls": BlsProvider, "bea": BeaProvider, "census": CensusProvider,
    # SHIP and PORTS: IMF PortWatch (keyless); MF: MFapi.in Indian mutual fund NAV (keyless community service)
    "portwatch": PortWatchProvider, "mfapi": MfapiProvider,
    # More free read-only sources: Frankfurter (ECB FX fixes, keyless), UK Companies House, Marketaux news, Etherscan (free keys; inert until set)
    "frankfurter": FrankfurterProvider, "companies_house": CompaniesHouseProvider,
    "marketaux": MarketauxProvider, "etherscan": EtherscanProvider,
    # AIS: live ship positions (AISstream, free key). `websockets` is imported only when a listen starts
    "aisstream": AisStreamProvider,
    # MAP: keyless geo feeds (USGS earthquakes, NASA EONET events)
    "usgs": UsgsProvider, "eonet": EonetProvider,
    # Second crypto exchanges, keyless: Kraken and Coinbase Exchange (board, candles, order book) for when Binance is blocked or down
    "kraken": KrakenProvider, "coinbase": CoinbaseProvider,
    # US government data: USASP (USASpending) and FEDREG (Federal Register) keyless; FEC (OpenFEC) and CONGRESS (Congress.gov) with a free api.data.gov key
    "usaspending": UsaSpendingProvider, "federalregister": FederalRegisterProvider, "openfec": OpenFecProvider, "congressgov": CongressProvider,
    # FLT: live aircraft from the OpenSky Network (works with no key; an optional free account raises the daily credits)
    "opensky": OpenSkyProvider,
}

# Keyed providers with a SOURCES row but no adapter yet: name -> (settings attribute, phase, purpose). Providers that DO have a
# key in the key store (KEY_SPECS: finnhub, fmp, fred, ...) are listed from there instead, so none of them belongs here.
KEYED = {
    "twelvedata": ("twelvedata_api_key", 3, "Quotes/history fallback incl. some non-US"),
    "alphavantage": ("alphavantage_api_key", 6, "Fundamentals fallback"),
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
        out: dict[str, Provider] = {name: cls(fx, source=f"{name}:fixture", fixture=True) for name, cls in ADAPTERS.items()}
    else:
        out = {name: cls(http) for name, cls in ADAPTERS.items()}
    if synthetic:
        out["synthetic"] = SyntheticProvider()
    return out


def keyed_status(settings: Settings, keys=None) -> list[dict]:
    """The SOURCES rows for keyed and retired providers, in this order: one row per KEY_SPECS provider (state from the key
    store, never the value), then the planned ones with no adapter yet, then the retired ones."""
    rows = []
    for st in keys.statuses() if keys is not None else []:
        spec = KEY_SPECS[st["name"]]
        if st["present"]:
            note = f"{spec.purpose}. Key from {st['source']}." + (f" {st['detail']}" if st["detail"] else "")
            rows.append({"name": spec.name, "status": st["state"], "note": note})
        else:
            rows.append({"name": spec.name, "status": "KEY REQUIRED",
                         "note": f"{spec.purpose}. Phase {spec.phase}. Set {spec.label} in APIKEYS."})
    for name, (attr, phase, purpose) in KEYED.items():
        has_key = bool(getattr(settings, attr))
        rows.append({
            "name": name,
            "status": "NOT BUILT" if has_key else "KEY REQUIRED",
            "note": f"{purpose}. Phase {phase}." + ("" if has_key else f" Set {attr.upper()} in .env."),
        })
    rows += [{"name": n, "status": "RETIRED", "note": why} for n, why in RETIRED.items()]
    return rows
