"""Broker file parsers: text in, normalised `Trade` rows out. Pure Python (csv, datetime); no pandas.

Formats (all DOC-SHAPED: written from each broker's published column names, not from a recording of a real export):
- Zerodha Console tradebook CSV: symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
- IBKR Flex Query trades CSV: the columns you pick in the query; needs Symbol, a date (DateTime or TradeDate), Buy/Sell or a signed
  Quantity, TradePrice. Uses IBCommission, CurrencyPrimary or Currency, IBOrderID, TradeID, Multiplier, ListingExchange when present.
- Alpaca account activities CSV: id,activity_type,transaction_time,type,price,qty,side,symbol,leaves_qty,order_id,cum_qty,order_status
  (only FILL activities are trades; dividends, fees and transfers are ignored and counted).
- Generic CSV: you map your columns to time, symbol, side, qty, price (and optionally fee, currency, order id).

Rules: a row that cannot be read stops the import and is named by its line (nothing is half-stored). A slash date such as 03/04/2024
is never guessed: choose DMY or MDY. Times are the file's own wall clock (no time zone is invented); Alpaca's UTC times are shown in
New York time, the market they belong to. A fee is always a positive cost.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

BROKERS = ("zerodha", "ibkr", "alpaca", "generic")
MAX_ROWS = 50_000
MAX_TEXT = 4_000_000
NY = ZoneInfo("America/New_York")


class JournalError(ValueError):
    """A file the parser cannot use. `detail` lists the first problems (one line each)."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail


@dataclass
class Trade:
    time: str  # ISO "YYYY-MM-DDTHH:MM:SS", the broker file's wall clock
    symbol: str
    side: str  # "buy" | "sell"
    qty: float  # > 0
    price: float  # > 0
    fee: float  # >= 0
    currency: str
    broker: str
    order_id: str = ""
    trade_id: str = ""
    mult: float = 1.0
    dkey: str = ""

    @property
    def ts(self) -> float:
        return datetime.fromisoformat(self.time).replace(tzinfo=UTC).timestamp()


# ---------------------------------------------------------------- cells
BUY = {"buy", "b", "bought", "bot", "long", "buy to cover", "buy_to_cover", "cover", "buy to open", "buy to close"}
SELL = {"sell", "s", "sold", "sld", "short", "sell short", "sell_short", "sell to open", "sell to close"}


def num(raw: str | None, what: str) -> float:
    s = (raw or "").strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")")  # accounting negative
    s = s.strip("()").lstrip("$€£₹").strip()
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"BAD {what} {raw!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"BAD {what} {raw!r}")
    return -v if neg else v


def side_of(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if s in BUY:
        return "buy"
    if s in SELL:
        return "sell"
    return None


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:[;, T]\s*(\d{2}):?(\d{2}):?(\d{2})?)?$")
_SLASH = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:[ T,]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?)?$")


def when(raw: str | None, order: str | None = None, tz_to: ZoneInfo | None = None) -> str:
    """One date or date-time cell -> ISO wall clock. `order` is "DMY" or "MDY" for slash dates (never guessed)."""
    s = (raw or "").strip().strip('"')
    if not s:
        raise ValueError("EMPTY TIME")
    m = _ISO.match(s)
    try:
        if m:
            y, mo, d, hh, mi, ss, off = m.groups()
            dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
            if off and tz_to is not None:  # an explicit offset: show it in the market's own clock
                if off == "Z":
                    aware = dt.replace(tzinfo=UTC)
                else:
                    o = off.replace(":", "")
                    aware = dt.replace(tzinfo=datetime.strptime(o, "%z").tzinfo)
                dt = aware.astimezone(tz_to).replace(tzinfo=None)
            return dt.isoformat(timespec="seconds")
        m = _COMPACT.match(s)
        if m:
            y, mo, d, hh, mi, ss = m.groups()
            return datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0)).isoformat(timespec="seconds")
        m = _SLASH.match(s)
        if m:
            a, b, y, hh, mi, ss, ap = m.groups()
            if order not in ("DMY", "MDY"):
                raise ValueError(f"SLASH DATE {s!r}: CHOOSE DMY OR MDY")
            day, mon = (int(a), int(b)) if order == "DMY" else (int(b), int(a))
            h = int(hh or 0)
            if ap:
                h = h % 12 + (12 if ap.lower() == "pm" else 0)
            return datetime(int(y), mon, day, h, int(mi or 0), int(ss or 0)).isoformat(timespec="seconds")
    except ValueError as e:
        if "CHOOSE" in str(e):
            raise
        raise ValueError(f"BAD TIME {s!r}") from None
    raise ValueError(f"BAD TIME {s!r}")


def _ccy(raw: str | None, default: str) -> str:
    s = (raw or "").strip().upper()
    return s if re.fullmatch(r"[A-Z]{3}", s) else default


# ---------------------------------------------------------------- reading
Rows = list[tuple[int, dict[str, str]]]


def read_rows(text: str) -> tuple[list[str], Rows]:
    """(header, [(line number, row by lower-cased header)]). The delimiter is sniffed (comma, semicolon, tab)."""
    if len(text) > MAX_TEXT:
        raise JournalError(f"FILE OVER {MAX_TEXT // 1_000_000} MB")
    lines = text.lstrip("﻿").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise JournalError("EMPTY FILE")
    delim = max(",;\t", key=lines[0].count)
    if lines[0].count(delim) == 0:
        raise JournalError("NO COLUMNS FOUND", "THE FIRST LINE MUST BE THE COLUMN NAMES, SEPARATED BY COMMAS")
    rdr = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    header = [h.strip() for h in next(rdr)]
    keys = [h.lower() for h in header]
    out: Rows = []
    for row in rdr:
        if not any(c.strip() for c in row):
            continue
        out.append((rdr.line_num, {k: (row[i].strip() if i < len(row) else "") for i, k in enumerate(keys)}))
        if len(out) > MAX_ROWS:
            raise JournalError(f"MORE THAN {MAX_ROWS} ROWS", "IMPORT THE FILE IN PARTS")
    return header, out


def detect(header: list[str]) -> str | None:
    h = {c.strip().lower() for c in header}
    if {"trade_type", "trade_date", "quantity", "price", "symbol"} <= h:
        return "zerodha"
    if {"transaction_time", "qty", "price", "symbol"} <= h or ("activity_type" in h and "qty" in h):
        return "alpaca"
    if {"symbol", "tradeprice"} <= h and ("buy/sell" in h or "quantity" in h):
        return "ibkr"
    return None


# ---------------------------------------------------------------- per-broker
IBKR_MARKS = {"BOF", "EOF", "BOA", "EOA", "BOS", "EOS", "HEADER", "DATA"}
IBKR_SUFFIX = {"LSE": ".L", "SEHK": ".HK", "TSE": ".TO", "NSE": ".NS", "BSE": ".BO", "VENTURE": ".V"}


def _finish(trades: list[Trade], errs: list[str], ignored: int) -> tuple[list[Trade], int]:
    if errs:
        raise JournalError(f"{len(errs)} ROW{'S' if len(errs) != 1 else ''} COULD NOT BE READ, NOTHING WAS STORED", "\n".join(errs[:12]))
    if not trades:
        raise JournalError("NO TRADES FOUND IN THE FILE", f"{ignored} ROWS WERE NOT TRADES" if ignored else None)
    _keys(trades)
    return trades, ignored


def _keys(trades: list[Trade]) -> None:
    """A stable de-duplication key. A broker trade id decides when there is one; otherwise every field does, and a repeat of the
    very same row inside one file gets its own count, so two real identical fills stay two while a re-import stays a no-op."""
    seen: dict[str, int] = {}
    for t in trades:
        if t.trade_id:
            base = f"{t.broker}|id|{t.trade_id}"
        else:
            base = "|".join([t.broker, t.time, t.symbol, t.side, f"{t.qty:.8g}", f"{t.price:.8g}", t.order_id])
        n = seen[base] = seen.get(base, 0) + 1
        t.dkey = hashlib.sha1(f"{base}#{n}".encode()).hexdigest()[:24]


def parse_zerodha(rows: Rows, order: str | None, ccy: str) -> tuple[list[Trade], int]:
    out: list[Trade] = []
    errs: list[str] = []
    for ln, r in rows:
        try:
            side = side_of(r.get("trade_type"))
            if side is None:
                raise ValueError(f"BAD trade_type {r.get('trade_type')!r}")
            t = when(r.get("order_execution_time") or r.get("trade_date"), order)
            qty, price = num(r.get("quantity"), "quantity"), num(r.get("price"), "price")
            if qty <= 0 or price <= 0:
                raise ValueError("quantity and price must be above 0")
            sym = r.get("symbol", "").strip().upper()
            if not sym:
                raise ValueError("EMPTY symbol")
            suffix = {"NSE": ".NS", "BSE": ".BO"}.get(r.get("exchange", "").strip().upper(), "")
            if r.get("segment", "EQ").strip().upper() not in ("EQ", ""):
                suffix = ""  # F&O, currency and commodity contracts have no daily-bar symbol
            out.append(Trade(t, sym + suffix, side, qty, price, 0.0, "INR", "zerodha", r.get("order_id", ""), r.get("trade_id", "")))
        except ValueError as e:
            errs.append(f"LINE {ln}: {e}")
    return _finish(out, errs, 0)


def parse_ibkr(rows: Rows, order: str | None, ccy: str) -> tuple[list[Trade], int]:
    out: list[Trade] = []
    errs: list[str] = []
    ignored = 0
    for ln, r in rows:
        first = next(iter(r.values()), "")
        if (first.upper() in IBKR_MARKS and not r.get("symbol")) or r.get("symbol", "").lower() == "symbol":
            ignored += 1  # section markers and repeated header lines of a multi-section Flex file
            continue
        try:
            q = num(r.get("quantity"), "Quantity")
            bs = r.get("buy/sell", "")
            side = side_of(bs) if bs else ("buy" if q > 0 else "sell")
            if side is None:
                raise ValueError(f"BAD Buy/Sell {bs!r}")
            stamp = r.get("datetime") or r.get("tradedatetime") or r.get("tradedate") or r.get("date/time") or ""
            if not stamp:
                raise ValueError("NO DateTime OR TradeDate")
            t = when(stamp, order)
            price = num(r.get("tradeprice"), "TradePrice")
            qty = abs(q)
            if qty <= 0 or price <= 0:
                raise ValueError("Quantity and TradePrice must be above 0")
            fee = abs(num(r.get("ibcommission") or r.get("commission") or "0", "IBCommission"))
            mult = abs(num(r.get("multiplier") or "1", "Multiplier")) or 1.0
            sym = r.get("symbol", "").strip().upper()
            if not sym:
                raise ValueError("EMPTY Symbol")
            sfx = IBKR_SUFFIX.get((r.get("listingexchange") or "").strip().upper(), "")
            cur = _ccy(r.get("currencyprimary") or r.get("currency"), ccy)
            out.append(Trade(t, sym + sfx, side, qty, price, fee, cur, "ibkr", r.get("iborderid", ""), r.get("tradeid", ""), mult))
        except ValueError as e:
            errs.append(f"LINE {ln}: {e}")
    return _finish(out, errs, ignored)


def parse_alpaca(rows: Rows, order: str | None, ccy: str) -> tuple[list[Trade], int]:
    out: list[Trade] = []
    errs: list[str] = []
    ignored = 0
    for ln, r in rows:
        kind = (r.get("activity_type") or "FILL").strip().upper()
        if kind != "FILL" or (r.get("type") or "fill").strip().lower() not in ("fill", "partial_fill"):
            ignored += 1  # dividends, fees, journals, transfers
            continue
        try:
            side = side_of(r.get("side"))
            if side is None:
                raise ValueError(f"BAD side {r.get('side')!r}")
            t = when(r.get("transaction_time"), order, tz_to=NY)
            qty, price = num(r.get("qty"), "qty"), num(r.get("price"), "price")
            if qty <= 0 or price <= 0:
                raise ValueError("qty and price must be above 0")
            sym = r.get("symbol", "").strip().upper().replace("/", "-")
            if not sym:
                raise ValueError("EMPTY symbol")
            out.append(Trade(t, sym, side, qty, price, 0.0, "USD", "alpaca", r.get("order_id", ""), r.get("id", "")))
        except ValueError as e:
            errs.append(f"LINE {ln}: {e}")
    return _finish(out, errs, ignored)


MAP_KEYS = ("time", "date", "symbol", "side", "qty", "price", "fee", "currency", "order_id")
GUESS = {
    "time": ("time", "when", "datetime", "date/time", "timestamp", "executed at", "filled at", "date", "trade date"),
    "date": ("date", "trade date", "tradedate"),
    "symbol": ("symbol", "ticker", "instrument", "security", "code"),
    "side": ("side", "action", "buy/sell", "type", "trade type", "direction", "b/s"),
    "qty": ("qty", "quantity", "shares", "size", "units", "filled"),
    "price": ("price", "fill", "fill price", "avg price", "trade price", "executed price"),
    "fee": ("fee", "fees", "commission", "commissions", "charges"),
    "currency": ("currency", "ccy", "curr"),
    "order_id": ("order id", "order_id", "orderid", "order", "id", "trade id"),
}


def guess_mapping(header: list[str]) -> dict[str, str]:
    """A first guess at the generic mapping from common column names; the user confirms or changes it."""
    low = {h.strip().lower(): h for h in header}
    out: dict[str, str] = {}
    for k, names in GUESS.items():
        for n in names:
            if n in low and low[n] not in out.values():
                out[k] = low[n]
                break
    return out


def parse_generic(rows: Rows, order: str | None, ccy: str, mapping: dict[str, str], header: list[str]) -> tuple[list[Trade], int]:
    have = {h.strip().lower() for h in header}
    m = {k: v.strip().lower() for k, v in mapping.items() if isinstance(v, str) and v.strip()}
    for k, v in m.items():
        if k not in MAP_KEYS:
            raise JournalError(f"UNKNOWN MAPPING KEY {k.upper()}", f"USE {', '.join(MAP_KEYS)}")
        if v not in have:
            raise JournalError(f"MAPPED COLUMN {v.upper()} IS NOT IN THE FILE", f"COLUMNS: {', '.join(header)}")
    need = [k for k in ("symbol", "qty", "price") if k not in m]
    if "time" not in m and "date" not in m:
        need.insert(0, "time")
    if need:
        raise JournalError(f"MAP THESE COLUMNS: {', '.join(n.upper() for n in need)}", "side is optional when qty is negative for sells")
    out: list[Trade] = []
    errs: list[str] = []
    for ln, r in rows:
        try:
            if "time" in m and "date" in m and m["time"] != m["date"]:
                stamp = f"{r.get(m['date'], '').strip()} {r.get(m['time'], '').strip()}".strip()
            else:
                stamp = r.get(m.get("time") or m["date"], "")
            t = when(stamp, order)
            q = num(r.get(m["qty"]), "qty")
            if "side" in m:
                side = side_of(r.get(m["side"]))
                if side is None:
                    raise ValueError(f"BAD side {r.get(m['side'])!r}")
            else:
                side = "buy" if q > 0 else "sell"
            price, qty = num(r.get(m["price"]), "price"), abs(q)
            if qty <= 0 or price <= 0:
                raise ValueError("qty and price must be above 0")
            sym = r.get(m["symbol"], "").strip().upper()
            if not sym:
                raise ValueError("EMPTY symbol")
            fee = abs(num(r.get(m["fee"]) or "0", "fee")) if "fee" in m else 0.0
            cur = _ccy(r.get(m["currency"]) if "currency" in m else "", ccy)
            out.append(Trade(t, sym, side, qty, price, fee, cur, "generic", r.get(m.get("order_id", ""), ""), ""))
        except ValueError as e:
            errs.append(f"LINE {ln}: {e}")
    return _finish(out, errs, 0)


# ---------------------------------------------------------------- entry points
def inspect(text: str) -> dict:
    """What the file looks like, for the mapping step: detected broker, columns, a guess at the generic mapping, a few raw rows."""
    header, rows = read_rows(text)
    return {"broker": detect(header), "columns": header, "rows": len(rows), "mapping": guess_mapping(header),
            "sample": [{h: r.get(h.lower(), "") for h in header} for _, r in rows[:5]]}


def parse(text: str, broker: str = "auto", mapping: dict | None = None, date_order: str | None = None,
          currency: str = "USD") -> tuple[str, list[Trade], int]:
    """(broker, trades, ignored rows). Raises JournalError with the reason when the file cannot be used."""
    if broker not in ("auto", *BROKERS):
        raise JournalError(f"BROKER MUST BE auto, {', '.join(BROKERS)}")
    if date_order is not None and date_order not in ("DMY", "MDY"):
        raise JournalError("DATE ORDER MUST BE DMY OR MDY")
    ccy = _ccy(currency, "")
    if not ccy:
        raise JournalError("CURRENCY MUST BE A 3-LETTER CODE")
    header, rows = read_rows(text)
    kind = detect(header) if broker == "auto" else broker
    if kind is None:
        raise JournalError("FORMAT NOT RECOGNISED: MAP THE COLUMNS (GENERIC)", f"COLUMNS: {', '.join(header)}")
    if kind == "zerodha":
        trades, ign = parse_zerodha(rows, date_order, ccy)
    elif kind == "ibkr":
        trades, ign = parse_ibkr(rows, date_order, ccy)
    elif kind == "alpaca":
        trades, ign = parse_alpaca(rows, date_order, ccy)
    else:
        trades, ign = parse_generic(rows, date_order, ccy, mapping or guess_mapping(header), header)
    return kind, trades, ign
