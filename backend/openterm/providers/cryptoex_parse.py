"""Pure parsers for the Kraken and Coinbase Exchange public market-data answers (no network, no pandas).

Both are SPOT exchanges that quote in real dollars (USD) as well as USDT, so a USD pair is a different instrument from a USDT pair:
the quote currency is carried through every result (Bars.currency, Coin.quote, the depth ladder) and is never swapped silently.

Kraken's naming is odd, so it is handled here and nowhere else:
  - Bitcoin is XBT and Dogecoin is XDG in its pair names (`XBTUSD`, `XDGUSD`);
  - the answer's result key is NOT always the pair you asked for: for the oldest assets it is `XXBTZUSD` (X + base + Z + quote);
  - every error comes back as HTTP 200 with a non-empty `error` list, so a 200 must be read, never trusted.
Coinbase's candle rows are `[time, LOW, HIGH, OPEN, CLOSE, volume]` (note the order) and arrive newest first.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..models import Bars, Coin
from ..ranges import range_days
from .base import ProviderError
from .crypto import _BAR_DAYS

# `BTC-USD`, `ETH-USDT`, `SOL-EUR`: the app's canonical crypto spelling (symbols.resolve turns BTCUSD / BTCUSDT into it).
# The dash is required on purpose: without it `ABUSD` could just as well be a share, and a share must never reach a crypto exchange.
_PAIR = re.compile(r"^([A-Z0-9]{2,10})-(USDT|USD|EUR|GBP)$")

KRAKEN_BASE = {"BTC": "XBT", "DOGE": "XDG"}  # the two bases Kraken spells differently


def split_pair(symbol: str) -> tuple[str, str] | None:
    """`btc-usdt` -> ("BTC", "USDT"); None for anything that is not a crypto pair in the app's spelling."""
    m = _PAIR.match(symbol.strip().upper())
    return (m.group(1), m.group(2)) if m else None


def bars_wanted(range_: str, interval: str) -> int:
    """How many candles a range asks for at a candle length (1Y at 1d = 366)."""
    return max(2, int(range_days(range_) / _BAR_DAYS[interval]))


def depth_text(interval: str, days: float) -> str:
    """The sentence the router and the chart expect ("... ONLY AVAILABLE FOR THE LAST N DAYS"; hours when under a day)."""
    return f"INTERVAL {interval} ONLY AVAILABLE FOR THE LAST {int(days)} DAYS" if days >= 1 else f"INTERVAL {interval} ONLY AVAILABLE FOR THE LAST {int(days * 24)} HOURS"


def make_bars(rows: list[tuple[int, float, float, float, float, float]], symbol: str, range_: str, interval: str, quote: str,
              exchange: str, source: str, want: int) -> Bars:
    """Candle tuples (oldest first) -> the app's columnar Bars, newest `want` only. `currency` is the pair's real quote (USD or USDT).

    Volume is truncated to a whole coin because Bars.v is an integer column (Binance candles do the same); this is the coin count, not value.
    """
    rows = rows[-want:]
    return Bars.model_construct(
        symbol=symbol, range=range_, interval=interval, currency=quote, exchange=exchange, tz="UTC",
        t=[r[0] for r in rows], o=[r[1] for r in rows], h=[r[2] for r in rows], l=[r[3] for r in rows], c=[r[4] for r in rows],
        v=[int(r[5]) for r in rows], source=source, as_of=time.time(),
    )


def _f(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# --- Kraken ----------------------------------------------------------------------------------------------------------------
def kraken_asset(code: str) -> str:
    """BTC -> XBT, DOGE -> XDG, everything else unchanged. Works for a quote too (ETH/BTC is `ETHXBT`)."""
    return KRAKEN_BASE.get(code, code)


def kraken_pair(base: str, quote: str) -> str:
    """The pair name Kraken's REST API accepts: BTC + USD -> `XBTUSD`."""
    return kraken_asset(base) + kraken_asset(quote)


def kraken_unwrap(body: Any, what: str) -> Any:
    """Return `body["result"]`, or raise the right ProviderError for Kraken's HTTP-200 error answers.

    EQuery:Unknown asset pair -> not_found (the pair is not listed: the next source gets a go, no circuit-breaker strike);
    EAPI:Rate limit / EGeneral:Temporary lockout -> rate_limited; anything else (EGeneral:Invalid arguments is OUR bug) -> unavailable.
    """
    if not isinstance(body, dict):
        raise ProviderError("unavailable", f"KRAKEN {what}: UNEXPECTED ANSWER")
    errors = [str(e) for e in (body.get("error") or [])]
    if errors:
        if any(e.startswith("EQuery:Unknown asset pair") for e in errors):
            raise ProviderError("not_found", f"KRAKEN {what}: PAIR NOT LISTED")
        if any(e.startswith(("EAPI:Rate limit", "EGeneral:Temporary lockout")) for e in errors):
            raise ProviderError("rate_limited", f"KRAKEN {what}: {'; '.join(errors)}")
        raise ProviderError("unavailable", f"KRAKEN {what}: {'; '.join(errors)}")
    result = body.get("result")
    if not isinstance(result, dict) or not result:
        raise ProviderError("unavailable", f"KRAKEN {what}: EMPTY RESULT")
    return result


def kraken_single(result: dict, what: str) -> Any:
    """The one pair in a single-pair answer (its key is not the name we asked for, and OHLC adds a `last` key)."""
    keys = [k for k in result if k != "last"]
    if len(keys) != 1:
        raise ProviderError("unavailable", f"KRAKEN {what}: EXPECTED ONE PAIR, GOT {len(keys)}")
    return result[keys[0]]


def parse_kraken_ohlc(body: Any) -> list[tuple[int, float, float, float, float, float]]:
    """OHLC answer -> [(time, open, high, low, close, volume)] oldest first.

    Kraken rows are [time, open, high, low, close, vwap, volume, count] with the prices as strings. The LAST row is the candle still
    forming (the answer's `last` field points at the last finished one); it is kept because a chart wants the live bar.
    """
    rows = kraken_single(kraken_unwrap(body, "OHLC"), "OHLC")
    out = {}
    for r in rows:
        o, h, lo, c, v = _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[6])
        if None in (o, h, lo, c, v):
            raise ProviderError("unavailable", "KRAKEN OHLC: A CANDLE HAS A NON-NUMERIC FIELD")
        out[int(r[0])] = (int(r[0]), o, h, lo, c, v)
    if not out:
        raise ProviderError("not_found", "KRAKEN OHLC: NO CANDLES")
    return [out[t] for t in sorted(out)]


def kraken_ticker_keys(base: str, quote: str) -> set[str]:
    """Every key the Ticker answer may use for one pair: the plain pair name, or the legacy X<base>Z<quote> form."""
    b, q = kraken_asset(base), kraken_asset(quote)
    return {b + q, f"X{b}Z{q}"}


def parse_kraken_ticker(body: Any, bases: tuple[str, ...], quote: str, source: str, as_of: float) -> list[Coin]:
    """Multi-pair Ticker answer -> board rows in the order of `bases`.

    What Kraken gives: c = last trade, h / l = today and last-24h high / low, v = today and last-24h volume in coins, p = volume-weighted
    average price (today, 24h). Quote volume is therefore 24h volume x 24h VWAP (exact, not an estimate).
    What it does NOT give: a 24h price change. `o` is the price at 00:00 UTC TODAY, which is a different window, so the 24h change is
    left empty instead of being mislabelled.
    """
    result = kraken_unwrap(body, "TICKER")
    coins = []
    for base in bases:
        key = next((k for k in kraken_ticker_keys(base, quote) if k in result), None)
        if key is None:
            continue  # a pair that was asked for but not answered is left off the board (the board never invents a row)
        t = result[key]
        price = _f(t["c"][0])
        vol, vwap = _f(t["v"][1]), _f(t["p"][1])
        coins.append(Coin(
            symbol=base, quote=quote, price=price, change_pct_24h=None, high_24h=_f(t["h"][1]), low_24h=_f(t["l"][1]),
            volume_24h=vol * vwap if vol is not None and vwap is not None else None, updated=None, source=source, as_of=as_of,
        ))
    if not coins:
        raise ProviderError("unavailable", "KRAKEN TICKER: NONE OF THE REQUESTED PAIRS CAME BACK")
    return coins


# --- Coinbase Exchange ---------------------------------------------------------------------------------------------------
def parse_coinbase_candles(body: Any) -> list[tuple[int, float, float, float, float, float]]:
    """Candles answer -> [(time, open, high, low, close, volume)] oldest first, de-duplicated by time.

    Coinbase rows are [time, low, high, open, close, volume], newest first. An error answer is a dict ({"message": ...}), not a list.
    """
    if not isinstance(body, list):
        raise ProviderError("unavailable", f"COINBASE CANDLES: {(body or {}).get('message') if isinstance(body, dict) else 'UNEXPECTED ANSWER'}")
    out = {}
    for r in body:
        t, lo, h, o, c, v = int(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5])
        if None in (lo, h, o, c, v):
            raise ProviderError("unavailable", "COINBASE CANDLES: A CANDLE HAS A NON-NUMERIC FIELD")
        out[t] = (t, o, h, lo, c, v)
    return [out[t] for t in sorted(out)]


def parse_coinbase_stats(body: Any, base: str, quote: str, source: str, as_of: float) -> Coin:
    """`/products/<id>/stats` -> one board row.

    open / high / low / last are in the quote currency over a rolling 24h window, so the 24h change is exact: (last - open) / open.
    `volume` is in COINS, not in the quote currency. Multiplying it by some price would be a guess, so volume_24h stays empty.
    """
    if not isinstance(body, dict) or "last" not in body or "open" not in body:
        raise ProviderError("unavailable", "COINBASE STATS: ANSWER HAS NO LAST / OPEN")
    last, open_ = _f(body["last"]), _f(body["open"])
    if last is None or open_ is None or open_ == 0:
        raise ProviderError("unavailable", "COINBASE STATS: NON-NUMERIC OR ZERO OPEN")
    return Coin(symbol=base, quote=quote, price=last, change_pct_24h=(last - open_) / open_ * 100.0, high_24h=_f(body.get("high")),
                low_24h=_f(body.get("low")), volume_24h=None, updated=None, source=source, as_of=as_of)
