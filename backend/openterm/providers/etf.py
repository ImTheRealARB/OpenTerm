"""FSRC (ETF screener) sources: the list of US ETFs, and one fund's fee / size / category.

Two small adapters, each doing one job, so the router can name the one that failed:

  * `NasdaqTraderProvider` (capability `etf_universe`)  the Nasdaq Trader symbol directory, one ~1 MB text file that lists every
    US-traded security. We keep the ETF lines. Free, keyless, refreshed each trading day.
  * `YahooFundsProvider` (capability `fund_profile`)  Yahoo's `quoteSummary` modules `fundProfile` + `summaryDetail` for ONE
    ETF: expense ratio, total assets, category, fund family. It is a subclass of `YahooOwnProvider` only to reuse that class's
    cookie + crumb flow (the same login-less handshake a browser does), under its own name so SOURCES shows its health alone.
    Unofficial endpoint: it can change or block without notice.

Pacing: fetching ~5,800 profiles is a long job, so this provider has its OWN, slower token bucket (3 calls a second, below the
4 a second Yahoo's chart provider uses) and lets a call WAIT for its slot (`max_wait`) instead of failing the way a one-off request
does. `etf_screen.py` only limits how many calls are in flight; the bucket sets the speed. In fixture mode the bucket is wide open.
"""

from __future__ import annotations

from typing import ClassVar

from ..ratelimit import TokenBucket
from .base import Provider, ProviderError
from .etf_parse import fund_from_summary, parse_symbol_file
from .http import UA
from .ownership import YahooOwnProvider

ETF_UNIVERSE = "etf_universe"
FUND_PROFILE = "fund_profile"

SYMBOL_FILE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
# The two quoteSummary modules FSRC reads. Kept in one place because the fixture router matches on this exact string.
FUND_MODULES = "fundProfile,summaryDetail"


class NasdaqTraderProvider(Provider):
    name = "nasdaq_trader"
    label = "Nasdaq Trader symbol directory"
    capabilities = frozenset({ETF_UNIVERSE})
    markets = "Every US-traded ETF (NYSE, NYSE Arca, NYSE American, Nasdaq, Cboe BZX): about 5,800 symbols, one daily file"
    terms = "Public symbol directory published by Nasdaq Trader; personal use. Names only: no prices, fees or sizes."
    rate = (0.2, 2)  # one file a few times a day is plenty
    max_wait = 1.0
    timeout = 30.0  # about 1 MB
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "text/plain, */*"}

    async def etf_universe(self) -> dict:
        raw = await self.get_bytes(SYMBOL_FILE_URL)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ProviderError("unavailable", "symbol file is not UTF-8") from e
        etfs, stamp = parse_symbol_file(text)
        if not etfs:
            raise ProviderError("not_found", "symbol file lists no ETFs")
        return {"etfs": etfs, "file_stamp": stamp, "source": self.source, "as_of": self.now()}

    async def probe(self) -> None:
        await self.etf_universe()


class YahooFundsProvider(YahooOwnProvider):
    name = "yahoo_funds"
    label = "Yahoo Finance fund profiles (unofficial)"
    capabilities = frozenset({FUND_PROFILE})
    markets = "US-listed ETFs and funds: expense ratio, total assets, category, fund family"
    terms = "Unofficial quoteSummary modules; personal use. Fees and assets are as Yahoo reports them (fund companies update them slowly)."
    rate = (3.0, 3)
    max_wait = 6.0  # a call queues for its slot instead of failing: the engine starts a few at once and the bucket spreads them

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.fixture:
            self.bucket = TokenBucket(1000.0, 1000)  # recorded answers need no pacing

    async def fund_profile(self, symbol: str) -> dict:
        """{"fee": percent, "aum": dollars, "category", "family"} for one ETF; `not_found` when Yahoo has no fund data for it."""
        result = await self._summary(symbol, FUND_MODULES)
        row = fund_from_summary(result)
        if row is None:
            raise ProviderError("not_found", "no fund data")
        return row

    async def probe(self) -> None:
        await self.fund_profile("SPY")
