"""The source hierarchy: for each kind of data, which provider answers first, and WHY.

The router (router.py) walks a capability's list from the top and takes the first source that (a) is switched on for the
symbol (`supports()`: a key is set, a login is valid, the symbol is one it covers) and (b) is healthy (circuit breaker).
Anything below is the fallback chain. So this table is the whole answer to "which source do I get?":

  - a source with a key but no coverage of the symbol is skipped (Upstox never sees AAPL),
  - a source without a key is skipped (costs nothing),
  - a failing or rate-limited source is skipped for a cool-down, then the next one answers and the panel says
    "fallback from <name>".

Rank by, in this order of weight: DEPTH (how far back, which instruments), FRESHNESS (real time or delayed), RATE LIMITS
(a source with a few calls per day must not sit above one that can feed a 50-row grid), and last SPEED (measured at run
time on the SOURCES screen; a slow source is demoted by the circuit breaker, not by this table).

Each entry records its reasons next to its position, and `tests/test_hierarchy.py` insists every entry has them. To add a
source: write the adapter, register it in providers/__init__.py, add one `Rank` here at the position it earns.
`config.yaml` `providers:` can still pin a capability's order by hand; that wins over this table (and says so in the log).
"""

from __future__ import annotations

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
             "Deepest Indian data with open interest; only on while a Kite login is valid"),
        Rank("upstox", "NSE, BSE (shares, Nifty 50, Bank Nifty, Sensex)", "minute and hourly candles from Jan 2022, daily and longer from Jan 2000",
             "real time", "free Analytics Token (1 year, read only); 50 requests/s, 500/minute",
             "Free, real time and far deeper intraday than Yahoo for Indian names; one token, no daily login"),
        Rank("binance_klines", "USDT pairs on Binance (spot and perpetuals)", "minute candles and up", "real time", "keyless public market data",
             "The exchange's own candles for the pairs it lists"),
        Rank("yahoo", "global shares, ETFs, indices, FX, futures", "daily back 20 years; 1 minute only 7 days, other minute candles 60 days, hourly 2 years",
             "up to 15 minutes late on some exchanges", "keyless but unofficial; bursts get blocked",
             "Widest coverage with no key, so it answers whatever the sources above do not cover"),
        Rank("frankfurter", "FX pairs the ECB publishes (EURUSD=X, USDINR=X, cross rates)", "daily only, back to 4 Jan 1999; no intraday, no high/low (open = high = low = close)",
             "one ECB reference rate per business day (about 16:00 CET)", "keyless; no quota stated, rate limited against abuse",
             "Deeper than Yahoo's FX history but only one fix a day, so it ranks below Yahoo and answers FX pairs only when Yahoo is down"),
        Rank("nasdaq", "US-listed stocks and ETFs", "daily only", "delayed", "keyless public website API, undocumented",
             "A second opinion for US daily bars when Yahoo is down"),
        Rank("nse_archive", "NSE shares (.NS)", "daily only, the last 250 sessions, unadjusted", "end of day", "keyless public archive files",
             "Last resort: only answers when everything above failed"),
    ),
    "quotes": (
        Rank("upstox", "NSE, BSE (shares, Nifty 50, Bank Nifty, Sensex)", "last price, day open/high/low, previous close", "real time",
             "free Analytics Token; 500 requests/minute",
             "Real-time Indian prices instead of Yahoo's delayed ones"),
        Rank("yahoo", "global shares, ETFs, indices, FX, futures", "last price, day range, 52-week range", "up to 15 minutes late on some exchanges",
             "keyless but unofficial", "Widest coverage with no key"),
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


def rank_of(provider: str) -> dict[str, dict]:
    """Where a provider sits in each capability it appears in: {capability: {"rank": 1, "of": 6, ...reasons}}."""
    out: dict[str, dict] = {}
    for cap, ranks in HIERARCHY.items():
        for i, r in enumerate(ranks, start=1):
            if r.provider == provider:
                out[cap] = {"rank": i, "of": len(ranks), "covers": r.covers, "depth": r.depth, "freshness": r.freshness,
                            "limits": r.limits, "why": r.why}
    return out
