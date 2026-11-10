"""Financial Modeling Prep (free key): US quotes, daily candles, symbol search and the three financial statements (/stable API).

Free plan (per provider docs, not verified here): 250 requests a day, US coverage, annual statements (quarterly and most non-US data are
paid), about 5 years of daily history. The key travels in the `apikey` query parameter, so it is in the request URL: it never reaches an
error text, log or SOURCES row because every message here is a fixed sentence and `redact.py` masks the registered key and `apikey=`.
Errors: HTTP 401 `{"Error Message": "Invalid API KEY. ..."}` (a real recording), 402 (premium endpoint or parameter), 429 (daily limit).
The same texts also arrive as a 200 body on some endpoints, so the body is read whatever the status is.

Fixtures: keytest_fmp_401 is a REAL answer to a made-up key (no account). FMP has no public demo key, so every success shape
(`fmp_docshape_*`) is built from the documentation and says NOT A RECORDING inside the file: field names are not checked against a live key.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx

from .. import errkinds as K
from ..models import Bars, Quote, SearchHit
from ..ranges import range_days
from .base import HISTORY, QUOTES, SEARCH, ProviderError
from .keyed import KeyedProvider
from .keyed_market import build_fa, fnum, inum

FUNDAMENTALS = "fundamentals"
BASE = "https://financialmodelingprep.com/stable"
HISTORY_DAYS = 1827  # the free plan's five years
MAX_QUOTE_SYMBOLS = 5
STATEMENT_ROWS = 5  # the free plan's limit per statement call
_US = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")
_US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "NYSE ARCA", "BATS", "CBOE"}


def _abs(v: float) -> float:
    return abs(v)


# sec_parse.ROWS key -> (statement, FMP field(s), transform). FMP writes capex, dividends and buybacks as negative cash flows: OpenTerm's
# rows are positive amounts (like SEC's "payments"), so those three are made positive and nothing else is changed.
FIELDS: dict[str, tuple[str, str | tuple[str, ...], Any]] = {
    "revenue": ("IS", "revenue", None), "cost_of_revenue": ("IS", "costOfRevenue", None), "gross_profit": ("IS", "grossProfit", None),
    "rnd": ("IS", "researchAndDevelopmentExpenses", None), "sga": ("IS", "sellingGeneralAndAdministrativeExpenses", None),
    "operating_income": ("IS", "operatingIncome", None), "pretax_income": ("IS", "incomeBeforeTax", None),
    "income_tax": ("IS", "incomeTaxExpense", None), "interest_expense": ("IS", "interestExpense", None), "net_income": ("IS", "netIncome", None),
    "eps_basic": ("IS", "eps", None), "eps_diluted": ("IS", "epsDiluted", None), "shares_diluted": ("IS", "weightedAverageShsOutDil", None),
    "cash": ("BS", "cashAndCashEquivalents", None), "current_assets": ("BS", "totalCurrentAssets", None),
    "total_assets": ("BS", "totalAssets", None), "current_liabilities": ("BS", "totalCurrentLiabilities", None),
    "total_liabilities": ("BS", "totalLiabilities", None), "current_debt": ("BS", "shortTermDebt", None),
    "long_term_debt": ("BS", "longTermDebt", None), "equity": ("BS", "totalStockholdersEquity", None),
    "operating_cf": ("CF", "netCashProvidedByOperatingActivities", None), "capex": ("CF", "capitalExpenditure", _abs),
    "investing_cf": ("CF", "netCashProvidedByInvestingActivities", None), "financing_cf": ("CF", "netCashProvidedByFinancingActivities", None),
    "dividends": ("CF", ("commonDividendsPaid", "netDividendsPaid"), _abs), "buybacks": ("CF", "commonStockRepurchased", _abs),
    "da": ("CF", "depreciationAndAmortization", None),
}


def fmp_symbol(symbol: str) -> str | None:
    """US tickers only (BRK-B as FMP writes it); anything with an exchange suffix is not requested (non-US data is a paid plan)."""
    s = symbol.strip().upper()
    return s if _US.match(s) else None


def error_for(status: int, body: Any) -> ProviderError | None:
    """The ProviderError for an FMP error answer (HTTP status and/or an "Error Message" body); None when it is not an error. Fixed texts."""
    text = str(body.get("Error Message") or "").lower() if isinstance(body, dict) else ""
    if status == 401 or "invalid api key" in text:
        return ProviderError(K.KEY_REQUIRED, "Financial Modeling Prep refused the key")
    if status == 429 or "limit reach" in text:
        return ProviderError(K.RATE_LIMITED, "Financial Modeling Prep daily limit reached (250 requests a day on a free key)")
    if status in (402, 403) or any(w in text for w in ("premium", "exclusive endpoint", "special endpoint", "subscription")):
        return ProviderError(K.UNSUPPORTED, "KEY PLAN: this data needs a paid Financial Modeling Prep plan")
    if status == 404:
        return ProviderError(K.NOT_FOUND, "Financial Modeling Prep has no such symbol")
    if status >= 400 or text:
        return ProviderError(K.UNAVAILABLE, f"Financial Modeling Prep error (HTTP {status})")
    return None


class FmpProvider(KeyedProvider):
    name = "fmp"
    label = "Financial Modeling Prep (free key)"
    capabilities = frozenset({QUOTES, HISTORY, SEARCH, FUNDAMENTALS})
    markets = "US shares and ETFs: quote, daily candles (about 5 years), symbol search, annual income statement, balance sheet and cash flow"
    terms = ("Free key (FMP_API_KEY): 250 requests a day, US coverage, annual statements only (per provider docs, not verified here). "
             "Quarterly statements, intraday candles and most non-US data need a paid plan.")
    rate = (2.0, 5)
    max_wait = 2.0
    timeout = 10.0
    key_name = "FMP_API_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    msg_rate_limited = "Financial Modeling Prep daily limit reached"
    msg_refused = "Financial Modeling Prep refused the key ({code})"

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return super().supports(capability, symbol) and (symbol is None or capability == SEARCH or fmp_symbol(symbol) is not None)

    def auth_params(self) -> dict[str, str]:
        return {"apikey": self._key}  # FMP's documented form: the key is in the URL, so errors never echo the URL (see _request)

    def _check_status(self, r: httpx.Response) -> None:
        try:
            body = r.json()
        except ValueError:
            body = None
        if (err := error_for(r.status_code, body)) is not None:
            raise err

    async def _api(self, path: str, params: dict[str, Any]) -> Any:
        return await self.get_json(f"{BASE}/{path}", params)

    # --- quotes ---------------------------------------------------------------------------------------------------------------
    async def quotes(self, symbols: list[str]) -> list[Quote]:
        wanted = [(s, fmp_symbol(s)) for s in symbols[:MAX_QUOTE_SYMBOLS]]
        results = await asyncio.gather(*(self._quote(s, f) for s, f in wanted if f), return_exceptions=True)
        out = [r for r in results if isinstance(r, Quote)]
        if not out:
            errs = [r for r in results if isinstance(r, ProviderError) and r.kind != K.NOT_FOUND]
            if errs:
                raise errs[0]
            raise ProviderError(K.NOT_FOUND, "no quote")
        return out

    async def _quote(self, symbol: str, fmp: str) -> Quote:
        body = await self._api("quote", {"symbol": fmp})
        d = body[0] if isinstance(body, list) and body and isinstance(body[0], dict) else None
        if d is None or fnum(d.get("price")) is None:
            raise ProviderError(K.NOT_FOUND, "no quote")
        return Quote(
            symbol=symbol, name=d.get("name"), currency="USD", exchange=d.get("exchange"), price=fnum(d.get("price")),
            prev_close=fnum(d.get("previousClose")), change=fnum(d.get("change")), change_pct=fnum(d.get("changePercentage")),
            open=fnum(d.get("open")), high=fnum(d.get("dayHigh")), low=fnum(d.get("dayLow")), volume=inum(d.get("volume")),
            high_52w=fnum(d.get("yearHigh")), low_52w=fnum(d.get("yearLow")), market_time=inum(d.get("timestamp")),
            source=self.source, as_of=self.now(),
        )

    # --- history --------------------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        sym = fmp_symbol(symbol)
        if sym is None or interval != "1d":
            raise ProviderError(K.UNSUPPORTED, f"fmp: no {interval} candles for {symbol}")  # intraday and weekly are paid or not built
        days = range_days(range_)
        if days > HISTORY_DAYS:
            raise ProviderError(K.DEPTH, "daily candles reach back about 5 years on a free Financial Modeling Prep key")
        today = datetime.now(UTC).date()
        body = await self._api("historical-price-eod/full", {"symbol": sym, "from": (today - timedelta(days=days)).isoformat(),
                                                             "to": today.isoformat()})
        rows = [r for r in body if isinstance(r, dict) and _day(r.get("date")) is not None] if isinstance(body, list) else []
        if not rows:
            raise ProviderError(K.NOT_FOUND, "no rows")
        rows.sort(key=lambda r: r["date"])  # FMP sends newest first
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency="USD", exchange=None, tz=None,
            t=[_day(r["date"]) for r in rows], o=[fnum(r.get("open")) for r in rows], h=[fnum(r.get("high")) for r in rows],
            l=[fnum(r.get("low")) for r in rows], c=[fnum(r.get("close")) for r in rows], v=[inum(r.get("volume")) for r in rows],
            source=self.source, as_of=self.now(),
        )

    # --- search ---------------------------------------------------------------------------------------------------------------
    async def search(self, query: str) -> list[SearchHit]:
        body = await self._api("search-symbol", {"query": query.strip(), "limit": 15})
        hits = []
        for d in body if isinstance(body, list) else []:
            if not isinstance(d, dict) or not d.get("symbol") or d.get("exchange") not in _US_EXCHANGES:
                continue  # an exchange OpenTerm has no Yahoo suffix for would resolve to the wrong market
            hits.append(SearchHit(symbol=str(d["symbol"]), name=d.get("name"), exchange=d.get("exchangeFullName") or d.get("exchange"),
                                  type=None, source=self.source))
        if not hits:
            raise ProviderError(K.NOT_FOUND, "no matches")
        return hits

    # --- fundamentals ---------------------------------------------------------------------------------------------------------
    async def _statements(self, sym: str, period: str) -> dict[str, list[dict]]:
        params = {"symbol": sym, "limit": STATEMENT_ROWS if period == "annual" else 8, **({"period": "quarter"} if period == "quarter" else {})}
        paths = {"IS": "income-statement", "BS": "balance-sheet-statement", "CF": "cash-flow-statement"}
        got = await asyncio.gather(*(self._api(p, params) for p in paths.values()))
        return {s: [r for r in b if isinstance(r, dict)] if isinstance(b, list) else [] for s, b in zip(paths, got)}

    async def fundamentals(self, symbol: str) -> dict:
        """The FA payload in SEC EDGAR's shape. Annual statements are free; the quarterly view is a paid FMP plan and is left EMPTY
        with a note (never filled from the annual numbers)."""
        sym = fmp_symbol(symbol)
        if sym is None:
            raise ProviderError(K.UNSUPPORTED, "fmp: US symbols only")
        annual = await self._statements(sym, "annual")
        if not annual["IS"]:
            raise ProviderError(K.NOT_FOUND, "no statements")
        notes: list[str] = []
        try:
            quarter = await self._statements(sym, "quarter")
        except ProviderError as e:
            if e.kind not in (K.UNSUPPORTED, K.RATE_LIMITED):
                raise
            quarter = {"IS": [], "BS": [], "CF": []}
            notes.append("QUARTERLY STATEMENTS NEED A PAID FMP PLAN" if e.kind == K.UNSUPPORTED else "QUARTERLY STATEMENTS: FMP LIMIT REACHED")
        cur = annual["IS"][0].get("reportedCurrency") or "USD"
        if cur != "USD":
            raise ProviderError(K.UNSUPPORTED, f"fmp: statements in {cur}; OpenTerm shows USD rows only")

        def label(r: dict) -> tuple[str, int | None, str | None]:
            fy, fp = inum(r.get("fiscalYear")), r.get("period")
            if fy is None or not fp:
                return str(r.get("date")), None, None
            return (f"FY{fy}", fy, "FY") if fp == "FY" else (f"{fp} FY{fy}", fy, str(fp))

        out = {m: build_fa(reports, FIELDS, "date", label, m) for m, reports in (("A", annual), ("Q", quarter))}
        return {"cik": None, "name": None, "currency": cur, **out, "notes": notes, "symbol": symbol, "source": self.source,
                "as_of": self.now()}

    async def probe(self) -> None:
        await self._api("quote", {"symbol": "AAPL"})


def _day(text: Any) -> int | None:
    try:
        dt = datetime.strptime(str(text)[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return int(dt.replace(tzinfo=UTC).timestamp())
