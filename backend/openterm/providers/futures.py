"""Phase 14 step 7 sources, all keyless: Yahoo per-contract futures quotes (CT, WIRP), the CFTC legacy futures-only report (COT) and the
Federal Reserve FOMC calendar (WIRP). Parsing lives in derivs/fut_parse.py (pure)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from ..derivs import fut_parse as fp
from .base import Provider, ProviderError
from .http import BASE, UA

FUTURES_CONTRACT = "futures_contract"
COT_HISTORY = "cot_history"
COT_MARKETS = "cot_markets"
FOMC_DATES = "fomc_dates"
CFTC_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


class YahooFuturesProvider(Provider):
    name = "yahoo_futures"
    label = "Yahoo Finance futures contracts (unofficial)"
    capabilities = frozenset({FUTURES_CONTRACT})
    markets = "Per-contract CME/CBOT/NYMEX/COMEX futures quotes, delayed (one v8/chart call per contract; Yahoo returns no expiry date)"
    terms = "Unofficial v8/finance/chart endpoint; personal use. A contract Yahoo does not list is skipped, never invented."
    rate = (6.0, 20)
    timeout = 8.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "application/json"}

    async def futures_contract(self, symbol: str) -> dict:
        body = await self.get_json(f"{BASE}/v8/finance/chart/{symbol}", {"range": "5d", "interval": "1d"})
        out = fp.parse_contract(body, symbol, self.source)
        if out is None:
            raise ProviderError("not_found", f"NO CONTRACT {symbol}")
        return out


class CftcProvider(Provider):
    name = "cftc"
    label = "CFTC Commitments of Traders (public reporting)"
    capabilities = frozenset({COT_HISTORY, COT_MARKETS})
    markets = "Legacy futures-only report, weekly (as of Tuesday, released Friday)"
    terms = "Public Socrata API, no key. Data: U.S. Commodity Futures Trading Commission."
    rate = (2.0, 6)
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}

    async def cot_history(self, code: str, limit: int = 160) -> list[dict]:
        rows = await self.get_json(CFTC_URL, {"$select": fp.CFTC_FIELDS, "$where": f"cftc_contract_market_code='{code}'",
                                              "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": str(limit)})
        if not isinstance(rows, list) or not rows:
            raise ProviderError("not_found", f"NO COT ROWS FOR {code}")
        return rows

    async def cot_markets(self) -> list[dict]:
        since = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%d")
        rows = await self.get_json(CFTC_URL, {"$select": "market_and_exchange_names,cftc_contract_market_code",
                                              "$group": "market_and_exchange_names,cftc_contract_market_code",
                                              "$where": f"report_date_as_yyyy_mm_dd > '{since}'", "$limit": "2000"})
        if not isinstance(rows, list):
            raise ProviderError("unavailable", "unexpected answer")
        return rows


class FomcProvider(Provider):
    name = "fomc"
    label = "Federal Reserve FOMC calendar"
    capabilities = frozenset({FOMC_DATES})
    markets = "FOMC meeting decision dates, current and next year"
    terms = "Public web page, no key. Data: Board of Governors of the Federal Reserve System."
    rate = (1.0, 3)
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA, "Accept": "text/html"}

    async def fomc_dates(self) -> list[str]:
        html = (await self.get_bytes(FOMC_URL)).decode("utf-8", "replace")
        dates = fp.parse_fomc(html)
        if not dates:
            raise ProviderError("unavailable", "no FOMC dates found in the page")
        return dates
