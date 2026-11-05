"""Upstox helpers that need no network: symbol mapping, candle windows, and parsers for the documented answers. Pure.

Written from the official Upstox developer docs (V3 historical candles, V3 market quote OHLC, instruments files), NOT from
recorded responses: no Upstox token was available when this was built. Where the docs say nothing (for example how a quote
answer's keys relate to the instrument key) the code does not guess; it matches on a field the docs do show.
"""

from __future__ import annotations

import gzip
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote as urlquote

from .base import ProviderError

BASE = "https://api.upstox.com"
INSTRUMENT_FILES = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
)

#: Yahoo-style index symbols -> Upstox instrument keys (documented format `SEGMENT|name`).
INDEX_KEYS = {
    "^NSEI": ("NSE_INDEX|Nifty 50", "NSE", "NIFTY 50"),
    "^NSEBANK": ("NSE_INDEX|Nifty Bank", "NSE", "NIFTY BANK"),
    "^BSESN": ("BSE_INDEX|SENSEX", "BSE", "SENSEX"),
}
SUFFIX_SEGMENT = {".NS": ("NSE_EQ", "NSE"), ".BO": ("BSE_EQ", "BSE")}

#: Our interval -> (Upstox unit, Upstox interval). V3 allows minutes 1-300, hours 1-5, days/weeks/months 1.
INTERVAL_PLAN = {
    "1m": ("minutes", 1), "2m": ("minutes", 2), "5m": ("minutes", 5), "15m": ("minutes", 15), "30m": ("minutes", 30),
    "60m": ("hours", 1), "90m": ("minutes", 90), "1d": ("days", 1), "1wk": ("weeks", 1), "1mo": ("months", 1),
}
INTRADAY_SINCE = date(2022, 1, 1)  # docs: minute and hour candles are available from January 2022
DAILY_SINCE = date(2000, 1, 1)  # docs: day, week and month candles from January 2000


def classify(symbol: str) -> tuple[str, str, str, str] | None:
    """`RELIANCE.NS` -> ("equity", "NSE_EQ", "NSE", "RELIANCE"); `^NSEI` -> ("index", key, "NSE", "NIFTY 50"); None for anything else."""
    s = symbol.strip().upper()
    if s in INDEX_KEYS:
        key, exchange, name = INDEX_KEYS[s]
        return "index", key, exchange, name
    for suffix, (segment, exchange) in SUFFIX_SEGMENT.items():
        if s.endswith(suffix) and len(s) > len(suffix):
            return "equity", segment, exchange, s[: -len(suffix)]
    return None


def window_days(unit: str, interval: int) -> int | None:
    """Longest date span one candle request may cover, a little under the documented limit. None = no limit (weeks, months)."""
    if unit == "minutes":
        return 28 if interval <= 15 else 85  # docs: 1 month up to 15 minutes, 1 quarter above
    if unit == "hours":
        return 85  # docs: 1 quarter
    if unit == "days":
        return 3600  # docs: 1 decade
    return None


def since(unit: str) -> date:
    return INTRADAY_SINCE if unit in ("minutes", "hours") else DAILY_SINCE


def depth_days(today: date) -> int:
    """Days of minute/hour history Upstox holds, counted back from today (it starts in January 2022)."""
    return (today - INTRADAY_SINCE).days


def windows(end: date, days: int, unit: str, interval: int) -> list[tuple[date, date]]:
    """Date windows (from, to), oldest first, that together cover `days` back from `end` without passing a request limit
    or the date the data starts."""
    start = max(end - timedelta(days=days), since(unit))
    span = window_days(unit, interval)
    if span is None or (end - start).days <= span:
        return [(start, end)]
    out: list[tuple[date, date]] = []
    to = end
    while to >= start:  # >=, not >: a window can end the day after `start`, and that first day must still be fetched
        frm = max(to - timedelta(days=span), start)
        out.append((frm, to))
        to = frm - timedelta(days=1)
    return out[::-1]


def candle_path(instrument_key: str, unit: str, interval: int, frm: date, to: date) -> str:
    """Documented V3 route: /v3/historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}."""
    return f"/v3/historical-candle/{urlquote(instrument_key, safe='')}/{unit}/{interval}/{to.isoformat()}/{frm.isoformat()}"


def parse_candles(rows: object) -> list[list]:
    """The `data.candles` list -> rows [epoch seconds, o, h, l, c, volume, open interest], oldest first, duplicates dropped.

    Each documented candle is [ISO timestamp with +05:30, open, high, low, close, volume, open interest]. A row that does not
    look like that is an error, not a skipped line: prices must never be guessed."""
    if not isinstance(rows, list):
        raise ProviderError("unavailable", "Upstox candles are not a list")
    out: dict[int, list] = {}
    for r in rows:
        try:
            ts = int(datetime.fromisoformat(r[0]).timestamp())
            out[ts] = [ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5]), float(r[6]) if len(r) > 6 and r[6] is not None else 0.0]
        except (TypeError, ValueError, IndexError, KeyError) as e:
            raise ProviderError("unavailable", f"unexpected Upstox candle shape: {type(e).__name__}") from e
    return [out[t] for t in sorted(out)]


def parse_quotes(data: object, wanted: dict[str, str]) -> list[dict]:
    """OHLC V3 `data` -> [{symbol, price, prev_close, open, high, low, volume}] for the requested instruments.

    `wanted` maps instrument key -> Yahoo-style symbol. The docs show response keys such as `NSE_FO:NIFTY2543021600PE` and
    do not say how they relate to the `NSE_FO|51834` key we asked for, so entries are matched on their `instrument_token`
    field (the documented `|` form) and the response key is ignored."""
    if not isinstance(data, dict):
        raise ProviderError("unavailable", "Upstox quotes are not an object")
    out = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        symbol = wanted.get(str(entry.get("instrument_token")))
        last = entry.get("last_price")
        if symbol is None or last is None:
            continue
        live, prev = entry.get("live_ohlc") or {}, entry.get("prev_ohlc") or {}
        out.append({"symbol": symbol, "price": float(last), "prev_close": prev.get("close"), "open": live.get("open"),
                    "high": live.get("high"), "low": live.get("low"), "volume": live.get("volume")})
    return out


_FLAT_OBJECT = re.compile(rb"\{[^{}]*\}")


def parse_instruments(raw: bytes) -> dict[str, dict]:
    """A downloaded `NSE.json.gz` / `BSE.json.gz` (or its plain JSON) -> {"NSE_EQ:RELIANCE": {key, name, isin}, ...}.

    Only cash-equity rows are kept (the file also holds hundreds of thousands of option contracts). Records are flat JSON
    objects, so they are pulled out one by one and only the equity ones are decoded: that keeps memory small. If that finds no
    equities the file is decoded whole, and if there are still none the shape changed and this says so (never an empty table).
    BSE rows are also indexed by exchange token (`BSE_EQ:500325`), because Yahoo's `.BO` symbols are often the scrip code."""
    if raw[:2] == b"\x1f\x8b":  # a server may already have un-gzipped the body; only decompress when it is still gzip
        raw = gzip.decompress(raw)
    rows: list[dict] = []
    for m in _FLAT_OBJECT.finditer(raw):
        chunk = m.group(0)
        if b'"NSE_EQ"' in chunk or b'"BSE_EQ"' in chunk:
            try:
                rows.append(json.loads(chunk))
            except ValueError:
                continue
    if not rows:
        try:
            whole = json.loads(raw)
        except ValueError as e:
            raise ProviderError("unavailable", "Upstox instruments file is not JSON") from e
        rows = [r for r in whole if isinstance(r, dict) and r.get("segment") in ("NSE_EQ", "BSE_EQ")] if isinstance(whole, list) else []
    table: dict[str, dict] = {}
    for r in rows:
        segment, key, trading = r.get("segment"), r.get("instrument_key"), str(r.get("trading_symbol") or "").upper()
        if segment not in ("NSE_EQ", "BSE_EQ") or not key or "|" not in str(key) or not trading:
            continue
        rec = {"key": key, "name": r.get("name") or r.get("short_name"), "isin": r.get("isin")}
        eq = r.get("instrument_type") == "EQ"
        for k in (f"{segment}:{trading}", f"{segment}:{r['exchange_token']}" if segment == "BSE_EQ" and r.get("exchange_token") else None):
            if k and (k not in table or eq):  # on a duplicate name, the plain EQ series wins
                table[k] = rec
    if not table:
        raise ProviderError("unavailable", "Upstox instruments file has no equity rows (format changed?)")
    return table
