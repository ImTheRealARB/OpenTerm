"""Phase 7 macro sources: FRED (official API with a key, keyless fredgraph.csv without), the US Treasury par yield
curve, the Nasdaq earnings calendar, and the BLS + BEA release calendars (official ICS feeds) for ECO.

Parsers are pure functions so tests can feed them recorded text. Nothing here logs URLs: the FRED key travels in the
query string, so error messages carry only a status and the API's own message, with the key redacted.
"""

import asyncio
import calendar
import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from statistics import median
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx
import orjson

from ..config import get_settings
from ..models import Earning, EcoEvent, MacroSeries, YieldCurve
from ..ratelimit import RateLimited
from .base import Provider, ProviderError
from .nasdaq import NasdaqProvider

FRED_SERIES = "fred_series"
FRED_SEARCH = "fred_search"
YIELD_CURVE = "yield_curve"
EARNINGS = "earnings"
ECO_CALENDAR = "eco_calendar"

NY = ZoneInfo("America/New_York")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API = "https://api.stlouisfed.org/fred"
TREASURY_CSV = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
)
NASDAQ_EARNINGS = "https://api.nasdaq.com/api/calendar/earnings"
BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_ICS = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"

# FRED chart ranges (days back from today; None = full history).
FRED_RANGES: dict[str, int | None] = {"1Y": 366, "2Y": 731, "5Y": 1827, "10Y": 3653, "20Y": 7306, "MAX": None}
FRED_DEFAULT_RANGE = "5Y"
SERIES_ID = re.compile(r"^[A-Z0-9_.]{1,40}$")

# Well-known FRED series for MACRO without a key: (id, label, title, units, frequency, seasonal adjustment).
# Static series metadata (titles/units as published by FRED), not values: values are always fetched.
CURATED: list[tuple[str, str, str, str, str, str]] = [
    ("GDP", "GDP", "Gross Domestic Product", "Billions of Dollars", "Quarterly", "SAAR"),
    ("A191RL1Q225SBEA", "Real GDP growth", "Real Gross Domestic Product",
     "Percent Change from Preceding Period", "Quarterly", "SAAR"),
    ("CPIAUCSL", "CPI", "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
     "Index 1982-1984=100", "Monthly", "SA"),
    ("CPILFESL", "Core CPI", ("Consumer Price Index for All Urban Consumers: All Items Less Food and Energy in "
                  "U.S. City Average"), "Index 1982-1984=100", "Monthly", "SA"),
    ("PCEPILFE", "Core PCE prices", ("Personal Consumption Expenditures Excluding Food and Energy "
                        "(Chain-Type Price Index)"), "Index 2017=100", "Monthly", "SA"),
    ("UNRATE", "Unemployment rate", "Unemployment Rate", "Percent", "Monthly", "SA"),
    ("PAYEMS", "Nonfarm payrolls", "All Employees, Total Nonfarm", "Thousands of Persons", "Monthly", "SA"),
    ("ICSA", "Initial claims", "Initial Claims", "Number", "Weekly", "SA"),
    ("FEDFUNDS", "Fed funds rate", "Federal Funds Effective Rate", "Percent", "Monthly", "NSA"),
    ("DGS2", "UST 2Y", ("Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity, Quoted on an "
                "Investment Basis"), "Percent", "Daily", "NSA"),
    ("DGS10", "UST 10Y", ("Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an "
                  "Investment Basis"), "Percent", "Daily", "NSA"),
    ("T10Y2Y", "10Y minus 2Y", "10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity",
     "Percent", "Daily", "NSA"),
    ("MORTGAGE30US", "30Y mortgage", "30-Year Fixed Rate Mortgage Average in the United States", "Percent",
     "Weekly", "NSA"),
    ("INDPRO", "Industrial production", "Industrial Production: Total Index", "Index 2017=100", "Monthly", "SA"),
    ("RSAFS", "Retail sales", "Advance Retail Sales: Retail Trade and Food Services", "Millions of Dollars",
     "Monthly", "SA"),
    ("HOUST", "Housing starts", "New Privately-Owned Housing Units Started: Total Units", "Thousands of Units",
     "Monthly", "SAAR"),
    ("UMCSENT", "UMich sentiment", "University of Michigan: Consumer Sentiment", "Index 1966:Q1=100", "Monthly",
     "NSA"),
    ("M2SL", "M2 money stock", "M2", "Billions of Dollars", "Monthly", "SA"),
    ("DCOILWTICO", "WTI crude", "Crude Oil Prices: West Texas Intermediate (WTI) - Cushing, Oklahoma",
     "Dollars per Barrel", "Daily", "NSA"),
    ("DTWEXBGS", "Broad USD index", "Nominal Broad U.S. Dollar Index", "Index Jan 2006=100", "Daily", "NSA"),
]
CURATED_META = {c[0]: c for c in CURATED}

# FRED constant-maturity series -> curve tenor (RATES fallback when the Treasury site is down).
DGS_TENORS = {
    "DGS1MO": "1M", "DGS3MO": "3M", "DGS6MO": "6M", "DGS1": "1Y", "DGS2": "2Y", "DGS3": "3Y",
    "DGS5": "5Y", "DGS7": "7Y", "DGS10": "10Y", "DGS20": "20Y", "DGS30": "30Y",
}
# Releases that move markets (name match against the agencies' own titles). A label list, not a schedule.
MAJOR = (
    "employment situation", "consumer price index", "producer price index", "gross domestic product", "gdp",
    "personal income and outlays", "job openings and labor turnover", "employment cost index",
    "international trade in goods and services", "productivity and costs", "retail",
)


def ny_today() -> date:
    return datetime.now(NY).date()


def redact(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


# --- FRED CSV -------------------------------------------------------------------------------------
def _num(s: str | None) -> float | None:
    """FRED CSV leaves missing observations empty; the API (and older CSVs) use "."."""
    s = (s or "").strip()
    if s in ("", ".", "NA", "N/A", "#N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_fred_csv(text: str) -> tuple[list[str], list[tuple[str, list[float | None]]]]:
    """-> (series ids, [(ISO date, [value per id])]) in date order. Raises ProviderError on a non-CSV answer."""
    if text.startswith("PK") or text.lstrip().startswith("<"):
        raise ProviderError("unavailable", "fredgraph answered with a zip or HTML page, not CSV")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or header[0].strip().lower() not in ("observation_date", "date"):
        raise ProviderError("unavailable", "unexpected CSV header")
    ids = [h.strip().upper() for h in header[1:]]
    rows: list[tuple[str, list[float | None]]] = []
    for r in reader:
        if not r or not re.match(r"^\d{4}-\d{2}-\d{2}$", r[0].strip()):
            continue
        vals = [_num(r[i + 1]) if i + 1 < len(r) else None for i in range(len(ids))]
        rows.append((r[0].strip(), vals))
    rows.sort(key=lambda x: x[0])
    return ids, rows


def epoch(iso: str) -> int:
    y, m, d = (int(x) for x in iso.split("-"))
    return calendar.timegm((y, m, d, 0, 0, 0))


def infer_frequency(dates: list[str]) -> str | None:
    if len(dates) < 3:
        return None
    tail = dates[-60:]
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in pairwise(tail)]
    g = median(gaps)
    if g <= 3:
        return "Daily"
    if g <= 8:
        return "Weekly"
    if g <= 35:
        return "Monthly"
    if g <= 100:
        return "Quarterly"
    if g <= 200:
        return "Semiannual"
    return "Annual"


def build_series(sid: str, points: list[tuple[str, float | None]], meta: dict[str, Any], source: str,
                 as_of: float) -> MacroSeries:
    """points in date order; missing values stay None in the arrays but never count as the last value."""
    t = [epoch(d) for d, _ in points]
    v = [x for _, x in points]
    known = [(d, x) for d, x in points if x is not None]
    if not known:
        raise ProviderError("not_found", "series has no observations in range")
    last_date, last = known[-1]
    prev = known[-2][1] if len(known) > 1 else None
    return MacroSeries(
        id=sid, title=meta.get("title"), units=meta.get("units"),
        frequency=meta.get("frequency") or infer_frequency([d for d, _ in points]),
        seasonal_adjustment=meta.get("seasonal_adjustment"), last_updated=meta.get("last_updated"),
        meta_source=meta.get("meta_source", "none"), t=t, v=v, last_value=last, last_date=last_date,
        prev_value=prev, change=(last - prev) if prev is not None else None, missing=sum(1 for x in v if x is None),
        source=source, as_of=as_of,
    )


def curated_meta(sid: str) -> dict[str, Any]:
    c = CURATED_META.get(sid)
    if not c:
        return {"meta_source": "none"}
    return {"title": c[2], "units": c[3], "frequency": c[4], "seasonal_adjustment": c[5], "meta_source": "curated"}


def range_start(range_: str, today: date | None = None) -> date | None:
    days = FRED_RANGES[range_]
    return None if days is None else (today or ny_today()) - timedelta(days=days)


# --- Treasury par yield curve -------------------------------------------------------------------
_TENOR = re.compile(r"^\s*([\d.]+)\s*(mo|month|months|yr|year|years)\s*$", re.IGNORECASE)


def tenor_label(header: str) -> str | None:
    m = _TENOR.match(header)
    if not m:
        return None
    n = m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)
    return f"{n}{'M' if m.group(2).lower().startswith('mo') else 'Y'}"


def tenor_years(label: str) -> float:
    return float(label[:-1]) / (12 if label.endswith("M") else 1)


def parse_treasury_csv(text: str) -> list[tuple[str, dict[str, float | None]]]:
    """-> [(ISO date, {tenor: yield})] oldest first. Columns vary by year, so they are read from the header."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or header[0].strip().lower() != "date":
        raise ProviderError("unavailable", "unexpected Treasury CSV header")
    labels = [tenor_label(h) for h in header[1:]]
    rows = []
    for r in reader:
        if not r or not r[0].strip():
            continue
        try:
            d = datetime.strptime(r[0].strip(), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        rows.append((d, {lab: _num(r[i + 1]) if i + 1 < len(r) else None for i, lab in enumerate(labels) if lab}))
    rows.sort(key=lambda x: x[0])
    return rows


def shift(d: date, months: int = 0, days: int = 0) -> date:
    if months:
        m = d.month - 1 + months
        y, m = d.year + m // 12, m % 12 + 1
        d = date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
    return d + timedelta(days=days)


def build_curve(rows: list[tuple[str, dict[str, float | None]]], source: str, as_of: float,
                note: str | None = None) -> YieldCurve:
    """Latest curve plus the last observation on or before 1 day / 1 week / 1 month / 1 year earlier."""
    rows = [r for r in rows if any(v is not None for v in r[1].values())]
    if not rows:
        raise ProviderError("not_found", "no curve rows")
    tenors: list[str] = []
    for _, vals in rows[-260:]:
        for k in vals:
            if k not in tenors:
                tenors.append(k)
    tenors.sort(key=tenor_years)
    latest_d, latest = rows[-1]
    d0 = date.fromisoformat(latest_d)

    def on_or_before(target: date) -> tuple[str, dict] | None:
        iso = target.isoformat()
        for d, vals in reversed(rows):
            if d <= iso:
                return d, vals
        return None

    targets = {
        "1D": rows[-2] if len(rows) > 1 else None,
        "1W": on_or_before(shift(d0, days=-7)),
        "1M": on_or_before(shift(d0, months=-1)),
        "1Y": on_or_before(shift(d0, months=-12)),
    }
    # A comparison older than its target by more than a week means the file did not reach back that far.
    limits = {"1D": 10, "1W": 14, "1M": 38, "1Y": 372}

    def spread(vals: dict) -> float | None:
        a, b = vals.get("10Y"), vals.get("2Y")
        return round(a - b, 4) if a is not None and b is not None else None

    compare = {}
    for label, hit in targets.items():
        if hit and (d0 - date.fromisoformat(hit[0])).days <= limits[label]:
            compare[label] = {"date": hit[0], "yields": [hit[1].get(t) for t in tenors], "spread_2s10s": spread(hit[1])}
    return YieldCurve(
        date=latest_d, tenors=tenors, years=[tenor_years(t) for t in tenors], yields=[latest.get(t) for t in tenors],
        spread_2s10s=spread(latest), compare=compare, note=note, source=source, as_of=as_of,
    )


# --- Nasdaq earnings ------------------------------------------------------------------------------
def money(s: Any) -> float | None:
    """'$4.60' -> 4.6, '($0.24)' -> -0.24, '$2,190,001,700,000' -> 2.19e12, 'N/A' / '' -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("$", "").replace(",", "").strip()
    if t in ("", "N/A", "NA", "--"):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


TIME_OF_DAY = {"time-pre-market": "PRE", "time-after-hours": "POST"}


def parse_earnings(body: Any, day: str, source: str, as_of: float) -> dict:
    """Nasdaq answers weekends/holidays with rows: null. That is an empty day, not an error."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise ProviderError("unavailable", "unexpected earnings answer")
    data = body["data"]
    rows = []
    for r in data.get("rows") or []:
        if not r.get("symbol"):
            continue
        n = money(r.get("noOfEsts"))
        rows.append(Earning(
            symbol=str(r["symbol"]).upper(), name=r.get("name"), time=TIME_OF_DAY.get(r.get("time") or ""),
            fiscal_quarter=r.get("fiscalQuarterEnding") or None, eps_forecast=money(r.get("epsForecast")),
            n_ests=int(n) if n is not None else None, last_year_eps=money(r.get("lastYearEPS")),
            last_year_date=r.get("lastYearRptDt") or None, eps=money(r.get("eps")),
            surprise_pct=money(r.get("surprise")), market_cap=money(r.get("marketCap")),
        ))
    rows.sort(key=lambda e: -(e.market_cap or 0))
    return {"date": day, "as_of_text": data.get("asOf"), "rows": [e.model_dump() for e in rows], "source": source,
            "as_of": as_of}


# --- ICS release calendars ------------------------------------------------------------------------
def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _ics_unescape(s: str) -> str:
    return s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _ics_time(params: str, value: str) -> datetime | None:
    value = value.strip()
    try:
        if "VALUE=DATE" in params and "DATE-TIME" not in params or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=NY)
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).astimezone(NY)
        # TZID=US-Eastern (BLS) / America/New_York (BEA) or floating time: both agencies publish Eastern time.
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=NY)
    except ValueError:
        return None


def parse_ics(text: str, agency: str, source: str) -> list[EcoEvent]:
    if "BEGIN:VCALENDAR" not in text:
        raise ProviderError("unavailable", f"{agency}: not an iCalendar answer")
    events: list[EcoEvent] = []
    cur: dict[str, Any] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur and cur.get("dt") and cur.get("summary"):
                dt: datetime = cur["dt"]
                has_time = cur.get("has_time", True)
                events.append(EcoEvent(
                    date=dt.date().isoformat(), time=dt.strftime("%H:%M") if has_time else None,
                    ts=dt.timestamp(), name=cur["summary"], agency=agency,
                    major=any(k in cur["summary"].lower() for k in MAJOR), source=source,
                ))
            cur = None
        elif cur is not None and ":" in line:
            key, _, value = line.partition(":")
            name, _, params = key.partition(";")
            if name == "DTSTART":
                cur["dt"] = _ics_time(params, value)
                cur["has_time"] = "T" in value
            elif name == "SUMMARY":
                cur["summary"] = _ics_unescape(value)
    return events


# --- providers ------------------------------------------------------------------------------------
class FredCsvProvider(Provider):
    name = "fred_csv"
    label = "FRED graph CSV (keyless)"
    capabilities = frozenset({FRED_SERIES, YIELD_CURVE})
    markets = "Any FRED series by id (values only: titles/units need FRED_API_KEY); UST curve fallback (DGS*)"
    terms = "Public download, no key. Data: Federal Reserve Bank of St. Louis (FRED); cite the original source."
    rate = (3.0, 20)
    max_wait = 4.0
    timeout = 12.0
    # A browser User-Agent gets no answer from fredgraph (hangs); a plain client UA is served at once.
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "text/csv,*/*"}

    async def fred_series(self, sid: str, start: date | None) -> MacroSeries:
        params = {"id": sid} | ({"cosd": start.isoformat()} if start else {})
        text = (await self.get_bytes(FRED_CSV, params)).decode("utf-8", "replace")
        ids, rows = parse_fred_csv(text)
        if not ids or ids[0] != sid:
            raise ProviderError("unavailable", "CSV is for a different series")
        iso = start.isoformat() if start else ""
        points = [(d, vals[0]) for d, vals in rows if d >= iso]
        return build_series(sid, points, curated_meta(sid), self.source, self.now())

    async def yield_curve(self, today: date | None = None) -> YieldCurve:
        # Same-frequency ids come back as one CSV (cosd is ignored for several ids: full history, ~6 s).
        text = (await self.get_bytes(FRED_CSV, {"id": ",".join(DGS_TENORS)}, timeout=20.0)).decode("utf-8", "replace")
        ids, rows = parse_fred_csv(text)
        cut = shift(today or ny_today(), months=-13).isoformat()
        curve_rows = [(d, {DGS_TENORS[i]: v for i, v in zip(ids, vals) if i in DGS_TENORS}) for d, vals in rows if d >= cut]
        return build_curve(curve_rows, self.source, self.now(),
                           note="FRED constant-maturity series (DGS*), one business day behind the Treasury")

    async def probe(self) -> None:
        await self.get_bytes(FRED_CSV, {"id": "DGS10", "cosd": (ny_today() - timedelta(days=10)).isoformat()})


class FredApiProvider(Provider):
    """Official FRED API. Without FRED_API_KEY it supports nothing, so the router skips it."""

    name = "fred"
    label = "FRED API (St. Louis Fed)"
    capabilities = frozenset({FRED_SERIES, FRED_SEARCH, ECO_CALENDAR})
    markets = "800k+ US and international economic series with titles, units, frequency; search; release dates"
    terms = "Free API key (FRED_API_KEY), 120 requests/min. Data: FRED, Federal Reserve Bank of St. Louis."
    rate = (2.0, 20)
    max_wait = 3.0
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}

    key_name = "FRED"

    def __init__(self, http: httpx.AsyncClient, source: str | None = None, api_key: str | None = None):
        super().__init__(http, source)
        self._key = get_settings().fred_api_key if api_key is None else api_key

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return self.has_key and capability in self.capabilities

    async def _api(self, path: str, params: dict[str, Any]) -> dict:
        if not self._key:
            raise ProviderError("key_required", "FRED_API_KEY is not set")
        try:
            await self.bucket.acquire(self.max_wait)
        except RateLimited as e:
            raise ProviderError("rate_limited", str(e)) from e
        try:
            r = await self.http.get(f"{FRED_API}/{path}", params={**params, "api_key": self._key, "file_type": "json"},
                                    headers=self.headers, timeout=self.timeout)
        except httpx.TimeoutException as e:
            raise ProviderError("unavailable", "timeout") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", type(e).__name__) from e
        try:
            body = orjson.loads(r.content)
        except orjson.JSONDecodeError:
            body = None
        if r.status_code == 429:
            raise ProviderError("rate_limited", "429 from FRED")
        if r.status_code >= 400 or not isinstance(body, dict):
            msg = redact(str((body or {}).get("error_message") or f"HTTP {r.status_code}"), self._key)
            low = msg.lower()
            if "does not exist" in low:
                raise ProviderError("not_found", msg)
            if "api_key" in low or "api key" in low:
                raise ProviderError("key_required", msg)
            raise ProviderError("unavailable", msg[:200])
        return body

    async def fred_series(self, sid: str, start: date | None) -> MacroSeries:
        obs_params = {"series_id": sid} | ({"observation_start": start.isoformat()} if start else {})
        meta_body, obs_body = await asyncio.gather(self._api("series", {"series_id": sid}),
                                                   self._api("series/observations", obs_params))
        meta = (meta_body.get("seriess") or [{}])[0]
        points = [(o["date"], _num(o.get("value"))) for o in obs_body.get("observations") or [] if o.get("date")]
        return build_series(sid, points, {
            "title": meta.get("title"), "units": meta.get("units"), "frequency": meta.get("frequency"),
            "seasonal_adjustment": meta.get("seasonal_adjustment_short") or meta.get("seasonal_adjustment"),
            "last_updated": meta.get("last_updated"), "meta_source": "fred_api",
        }, self.source, self.now())

    async def fred_search(self, query: str) -> list[dict]:
        body = await self._api("series/search", {"search_text": query, "limit": 50, "order_by": "popularity",
                                                 "sort_order": "desc"})
        out = [{
            "id": s.get("id"), "title": s.get("title"), "units": s.get("units_short") or s.get("units"),
            "frequency": s.get("frequency_short") or s.get("frequency"),
            "seasonal_adjustment": s.get("seasonal_adjustment_short"), "observation_end": s.get("observation_end"),
            "last_updated": s.get("last_updated"), "popularity": s.get("popularity"),
        } for s in body.get("seriess") or [] if s.get("id")]
        if not out:
            raise ProviderError("not_found", "no series match")
        return out

    async def eco_calendar(self, start: date) -> dict:
        body = await self._api("releases/dates", {
            "realtime_start": start.isoformat(), "realtime_end": "9999-12-31",
            "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 1000,
        })
        events = [EcoEvent(
            date=d["date"], time=None, ts=epoch(d["date"]), name=d.get("release_name") or "", agency="FRED",
            major=any(k in (d.get("release_name") or "").lower() for k in MAJOR), source=self.source,
        ) for d in body.get("release_dates") or [] if d.get("date")]
        return {"events": events, "failed": []}

    async def probe(self) -> None:
        await self._api("series", {"series_id": "GDP"})


class TreasuryProvider(Provider):
    name = "treasury"
    label = "US Treasury par yield curve"
    capabilities = frozenset({YIELD_CURVE})
    markets = "Daily Treasury par yield curve rates, 1M-30Y (published after ~3:30 pm ET)"
    terms = "Public data, no key. Source: U.S. Department of the Treasury."
    rate = (1.0, 4)
    max_wait = 1.0
    timeout = 12.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": "OpenTerm/0.1", "Accept": "text/csv,*/*"}

    async def _year(self, year: int) -> list[tuple[str, dict[str, float | None]]]:
        params = {"type": "daily_treasury_yield_curve", "field_tdr_date_value": year, "page": "", "_format": "csv"}
        text = (await self.get_bytes(TREASURY_CSV.format(year=year), params)).decode("utf-8-sig", "replace")
        return parse_treasury_csv(text)

    async def yield_curve(self, today: date | None = None) -> YieldCurve:
        y = (today or ny_today()).year
        cur, prev = await asyncio.gather(self._year(y), self._year(y - 1), return_exceptions=True)
        if isinstance(cur, BaseException) and isinstance(prev, BaseException):
            raise cur if isinstance(cur, ProviderError) else ProviderError("unavailable", str(cur))
        rows = (prev if isinstance(prev, list) else []) + (cur if isinstance(cur, list) else [])
        note = None if isinstance(prev, list) else "previous year's file did not load: no 1Y comparison"
        return build_curve(rows, self.source, self.now(), note=note)

    async def probe(self) -> None:
        await self._year(ny_today().year)


class NasdaqEarningsProvider(Provider):
    name = "nasdaq_earnings"
    label = "Nasdaq.com earnings calendar"
    capabilities = frozenset({EARNINGS})
    markets = "US-listed companies reporting on a given day (consensus EPS, # estimates, last year's EPS)"
    terms = "Public website API; personal use. Undocumented: may change."
    rate = (1.0, 3)
    max_wait = 1.0
    timeout = 10.0
    headers: ClassVar[dict[str, str]] = NasdaqProvider.headers

    async def earnings(self, day: date) -> dict:
        body = await self.get_json(NASDAQ_EARNINGS, {"date": day.isoformat()})
        return parse_earnings(body, day.isoformat(), self.source, self.now())

    async def probe(self) -> None:
        await self.get_json(NASDAQ_EARNINGS, {"date": ny_today().isoformat()})


class AgencyCalendarProvider(Provider):
    """BLS and BEA publish their release schedules as iCalendar feeds. Both are fetched and merged; one failing
    leaves the other's events visible and is named in `failed`."""

    name = "agency_ics"
    label = "BLS + BEA release calendars (ICS)"
    capabilities = frozenset({ECO_CALENDAR})
    markets = "US releases: BLS (jobs, CPI, PPI, JOLTS, ECI...) and BEA (GDP, PCE/income, trade); Eastern times"
    terms = "Official agency schedules, no key. BLS asks for a User-Agent with contact info (SEC_USER_AGENT)."
    rate = (1.0, 4)
    max_wait = 1.0
    timeout = 12.0

    def __init__(self, http: httpx.AsyncClient, source: str | None = None):
        super().__init__(http, source)
        # BLS answers 403 to browser UAs and to a bare product token; it serves a UA that names a contact.
        self.headers = {"User-Agent": get_settings().sec_user_agent, "Accept": "text/calendar,text/plain,*/*"}

    async def _feed(self, url: str, agency: str) -> list[EcoEvent]:
        return parse_ics((await self.get_bytes(url)).decode("utf-8", "replace"), agency, self.source)

    async def eco_calendar(self, start: date) -> dict:
        results = await asyncio.gather(self._feed(BLS_ICS, "BLS"), self._feed(BEA_ICS, "BEA"), return_exceptions=True)
        events: list[EcoEvent] = []
        failed = []
        errors = []
        for agency, r in zip(("BLS", "BEA"), results):
            if isinstance(r, BaseException):
                failed.append(agency)
                errors.append(r)
            else:
                events += r
        if len(failed) == 2:
            e = errors[0]
            raise e if isinstance(e, ProviderError) else ProviderError("unavailable", str(e))
        return {"events": events, "failed": failed}

    async def probe(self) -> None:
        await self.get_bytes(BEA_ICS)
