"""QRY, the query language (Phase 31), and FLD, its field catalog. Pure: text in, a `Query` out; rows in, filtered rows out. No I/O.

Two shapes of query:

    QRY last, pe, mcap FOR MEMB:SPY WHERE pe<20 AND sector=Technology SORT mcap DESC LIMIT 50     (a snapshot: one row per symbol)
    QRY close FOR AAPL,MSFT DATES -1Y..0 FREQ M                                                  (a time series: one row per date)

  FOR    a universe word the scanner knows (SPX NDX DJI RUT MID, MEMB:<ETF>, WL:<NAME>, LIST:A,B, NIFTY50, NIFTY500), a comma list
         of symbols, or US (every US-listed stock in the screener file; only screener and quote fields then). In DATES mode the list
         may hold FRED series as FRED:<ID>.
  WHERE  conditions joined by AND: <field> <op> <value>, op one of < <= > >= = != ; text fields compare without case.
  SORT   one field, ASC or DESC (default DESC for numbers).  LIMIT  rows (default 100, at most 1000).
  DATES  <from>..<to>, each -<n>D|W|M|Y (back from today), 0 (today) or YYYY-MM-DD.  FREQ  D, W or M (last value of each period).

Every field says where it comes from, its unit, how often it changes and whether it needs a key (`FIELDS`, shown by FLD).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..research.fund_parse import INDEX_PROXY
from ..scanner.universe import ALIASES as SCAN_ALIASES
from ..scanner.universe import NIFTY

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100
PER_SYMBOL_CAP = 150  # symbols a per-symbol (Yahoo key statistics) field is fetched for; filter with screener fields first


class QueryError(ValueError):
    """Shown to the user as is."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    group: str  # quote | screener | stats | bars | fred
    source: str
    unit: str
    freq: str
    kind: str = "num"  # table column kind (research/table.py KINDS)
    key: str | None = None  # key-store name when the field needs a key
    words: str = ""  # extra search words for FLD
    path: tuple[str, ...] = ()  # where the value lives (quote attribute, screener column, Yahoo module key)


def _f(name, label, group, source, unit, freq, kind="num", words="", path=()) -> Field:
    return Field(name, label, group, source, unit, freq, kind, None, words, path or (name,))


QUOTE_SRC = "QUOTE CHAIN (YAHOO FIRST; SEE SOURCES)"
SCREENER_SRC = "NASDAQ.COM STOCK SCREENER (US LISTED, ONE FILE)"
STATS_SRC = "YAHOO KEY STATISTICS (UNOFFICIAL)"
BARS_SRC = "PRICE HISTORY (YAHOO FIRST; SEE SOURCES)"

FIELDS: dict[str, Field] = {f.name: f for f in (
    _f("last", "LAST PRICE", "quote", QUOTE_SRC, "CCY", "LIVE / DELAYED", "price", "price close", ("price",)),
    _f("chg", "CHANGE TODAY", "quote", QUOTE_SRC, "CCY", "LIVE / DELAYED", "num", "change", ("change",)),
    _f("pct", "CHANGE TODAY %", "quote", QUOTE_SRC, "%", "LIVE / DELAYED", "num", "change percent return", ("change_pct",)),
    _f("volume", "VOLUME TODAY", "quote", QUOTE_SRC, "SHARES", "LIVE / DELAYED", "int", "turnover", ("volume",)),
    _f("open", "OPEN TODAY", "quote", QUOTE_SRC, "CCY", "DAILY", "price", "", ("open",)),
    _f("high", "HIGH TODAY", "quote", QUOTE_SRC, "CCY", "LIVE / DELAYED", "price", "", ("high",)),
    _f("low", "LOW TODAY", "quote", QUOTE_SRC, "CCY", "LIVE / DELAYED", "price", "", ("low",)),
    _f("prev", "PREVIOUS CLOSE", "quote", QUOTE_SRC, "CCY", "DAILY", "price", "close yesterday", ("prev_close",)),
    _f("name", "COMPANY NAME", "screener", SCREENER_SRC, "TEXT", "DAILY", "text", "company"),
    _f("mcap", "MARKET CAP", "screener", SCREENER_SRC, "USD", "DAILY", "money", "market capitalisation size"),
    _f("sector", "SECTOR", "screener", SCREENER_SRC, "TEXT", "DAILY", "text", "industry group"),
    _f("industry", "INDUSTRY", "screener", SCREENER_SRC, "TEXT", "DAILY", "text", ""),
    _f("country", "COUNTRY", "screener", SCREENER_SRC, "TEXT", "DAILY", "text", "domicile"),
    _f("pe", "P/E (TRAILING)", "stats", STATS_SRC, "X", "DAILY", "num", "price earnings valuation", ("summaryDetail", "trailingPE")),
    _f("fpe", "P/E (FORWARD)", "stats", STATS_SRC, "X", "DAILY", "num", "price earnings forward estimate", ("summaryDetail", "forwardPE")),
    _f("pb", "PRICE / BOOK", "stats", STATS_SRC, "X", "DAILY", "num", "valuation book", ("defaultKeyStatistics", "priceToBook")),
    _f("ps", "PRICE / SALES (TTM)", "stats", STATS_SRC, "X", "DAILY", "num", "valuation revenue", ("summaryDetail", "priceToSalesTrailing12Months")),
    _f("evebitda", "EV / EBITDA", "stats", STATS_SRC, "X", "DAILY", "num", "enterprise value valuation", ("defaultKeyStatistics", "enterpriseToEbitda")),
    _f("beta", "BETA", "stats", STATS_SRC, "X", "MONTHLY", "num", "risk market", ("summaryDetail", "beta")),
    _f("divy", "DIVIDEND YIELD", "stats", STATS_SRC, "RATIO", "DAILY", "pct", "dividend income", ("summaryDetail", "dividendYield")),
    _f("eps", "EPS (TRAILING)", "stats", STATS_SRC, "CCY", "QUARTERLY", "num", "earnings per share", ("defaultKeyStatistics", "trailingEps")),
    _f("netmargin", "NET PROFIT MARGIN", "stats", STATS_SRC, "RATIO", "QUARTERLY", "pct", "net margin profitability", ("defaultKeyStatistics", "profitMargins")),
    _f("shares", "SHARES OUTSTANDING", "stats", STATS_SRC, "SHARES", "QUARTERLY", "money", "", ("defaultKeyStatistics", "sharesOutstanding")),
    _f("short", "SHORT % OF FLOAT", "stats", STATS_SRC, "RATIO", "TWICE A MONTH", "pct", "short interest", ("defaultKeyStatistics", "shortPercentOfFloat")),
    _f("hi52", "52-WEEK HIGH", "stats", STATS_SRC, "CCY", "DAILY", "price", "high year", ("summaryDetail", "fiftyTwoWeekHigh")),
    _f("lo52", "52-WEEK LOW", "stats", STATS_SRC, "CCY", "DAILY", "price", "low year", ("summaryDetail", "fiftyTwoWeekLow")),
    _f("close", "CLOSE", "bars", BARS_SRC, "CCY", "DAILY BARS", "price", "price history", ("c",)),
    _f("adj", "ADJUSTED CLOSE", "bars", BARS_SRC, "CCY", "DAILY BARS", "price", "dividends splits total return", ("adj",)),
    _f("ret", "RETURN SINCE THE FIRST ROW", "bars", BARS_SRC, "RATIO", "DAILY BARS", "pct", "performance cumulative", ("c",)),
    _f("vol", "VOLUME", "bars", BARS_SRC, "SHARES", "DAILY BARS", "int", "volume history", ("v",)),
    _f("value", "FRED SERIES VALUE (FOR FRED:<ID>)", "fred", "FRED (KEYLESS CSV)", "AS PUBLISHED", "AS PUBLISHED", "num", "macro economic series", ("v",)),
)}
SNAPSHOT_GROUPS = ("quote", "screener", "stats")
SERIES_GROUPS = ("bars", "fred")
OPS = ("<=", ">=", "!=", "<", ">", "=")


@dataclass
class Cond:
    field: str
    op: str
    value: float | str


@dataclass
class Query:
    fields: list[str]
    universe: str  # a universe word, "LIST:..." for a comma list, or "US"
    where: list[Cond] = field(default_factory=list)
    sort: str | None = None
    desc: bool = True
    limit: int = DEFAULT_LIMIT
    dates: tuple[date, date] | None = None
    freq: str = "D"

    @property
    def series(self) -> bool:
        return self.dates is not None


_CLAUSE = re.compile(r"\b(FOR|WHERE|SORT|LIMIT|DATES|FREQ)\b", re.IGNORECASE)
_REL = re.compile(r"^-(\d+)([DWMY])$", re.IGNORECASE)


def parse_when(word: str, today: date) -> date:
    w = word.strip().upper()
    if w in ("0", "TODAY", "NOW"):
        return today
    m = _REL.match(w)
    if m:
        n, u = int(m.group(1)), m.group(2)
        days = {"D": 1, "W": 7, "M": 30.4375, "Y": 365.25}[u] * n
        return today - timedelta(days=round(days))
    try:
        return date.fromisoformat(w)
    except ValueError as e:
        raise QueryError(f"DATE {word[:12]}: USE -1Y, -6M, -30D, 0 OR YYYY-MM-DD") from e


def _cond(text: str) -> Cond:
    t = text.strip()
    for op in OPS:
        if op in t:
            name, _, val = t.partition(op)
            name, val = name.strip().lower(), val.strip().strip("'\"")
            if name not in FIELDS:
                raise QueryError(f"UNKNOWN FIELD IN WHERE: {name[:20]} (FLD LISTS THEM)")
            if not val:
                raise QueryError(f"NO VALUE IN: {t[:30]}")
            if FIELDS[name].kind == "text":
                return Cond(name, op, val.upper())
            try:
                num = float(val.replace(",", "").rstrip("%"))
            except ValueError as e:
                raise QueryError(f"NOT A NUMBER: {val[:20]} (IN {t[:30]})") from e
            if val.endswith("%") or FIELDS[name].unit == "RATIO" and abs(num) > 1:
                num /= 100.0  # "divy>3%" and "divy>3" both mean 3 percent: ratio fields are stored as ratios
            return Cond(name, op, num)
    raise QueryError(f"NO COMPARISON IN: {t[:30]} (USE < <= > >= = !=)")


def parse(text: str, today: date | None = None) -> Query:
    today = today or date.today()
    body = text.strip()
    if body.upper().startswith("QRY "):
        body = body[4:]
    parts = _CLAUSE.split(body)
    head, rest = parts[0], parts[1:]
    fields = [f.strip().lower() for f in head.split(",") if f.strip()]
    if not fields:
        raise QueryError("USAGE: QRY <fields> FOR <universe> [WHERE ..] [SORT ..] [LIMIT n] | QRY <fields> FOR <symbols> DATES -1Y..0 [FREQ D|W|M]")
    clauses: dict[str, str] = {}
    for i in range(0, len(rest) - 1, 2):
        k = rest[i].upper()
        if k in clauses:
            raise QueryError(f"{k} GIVEN TWICE")
        clauses[k] = rest[i + 1].strip()
    if "FOR" not in clauses or not clauses["FOR"]:
        raise QueryError("FOR IS MISSING: QRY last FOR AAPL,MSFT")
    unknown = [f for f in fields if f not in FIELDS]
    if unknown:
        raise QueryError(f"UNKNOWN FIELD: {', '.join(unknown)[:40]} (FLD LISTS THEM)")
    q = Query(fields=fields, universe=_universe(clauses["FOR"]))
    if "DATES" in clauses:
        a, sep, b = clauses["DATES"].partition("..")
        if not sep:
            raise QueryError("DATES: <from>..<to>, FOR EXAMPLE -1Y..0")
        q.dates = (parse_when(a, today), parse_when(b, today))
        if q.dates[0] >= q.dates[1]:
            raise QueryError("DATES: THE START MUST BE BEFORE THE END")
        bad = [f for f in fields if FIELDS[f].group not in SERIES_GROUPS]
        if bad:
            raise QueryError(f"WITH DATES USE HISTORY FIELDS (close adj ret vol value), NOT: {', '.join(bad)[:40]}")
        q.freq = (clauses.get("FREQ") or "D").upper()
        if q.freq not in ("D", "W", "M"):
            raise QueryError("FREQ: D, W OR M")
        if "WHERE" in clauses or "SORT" in clauses:
            raise QueryError("WHERE AND SORT WORK ON SNAPSHOTS, NOT WITH DATES")
    else:
        bad = [f for f in fields if FIELDS[f].group not in SNAPSHOT_GROUPS]
        if bad:
            raise QueryError(f"{', '.join(bad)[:40]} NEED DATES (QRY close FOR AAPL DATES -1Y..0)")
        if "FREQ" in clauses:
            raise QueryError("FREQ NEEDS DATES")
    if "WHERE" in clauses:
        q.where = [_cond(c) for c in re.split(r"\bAND\b", clauses["WHERE"], flags=re.IGNORECASE) if c.strip()]
    if "SORT" in clauses:
        words = clauses["SORT"].split()
        q.sort = words[0].lower()
        if q.sort not in FIELDS:
            raise QueryError(f"UNKNOWN SORT FIELD: {q.sort[:20]}")
        if len(words) > 1 and words[1].upper() not in ("ASC", "DESC"):
            raise QueryError("SORT <field> [ASC|DESC]")
        q.desc = not (len(words) > 1 and words[1].upper() == "ASC")
    if "LIMIT" in clauses:
        try:
            q.limit = int(clauses["LIMIT"])
        except ValueError as e:
            raise QueryError("LIMIT: A WHOLE NUMBER") from e
        if not 1 <= q.limit <= MAX_LIMIT:
            raise QueryError(f"LIMIT: 1-{MAX_LIMIT}")
    return q


def _universe(text: str) -> str:
    """A scanner universe word (SPX, MEMB:SPY, WL:X, LIST:A,B, NIFTY50 ...), US, or else a comma list of symbols (FRED:<ID> allowed)."""
    t = text.strip().upper().replace(" ", "")
    if not t:
        raise QueryError("FOR IS EMPTY")
    words = {*INDEX_PROXY, *SCAN_ALIASES, *NIFTY}
    if t == "US" or t in words or t.startswith(("MEMB:", "WL:", "LIST:")):
        return t
    return "LIST:" + t


def needed_groups(q: Query) -> set[str]:
    names = set(q.fields) | {c.field for c in q.where} | ({q.sort} if q.sort else set())
    return {FIELDS[n].group for n in names}


def passes(row: dict, conds: list[Cond]) -> bool:
    """A row passes when every condition holds. A missing value fails its condition (never treated as zero)."""
    for c in conds:
        v = row.get(c.field)
        if v is None:
            return False
        if isinstance(c.value, str):
            a, b = str(v).upper(), c.value
            ok = {"=": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[c.op]
        else:
            a = float(v)
            ok = {"=": a == c.value, "!=": a != c.value, "<": a < c.value, "<=": a <= c.value, ">": a > c.value, ">=": a >= c.value}[c.op]
        if not ok:
            return False
    return True


def sort_rows(rows: list[dict], key: str | None, desc: bool) -> list[dict]:
    if not key:
        return rows
    have = [r for r in rows if r.get(key) is not None]
    rest = [r for r in rows if r.get(key) is None]  # rows without the value go last either way
    return sorted(have, key=lambda r: r[key], reverse=desc) + rest


def resample(points: list[tuple[str, float | None]], freq: str) -> list[tuple[str, float | None]]:
    """Last value of each week (ISO week) or month; D returns the points unchanged. `points` = (YYYY-MM-DD, value) ascending."""
    if freq == "D":
        return points
    out: dict[str, tuple[str, float | None]] = {}
    for d, v in points:
        if v is None:
            continue
        dd = date.fromisoformat(d)
        k = f"{dd.isocalendar()[0]}-W{dd.isocalendar()[1]:02d}" if freq == "W" else d[:7]
        out[k] = (d, v)
    return list(out.values())


def search_fields(words: str) -> list[Field]:
    """FLD: fields whose name, label, source or search words contain every word typed."""
    ws = [w.lower() for w in words.split() if w.strip()]
    out = []
    for f in FIELDS.values():
        hay = f"{f.name} {f.label} {f.group} {f.source} {f.words}".lower()
        if all(w in hay for w in ws):
            out.append(f)
    return out
