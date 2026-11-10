"""The source hierarchy: for each kind of data, which provider answers first, and WHY.

The router (router.py) walks a capability's list from the top and takes the first source that (a) is switched on for the
symbol (`supports()`: a key is set, a login is valid, the symbol is one it covers) and (b) is healthy (circuit breaker).
Anything below is the fallback chain. So this table is the whole answer to "which source do I get?":

  - a source with a key but no coverage of the symbol is skipped (Kite never sees AAPL),
  - a source without a key is skipped (costs nothing),
  - a failing or rate-limited source is skipped for a cool-down, then the next one answers and the panel says
    "fallback from <name>".

Rank by, in this order of weight: DEPTH (how far back, which instruments), FRESHNESS (real time or delayed), RATE LIMITS
(a source with a few calls per day must not sit above one that can feed a 50-row grid), and last SPEED (measured at run
time on the SOURCES screen; a slow source is demoted by the circuit breaker, not by this table).

Each entry records its reasons next to its position, and `tests/test_hierarchy.py` insists every entry has them. To add a
source: write the adapter, register it in providers/__init__.py, add one `Rank` here at the position it earns.
Every OTHER capability's default order is the `DEFAULT_ORDER` table further down (quotes and history point back at the ranks).
`config.yaml` `providers:` can still pin a capability's order by hand; that wins over this table (and says so in the log).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass


@dataclass(frozen=True)
class Rank:
    provider: str
    covers: str  # which symbols / markets it answers for
    depth: str  # how far back, which intervals
    freshness: str  # real time or delayed
    limits: str  # rate limits and who pays
    why: str  # why it sits at this position


HIERARCHY: dict[str, tuple[Rank, ...]] = {
    "history": (
        Rank("kite", "NSE, BSE, NFO, MCX", "1 minute to daily with open interest", "real time",
             "3 requests/s; your own paid Kite Connect app and a login each trading day",
             "Exchange-direct bars with open interest, far deeper intraday than Yahoo for NSE/BSE/F&O/MCX; on while a Kite login exists, and an expired login falls to Yahoo with the reason shown"),
        Rank("binance_klines", "USDT pairs on Binance (spot and perpetuals)", "minute candles and up", "real time", "keyless public market data",
             "The exchange's own candles for the pairs it lists"),
        Rank("yahoo", "global shares, ETFs, indices, FX, futures", "daily back 20 years; 1 minute only 7 days, other minute candles 60 days, hourly 2 years",
             "up to 15 minutes late on some exchanges", "keyless but unofficial; bursts get blocked",
             "Widest coverage with no key, so it answers whatever the sources above do not cover"),
        # The four keyed free-tier sources sit directly below Yahoo and above every other keyless fallback. With no key set they are skipped
        # (supports() is false: nothing changes in the chain). With a key they only answer when Yahoo (or Kite/Binance above) failed or could
        # not serve the request: none of them can sit above Yahoo because their quotas (8 a minute, 5 a minute, 250 or 25 a day) cannot feed a
        # chart or a 50-row grid, and Yahoo needs no key. Among themselves: depth first, then limits, then freshness.
        Rank("twelvedata", "US shares and ETFs, FX pairs, and shares on NSE, BSE, LSE, TSX, HKEX, TSE, Xetra, Euronext and other mapped exchanges",
             "daily and 1 minute to 1 hour candles, up to 5000 bars per call (about 20 years of daily, about 89 days of 5-minute candles)",
             "as the plan delivers it (free plans can be delayed)", "free key: 8 credits a minute, 800 a day, 1 credit per call (per provider docs)",
             "First keyed fallback: the only keyed source that covers non-US exchanges and FX, deepest daily history, 800 calls a day; mapped suffixes only, so an unmapped exchange is skipped, never mis-resolved"),
        Rank("polygon", "US shares and ETFs", "daily, weekly, monthly and minute candles, about 2 years on the free plan; minute candles include pre- and after-market",
             "end of day on the free plan", "free key: 5 requests a minute (per provider docs)",
             "Second keyed fallback for US names: official exchange-sourced bars and 2 years of minute candles, but US only and a call every 12 seconds"),
        Rank("fmp", "US shares and ETFs", "daily candles only, about 5 years on the free plan", "end of day on the free plan",
             "free key: 250 requests a day (per provider docs)",
             "Third: daily bars only (intraday is a paid plan), so it cannot serve a 1D or 5D chart, and its quota is shared with FA statements"),
        Rank("alphavantage", "US shares and ETFs", "daily, the last 100 sessions; intraday candles over the last 100 bars (can be premium)",
             "end of day (latest trading day)", "free key: 25 requests a day and 1 a second (per provider docs)",
             "Last of the keyed sources: 25 calls a day is a few charts, so it only answers when everything above failed"),
        Rank("coinbase", "crypto pairs against USD, USDT, EUR, GBP written BTC-USD / ETH-USDT (a USD pair is not a USDT pair: the quote is shown)",
             "1 minute, 5 minutes, 15 minutes, 1 hour, 1 day; paged back up to 4,000 candles per request (the API goes back to 2015); no 2m, 30m, weekly or monthly",
             "real time (the forming candle is included)", "keyless; about 10 requests a second per IP, a long range is up to 14 calls at once",
             "Second exchange for crypto when Binance is blocked or down: below Yahoo because Yahoo's BTC-USD is deeper (20 years of daily bars), above Kraken because it can be paged back and Kraken keeps only the last 720 candles"),
        Rank("kraken", "crypto pairs against USD, USDT, EUR, GBP written BTC-USD / ETH-USDT (a USD pair is not a USDT pair: the quote is shown)",
             "only the last 720 candles of each length: 12 hours of 1 minute, 2.5 days of 5 minutes, 30 days of hourly, 720 days of daily; weekly since 2013; no 2m, 90m or monthly",
             "real time (the forming candle is included)", "keyless; about 1 request a second",
             "Third choice for crypto candles: a second exchange when Binance and Coinbase fail, but shallow, so a long range gets a depth error"),
        Rank("frankfurter", "FX pairs the ECB publishes (EURUSD=X, USDINR=X, cross rates)", "daily only, back to 4 Jan 1999; no intraday, no high/low (open = high = low = close)",
             "one ECB reference rate per business day (about 16:00 CET)", "keyless; no quota stated, rate limited against abuse",
             "Deeper than Yahoo's FX history but only one fix a day, so it ranks below Yahoo and answers FX pairs only when Yahoo is down"),
        Rank("nasdaq", "US-listed stocks and ETFs", "daily only", "delayed", "keyless public website API, undocumented",
             "A second opinion for US daily bars when Yahoo is down"),
        Rank("nse_archive", "NSE shares (.NS)", "daily only, the last 250 sessions, unadjusted", "end of day", "keyless public archive files",
             "Last resort: only answers when everything above failed"),
    ),
    "quotes": (
        Rank("kite", "NSE, BSE, NFO, BFO, MCX, CDS (shares, indices, futures, options)", "last price, day open/high/low, previous close, volume",
             "real time", "10 requests/s, up to 500 instruments per call; your own paid Kite Connect app and a login each trading day",
             "Real-time exchange prices instead of Yahoo's delayed ones for the symbols Kite covers"),
        Rank("yahoo", "global shares, ETFs, indices, FX, futures", "last price, day range, 52-week range", "up to 15 minutes late on some exchanges",
             "keyless but unofficial", "Widest coverage with no key"),
        # Keyed free-tier fallbacks below Yahoo: see the note in "history". Among themselves for a quote: freshness first (a live-ish price beats
        # a previous close), then coverage, then limits. All skipped with no key.
        Rank("twelvedata", "US shares and ETFs, FX pairs, and shares on NSE, BSE, LSE, TSX, HKEX, TSE, Xetra, Euronext and other mapped exchanges",
             "last price, day range, 52-week range, previous close", "as the plan delivers it (free plans can be delayed)",
             "free key: 8 credits a minute, 800 a day, 1 credit per symbol (per provider docs); at most 8 symbols per call here",
             "First keyed fallback: widest coverage (non-US and FX), a price with day and 52-week ranges, 800 calls a day"),
        Rank("fmp", "US shares and ETFs", "last price, day range, 52-week range, previous close", "delayed or end of day on the free plan",
             "free key: 250 requests a day (per provider docs); at most 5 symbols per call here",
             "Second: a full quote with ranges for US names; US only and a smaller daily quota"),
        Rank("polygon", "US shares and ETFs", "the PREVIOUS session's open, high, low, close and volume (no live price on the free plan)",
             "end of day: the quote is a session old", "free key: 5 requests a minute (per provider docs)",
             "Third: official bars but not a live price (its market time shows the session), so it only answers when the two above cannot"),
        Rank("alphavantage", "US shares and ETFs", "last price, day range, previous close, latest trading day (a date, no time)",
             "end of day", "free key: 25 requests a day and 1 a second (per provider docs); at most 3 symbols per call here",
             "Last keyed: 25 calls a day"),
        Rank("frankfurter", "FX pairs the ECB publishes (EURUSD=X, USDINR=X, cross rates)", "last ECB reference rate and the one before it",
             "once a day (the fix date is the quote's time, so a weekend quote is up to 3 days old)", "keyless; no quota stated, rate limited against abuse",
             "Not live, so it ranks below Yahoo and only answers FX pairs when Yahoo is down"),
        Rank("nasdaq", "US-listed stocks and ETFs", "last price, day range", "delayed", "keyless public website API, undocumented",
             "Fallback for US names"),
    ),
}


def order_for(capability: str) -> list[str]:
    """Provider names for a capability, best first."""
    return [r.provider for r in HIERARCHY[capability]]


# ---------------------------------------------------------------------------------------------------------------------
# The default order for EVERY capability: capability name -> provider names, best first. The router walks each list from the
# top (see the module docstring). This is the one place to read or change an order:
#   - `quotes` and `history` are the two ranked capabilities above (HIERARCHY holds the reasons for their positions);
#   - every other capability is a plain literal list here, grouped by what it serves, with its reason in the comment.
# `config.yaml` `providers:` can still pin a capability by hand (see `build_order`), but the file no longer repeats these.
# A provider named here must exist in `providers.ADAPTERS` and declare the capability: `tests/test_hierarchy.py` checks both.
# ---------------------------------------------------------------------------------------------------------------------
DEFAULT_ORDER: dict[str, list[str]] = {
    # Market data. quotes/history: ranked above, with reasons.
    "quotes": order_for("quotes"),
    "history": order_for("history"),
    "search": ["yahoo", "twelvedata", "polygon", "fmp"],  # keyed free-tier fallbacks, inert without a key; US names or mapped exchanges only
    "profile": ["yahoo", "nasdaq"],
    "movers": ["nasdaq"],
    "screener": ["nasdaq_screener"],
    "peers": ["yahoo_peers"],
    "figi": ["openfigi"],  # SECF identifier mapping
    "mfnav": ["amfi"],  # AMFI NAV for the SECF fund rows
    # News. The keyed sources (finnhub, alpaca, marketaux) sit after the keyless ones and are inert until a key is set in APIKEYS.
    "news_top": ["rss", "finnhub", "alpaca", "marketaux"],
    "news_symbol": ["yahoo_rss", "finnhub", "alpaca", "marketaux", "gdelt"],
    "news_keyword": ["gdelt"],
    "news_pool": ["rss"],  # the curated feed table (providers/news_feeds.py)
    # Crypto. kraken and coinbase: keyless second exchanges for when Binance is blocked or down.
    "crypto": ["coingecko", "binance", "kraken", "coinbase"],
    "crypto_options": ["deribit"],
    # Crypto depth (Binance first; OKX when Binance fails, e.g. HTTP 451), funding, liquidations (OKX only), DefiLlama
    "crypto_depth": ["binance_deriv", "okx", "kraken", "coinbase"],
    "crypto_funding": ["binance_deriv", "okx"],
    "crypto_funding_detail": ["binance_deriv", "okx"],
    "crypto_liq": ["okx"],
    "stablecoins": ["defillama"],
    "yields": ["defillama"],
    "chain": ["etherscan"],  # ADDR: one keyed source; no key = KEY REQUIRED, never fake data
    # SEC / ownership
    # SEC EDGAR first: official, free, keyless and deep (12 annual / 16 quarterly periods). FMP then Alpha Vantage only when SEC cannot answer
    # (down, or a ticker it lacks): FMP gives annual statements (quarterly is paid) in 3 calls of 250 a day, Alpha Vantage both views in 3 of 25.
    "fundamentals": ["sec", "fmp", "alphavantage"],
    "filings": ["sec"],
    "insiders": ["sec", "yahoo_own"],
    "holders": ["yahoo_own"],
    # Research functions (keyless first; finnhub is keyed and inert without a key)
    "estimates": ["yahoo_research"],
    "ratings": ["yahoo_research", "finnhub"],
    "surprises": ["yahoo_research", "finnhub"],
    "officers": ["yahoo_research"],
    "keystats": ["yahoo_research"],
    "fund_info": ["yahoo_research"],
    "corp_events": ["yahoo_research"],
    "dividends": ["nasdaq_research", "yahoo_research"],
    "splits": ["yahoo_research"],
    "ipo": ["nasdaq_research"],
    "short_interest": ["nasdaq_research", "yahoo_research"],
    "short_volume": ["finra"],
    "etf_holdings": ["sec_nport"],
    "manager_13f": ["sec_13f"],
    "earnings_history": ["nasdaq_research"],  # GP event markers
    # Macro. fred = official API, only active with FRED_API_KEY; fred_csv = keyless CSV.
    "fred_series": ["fred", "fred_csv"],
    "fred_search": ["fred"],
    "yield_curve": ["treasury", "fred_csv"],
    "earnings": ["nasdaq_earnings"],
    "eco_calendar": ["agency_ics", "fred"],
    # Options and rates views
    "option_chain": ["yahoo_options", "tradier"],  # Tradier is a keyed fallback
    "curve_eur": ["ecb"],
    "curve_gbp": ["boe"],
    "curve_cad": ["boc"],
    "curve_jpy": ["mof"],
    "credit_spreads": ["fred_oas"],
    "auctions": ["treasurydirect"],
    # Futures, COT, FOMC, Fama-French factors
    "futures_contract": ["yahoo_futures"],
    "cot_history": ["cftc"],
    "cot_markets": ["cftc"],
    "fomc_dates": ["fomc"],
    "factors": ["kenfrench"],
    # Trade + US macro family (free keys)
    "comtrade": ["comtrade"],
    "bls": ["bls"],
    "bea": ["bea"],
    "census": ["census"],
    # World statistics, holidays, policy rates
    "holidays": ["nager"],
    "worldstats": ["worldbank", "dbnomics"],
    "worldstats_latest": ["worldbank"],
    "worldstats_countries": ["worldbank"],
    "worldstats_dbn": ["dbnomics"],
    "worldstats_search": ["dbnomics"],  # DBSRCH: find DBnomics datasets and series by words
    "policy_rates": ["policy_rates"],
    # Weather
    "weather_geocode": ["openmeteo"],
    "weather_forecast": ["openmeteo"],
    "nws_alerts": ["nws"],
    # Shipping, ports, maps, live positions
    "shipping_chokepoints": ["portwatch"],
    "ports_activity": ["portwatch"],  # PORTS: same keyless IMF PortWatch provider, daily port calls
    "geo_quakes": ["usgs"],  # MAP layers (keyless)
    "geo_events": ["eonet"],
    "ais": ["aisstream"],
    "flights": ["opensky"],
    # Mutual funds (MFapi.in)
    "mf_search": ["mfapi"],
    "mf_nav": ["mfapi"],
    # UK Companies House: one keyed source; no key = KEY REQUIRED
    "companies_house": ["companies_house"],
    # US government: USASP / FEDREG (keyless) and FEC / CONGRESS (free api.data.gov keys; no key = KEY REQUIRED, never fake data)
    "usaspending": ["usaspending"],
    "federal_register": ["federalregister"],
    "openfec": ["openfec"],
    "congress_gov": ["congressgov"],
    # Prediction markets (PRED)
    "pred_poly": ["polymarket"],
    "pred_poly_market": ["polymarket"],
    "pred_poly_history": ["polymarket"],
    "pred_kalshi": ["kalshi"],
    "pred_kalshi_market": ["kalshi"],
    "pred_kalshi_candles": ["kalshi"],
}

# Test data: with OPENTERM_SYNTHETIC=1 the SYN0000-SYN9999 provider answers for these two capabilities (last in line, so real
# sources still answer real tickers). Must equal SyntheticProvider.capabilities; a test checks it.
SYNTHETIC_CAPABILITIES = ("quotes", "history")


def build_order(pinned: dict, synthetic: bool) -> dict[str, list[str]]:
    """The order the router uses: DEFAULT_ORDER, then any hand-pinned `providers:` entries from config.yaml (they win).

    A pin on a ranked capability (quotes, history) is logged, because it also hides every source added to HIERARCHY later.
    A pin that names an unknown provider is not repaired: the router finds no such source and the panel shows the failure.
    """
    order = {**DEFAULT_ORDER, **pinned}
    for cap in HIERARCHY:
        if cap in pinned and list(pinned[cap]) != order_for(cap):
            logging.getLogger("openterm").warning(
                "config.yaml pins the %s order %s: the source hierarchy %s is ignored", cap, pinned[cap], order_for(cap))
    if synthetic:
        order = {k: [*v, "synthetic"] if k in SYNTHETIC_CAPABILITIES else v for k, v in order.items()}
    return order


def rank_of(provider: str) -> dict[str, dict]:
    """Where a provider sits in each capability it appears in: {capability: {"rank": 1, "of": 6, ...reasons}}."""
    out: dict[str, dict] = {}
    for cap, ranks in HIERARCHY.items():
        for i, r in enumerate(ranks, start=1):
            if r.provider == provider:
                out[cap] = {"rank": i, "of": len(ranks), "covers": r.covers, "depth": r.depth, "freshness": r.freshness,
                            "limits": r.limits, "why": r.why}
    return out
