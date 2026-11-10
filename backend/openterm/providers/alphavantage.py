"""Alpha Vantage (free key): US quotes, daily and intraday candles, and the three financial statements.

Free plan (per provider docs, not verified here): 25 requests a day and 1 request a second. So this source is the LAST fallback for every
capability it has (see hierarchy.py), and the FA statements cost 3 of the 25 daily requests. The key travels in the `apikey` query
parameter (the API has no header form), so it is in the request URL: it never reaches an error text, log or SOURCES row because every
message here is a fixed sentence (never the response body, which echoes the key in its limit text) and `redact.py` masks the key and
`apikey=` anyway.

Alpha Vantage answers HTTP 200 for nearly everything, and the problem is a body with one text key:
  - "Error Message": "Invalid API call ..."           -> not_found (the symbol)
  - "Information": "... premium endpoint ..."          -> unsupported (KEY PLAN: needs a paid plan; not a strike)
  - "Information": "... spreading out ... (1 request per second)"  -> rate_limited (burst)
  - "Information": "... 25 requests per day ..."       -> rate_limited (day)
  - "Information": "the demo API key is for demo purposes only" -> key_required (a demo key covers IBM only)
Fixtures: alphavantage_real_* are REAL answers (public `demo` key or a made-up key, see each file's "recorded" line);
alphavantage_docshape_* say NOT A RECORDING inside the file.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from .. import errkinds as K
from ..models import Bars, Quote
from ..ranges import range_days
from .base import HISTORY, QUOTES, ProviderError
from .keyed import KeyedProvider
from .keyed_market import (
    BARS_PER_SESSION,
    SESSIONS,
    build_fa,
    depth_days,
    fnum,
    inum,
    trim_sessions,
)

FUNDAMENTALS = "fundamentals"
BASE = "https://www.alphavantage.co/query"
COMPACT_BARS = 100  # outputsize=compact; "full" is a premium option on the free key
INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "60min"}
_US = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")

# sec_parse.ROWS key -> (statement, Alpha Vantage field(s), transform). A key with no field stays blank (EPS and diluted shares are not in
# Alpha Vantage's statements); a tuple means "first one the vendor filled".
FIELDS: dict[str, tuple[str, str | tuple[str, ...], Any]] = {
    "revenue": ("IS", "totalRevenue", None), "cost_of_revenue": ("IS", ("costOfRevenue", "costofGoodsAndServicesSold"), None),
    "gross_profit": ("IS", "grossProfit", None), "rnd": ("IS", "researchAndDevelopment", None),
    "sga": ("IS", "sellingGeneralAndAdministrative", None), "operating_income": ("IS", "operatingIncome", None),
    "pretax_income": ("IS", "incomeBeforeTax", None), "income_tax": ("IS", "incomeTaxExpense", None),
    "interest_expense": ("IS", "interestExpense", None), "net_income": ("IS", "netIncome", None),
    "cash": ("BS", "cashAndCashEquivalentsAtCarryingValue", None), "current_assets": ("BS", "totalCurrentAssets", None),
    "total_assets": ("BS", "totalAssets", None), "current_liabilities": ("BS", "totalCurrentLiabilities", None),
    "total_liabilities": ("BS", "totalLiabilities", None), "current_debt": ("BS", "currentDebt", None),
    "long_term_debt": ("BS", ("longTermDebtNoncurrent", "longTermDebt"), None), "equity": ("BS", "totalShareholderEquity", None),
    "operating_cf": ("CF", "operatingCashflow", None), "capex": ("CF", "capitalExpenditures", None),
    "investing_cf": ("CF", "cashflowFromInvestment", None), "financing_cf": ("CF", "cashflowFromFinancing", None),
    "dividends": ("CF", ("dividendPayoutCommonStock", "dividendPayout"), None),
    "buybacks": ("CF", "paymentsForRepurchaseOfCommonStock", None), "da": ("CF", "depreciationDepletionAndAmortization", None),
}


def av_symbol(symbol: str) -> str | None:
    """US tickers only (BRK-B as Alpha Vantage writes it); anything with an exchange suffix is not requested."""
    s = symbol.strip().upper()
    return s if _US.match(s) else None


def check_body(body: Any) -> None:
    """Raises the right ProviderError for an Alpha Vantage 200-with-a-message answer. Texts are fixed: the body is never copied."""
    if not isinstance(body, dict):
        raise ProviderError(K.UNAVAILABLE, "Alpha Vantage sent an unexpected answer")
    text = " ".join(str(body.get(k) or "") for k in ("Information", "Note", "Error Message")).lower()
    if not text.strip():
        return
    if "demo" in text and ("purposes only" in text or "demo api key" in text):
        raise ProviderError(K.KEY_REQUIRED, "Alpha Vantage: the demo key only covers a few symbols (set your own key in APIKEYS)")
    if "invalid api key" in text or "claim your free api key" in text:
        raise ProviderError(K.KEY_REQUIRED, "Alpha Vantage refused the key")
    if "spreading out" in text or ("per second" in text and "per day" not in text):
        raise ProviderError(K.RATE_LIMITED, "Alpha Vantage burst limit (1 request a second)")
    if "per day" in text or "rate limit" in text or "call frequency" in text:
        raise ProviderError(K.RATE_LIMITED, "Alpha Vantage daily limit reached (25 requests a day on a free key)")
    # The limit texts end with "... unlock all premium endpoints", so the premium test comes after them.
    if "premium endpoint" in text or "premium feature" in text:
        raise ProviderError(K.UNSUPPORTED, "KEY PLAN: this Alpha Vantage call needs a premium plan")
    if "invalid api call" in text or body.get("Error Message"):
        raise ProviderError(K.NOT_FOUND, "Alpha Vantage has no such symbol")
    raise ProviderError(K.UNAVAILABLE, "Alpha Vantage sent an unexpected message")


class AlphaVantageProvider(KeyedProvider):
    name = "alphavantage"
    label = "Alpha Vantage (free key)"
    capabilities = frozenset({QUOTES, HISTORY, FUNDAMENTALS})
    markets = "US shares and ETFs: last quote, daily and intraday candles, income statement, balance sheet and cash flow"
    terms = ("Free key (ALPHAVANTAGE_API_KEY): 25 requests a day and 1 a second (per provider docs, not verified here). Daily candles reach back "
             "about 100 sessions; intraday and full history can be premium. The last fallback in every order.")
    rate = (1.0, 1)  # 1 request a second
    max_wait = 3.0   # FA makes three calls in a row: wait for the next slot instead of failing over
    timeout = 10.0
    key_name = "ALPHAVANTAGE_API_KEY"
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}
    intraday_days: ClassVar[dict[str, int]] = {i: max(1, depth_days(BARS_PER_SESSION[i], COMPACT_BARS)) for i in INTERVALS}
    msg_rate_limited = "429 from Alpha Vantage"
    msg_refused = "Alpha Vantage refused the key ({code})"

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return super().supports(capability, symbol) and (symbol is None or av_symbol(symbol) is not None)

    def auth_params(self) -> dict[str, str]:
        return {"apikey": self._key}  # the only place Alpha Vantage accepts it

    async def _api(self, params: dict[str, Any]) -> dict:
        body = await self.get_json(BASE, params)
        check_body(body)
        return body

    # --- quotes ---------------------------------------------------------------------------------------------------------------
    async def quotes(self, symbols: list[str]) -> list[Quote]:
        out: list[Quote] = []
        first: ProviderError | None = None
        for s in symbols[:3]:  # 25 requests a day: a watchlist cannot be spread over this source
            sym = av_symbol(s)
            if sym is None:
                continue
            try:
                out.append(self._quote(s, await self._api({"function": "GLOBAL_QUOTE", "symbol": sym})))
            except ProviderError as e:
                if e.kind != K.NOT_FOUND:
                    first = first or e
        if not out:
            raise first or ProviderError(K.NOT_FOUND, "no quote")
        return out

    def _quote(self, symbol: str, body: dict) -> Quote:
        g = body.get("Global Quote") or {}
        price = fnum(g.get("05. price"))
        if price is None:
            raise ProviderError(K.NOT_FOUND, "no quote")
        # Only a date comes back: the quote's time is that day at 00:00 UTC, so its age is never understated (the panel shows the age).
        return Quote(symbol=symbol, currency="USD", price=price, prev_close=fnum(g.get("08. previous close")), change=fnum(g.get("09. change")),
                     change_pct=fnum(g.get("10. change percent")), open=fnum(g.get("02. open")), high=fnum(g.get("03. high")),
                     low=fnum(g.get("04. low")), volume=inum(g.get("06. volume")), market_time=_day_epoch(g.get("07. latest trading day")),
                     source=self.source, as_of=self.now())

    # --- history --------------------------------------------------------------------------------------------------------------
    async def history(self, symbol: str, range_: str, interval: str) -> Bars:
        sym = av_symbol(symbol)
        days = range_days(range_)
        intraday = interval in INTERVALS
        if sym is None or not (intraday or interval == "1d"):
            raise ProviderError(K.UNSUPPORTED, f"alphavantage: no {interval} candles for {symbol}")
        if intraday:
            limit = self.intraday_days[interval]
            if days > limit:
                raise ProviderError(K.DEPTH, f"{interval} candles reach back {limit} days on a free Alpha Vantage key")
            params = {"function": "TIME_SERIES_INTRADAY", "symbol": sym, "interval": INTERVALS[interval], "outputsize": "compact",
                      "extended_hours": "false"}
        else:
            if days > int(COMPACT_BARS * 7 / 5):
                raise ProviderError(K.DEPTH, "daily candles reach back about 100 sessions on a free Alpha Vantage key (full history is premium)")
            params = {"function": "TIME_SERIES_DAILY", "symbol": sym, "outputsize": "compact"}
        body = await self._api(params)
        key = next((k for k in body if k.startswith("Time Series")), None)
        rows = body.get(key) if key else None
        if not isinstance(rows, dict) or not rows:
            raise ProviderError(K.NOT_FOUND, "no rows")
        tzname = (body.get("Meta Data") or {}).get("6. Time Zone") if intraday else None
        zone = _zone(tzname)
        pairs = []  # (epoch, session day, row), oldest first
        for text in sorted(rows):
            t = _epoch(text, zone if intraday else UTC, intraday)
            if t is not None:
                pairs.append((t, text[:10], rows[text]))
        if not pairs:
            raise ProviderError(K.NOT_FOUND, "no rows")
        if intraday and range_ in SESSIONS:
            pairs = pairs[trim_sessions([(t, d) for t, d, _ in pairs], SESSIONS[range_]):]
        elif not intraday:
            cutoff = pairs[-1][0] - days * 86400  # from the newest bar, not from today: a stale answer is shown as stale, not cut away
            pairs = [p for p in pairs if p[0] >= cutoff]
        return Bars.model_construct(
            symbol=symbol, range=range_, interval=interval, currency="USD", exchange=None, tz=tzname,
            t=[t for t, _, _ in pairs], o=[fnum(r.get("1. open")) for _, _, r in pairs], h=[fnum(r.get("2. high")) for _, _, r in pairs],
            l=[fnum(r.get("3. low")) for _, _, r in pairs], c=[fnum(r.get("4. close")) for _, _, r in pairs],
            v=[inum(r.get("5. volume")) for _, _, r in pairs], source=self.source, as_of=self.now(),
        )

    # --- fundamentals ---------------------------------------------------------------------------------------------------------
    async def fundamentals(self, symbol: str) -> dict:
        """The FA payload in SEC EDGAR's shape ({"A": ..., "Q": ...}); rows Alpha Vantage does not send stay blank."""
        sym = av_symbol(symbol)
        if sym is None:
            raise ProviderError(K.UNSUPPORTED, "alphavantage: US symbols only")
        bodies = {}
        for stmt, fn in (("IS", "INCOME_STATEMENT"), ("BS", "BALANCE_SHEET"), ("CF", "CASH_FLOW")):
            bodies[stmt] = await self._api({"function": fn, "symbol": sym})
        if not bodies["IS"].get("annualReports"):
            raise ProviderError(K.NOT_FOUND, "no statements")
        cur = bodies["IS"]["annualReports"][0].get("reportedCurrency") or "USD"
        if cur != "USD":
            raise ProviderError(K.UNSUPPORTED, f"alphavantage: statements in {cur}; OpenTerm shows USD rows only")

        def label(r: dict) -> tuple[str, int | None, str | None]:
            return str(r.get("fiscalDateEnding")), None, None  # no fiscal year in the answer: a period is named by its end date

        out = {m: build_fa({s: b.get(key) or [] for s, b in bodies.items()}, FIELDS, "fiscalDateEnding", label, m)
               for m, key in (("A", "annualReports"), ("Q", "quarterlyReports"))}
        return {"cik": None, "name": None, "currency": cur, **out, "symbol": symbol, "source": self.source, "as_of": self.now()}

    async def probe(self) -> None:
        await self._api({"function": "GLOBAL_QUOTE", "symbol": "IBM"})


def _zone(name: str | None) -> Any:
    try:
        return ZoneInfo(name) if name else UTC
    except (KeyError, ValueError):
        return UTC


def _day_epoch(text: Any) -> int | None:
    return _epoch(str(text or "")[:10], UTC, False)


def _epoch(text: str, zone: Any, intraday: bool) -> int | None:
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d")
    except ValueError:
        return None
    return int(dt.replace(tzinfo=zone).timestamp())
