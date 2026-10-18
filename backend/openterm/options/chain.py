"""Option chain parsing and per-contract IV / Greeks (spec docs/specs/PHASE_14.md decisions D, E). Pure: no I/O, no clock.

A provider answers one normalised chain:

    {symbol, spot, quote_time, expirations:[epoch..], expiry:epoch, calls:[contract..], puts:[contract..],
     vendor_greeks: bool, source}

and a contract is {strike, bid, ask, last, volume, oi, iv_vendor, itm, greeks?}. `greeks` is present only when the vendor sent
its own (Tradier). Yahoo sends none, so IV and the Greeks are computed here from the bid/ask mid (Black-Scholes, European) and
every row says where its IV came from.
"""

from __future__ import annotations

import math
from typing import Any

from ..providers.base import ProviderError

MIN_VENDOR_IV = 0.01   # Yahoo prints 1e-05 style placeholders for contracts with no market; below 1 vol point is not an IV
SECONDS_PER_YEAR = 365.0 * 86400.0
EXPIRY_CLOSE_UTC_HOUR = 20   # 16:00 New York in daylight time; the standard-time hour (21) differs by one hour of a day count


def years_to_expiry(expiry_epoch: int, now_epoch: float) -> float:
    """Spec C: expiry date at 16:00 New York minus now, over 365 calendar days. Floors at 0 (an expiring contract)."""
    close = expiry_epoch + EXPIRY_CLOSE_UTC_HOUR * 3600
    return max(0.0, (close - now_epoch) / SECONDS_PER_YEAR)


def contract(c: dict) -> dict:
    return {
        "strike": float(c["strike"]), "bid": c.get("bid"), "ask": c.get("ask"), "last": c.get("lastPrice"),
        "volume": c.get("volume"), "oi": c.get("openInterest", 0), "iv_vendor": c.get("impliedVolatility"),
        "itm": bool(c.get("inTheMoney")),
    }


def parse_yahoo_chain(body: dict, requested: int | None, source: str) -> dict:
    """Yahoo `v7/finance/options` -> the normalised chain. A date Yahoo does not list is not_found, never the nearest expiry."""
    result = (body.get("optionChain") or {}).get("result")
    if not result:
        raise ProviderError("not_found", "no option chain")
    r0 = result[0]
    quote = r0.get("quote") or {}
    spot = quote.get("regularMarketPrice")
    options = r0.get("options") or []
    if spot is None or not options:
        raise ProviderError("not_found", "no option chain")
    opt = options[0]
    expiry = opt.get("expirationDate")
    if requested is not None and expiry != requested:
        raise ProviderError("not_found", "expiry not listed")
    return {
        "symbol": r0.get("underlyingSymbol") or quote.get("symbol"), "spot": float(spot),
        "quote_time": quote.get("regularMarketTime"), "currency": quote.get("currency"),
        "expirations": list(r0.get("expirationDates") or []), "expiry": expiry,
        "calls": [contract(c) for c in opt.get("calls") or []], "puts": [contract(c) for c in opt.get("puts") or []],
        "vendor_greeks": False, "source": source,
    }


def mid_price(c: dict) -> float | None:
    bid, ask = c.get("bid"), c.get("ask")
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2.0


def solved_iv(c: dict, kind: str, S: float, T: float, r: float, q: float) -> tuple[float | None, str | None]:
    """(IV, source) for one contract: solved from the mid when there is a two-sided market, else the vendor's IV above the
    placeholder floor, else nothing. The source is MID, YAHOO (the vendor) or None."""
    from ..quant import options as qo

    mid = mid_price(c)
    if mid is not None and T > 0:
        try:
            iv = qo.implied_volatility(mid, S, c["strike"], T, r, kind, q)
        except ValueError:
            iv = float("nan")
        if math.isfinite(iv) and iv >= MIN_VENDOR_IV:
            return iv, "MID"
    v = c.get("iv_vendor")
    if v is not None and v >= MIN_VENDOR_IV:
        return float(v), "YAHOO"
    return None, None


def greeks_row(c: dict, kind: str, S: float, T: float, r: float, q: float) -> dict:
    """The five Greeks plus IV and its source for one contract, or Nones when no IV exists (never a made-up volatility)."""
    from ..quant import options as qo

    vg = c.get("greeks")
    if vg:   # vendor Greeks (Tradier): shown as sent, labelled VENDOR
        return {"iv": vg.get("iv"), "iv_src": "VENDOR", "delta": vg.get("delta"), "gamma": vg.get("gamma"),
                "theta": vg.get("theta"), "vega": vg.get("vega"), "rho": vg.get("rho")}
    iv, src = solved_iv(c, kind, S, T, r, q)
    if iv is None:
        return {"iv": None, "iv_src": None, "delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}
    g: dict[str, Any] = qo.bs_greeks(S, c["strike"], T, r, iv, kind, q)
    return {"iv": iv, "iv_src": src, **g}


def atm_iv(rows_calls: list[dict], rows_puts: list[dict], spot: float) -> float | None:
    """ATM IV of one expiry: the two strikes bracketing the spot, calls and puts averaged, interpolated linearly in strike."""
    pts: dict[float, list[float]] = {}
    for r in (*rows_calls, *rows_puts):
        if r.get("iv") is not None:
            pts.setdefault(r["strike"], []).append(r["iv"])
    ks = sorted(pts)
    if not ks:
        return None
    avg = {k: sum(v) / len(v) for k, v in pts.items()}
    below = [k for k in ks if k <= spot]
    above = [k for k in ks if k >= spot]
    if not below or not above:
        return avg[min(ks, key=lambda k: abs(k - spot))]
    lo, hi = below[-1], above[0]
    if lo == hi:
        return avg[lo]
    w = (spot - lo) / (hi - lo)
    return avg[lo] * (1 - w) + avg[hi] * w


def listed(v: Any) -> list:
    """Tradier answers a list, or the bare object when there is exactly one, or null."""
    return [] if v is None else v if isinstance(v, list) else [v]


def epoch_of(day: str) -> int:
    from datetime import UTC, datetime

    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())


def parse_tradier_chain(symbol: str, expirations: dict, chain: dict, quote: dict, requested_day: str, source: str) -> dict:
    """Tradier expirations + chains (greeks=true) + quotes -> the normalised chain, vendor Greeks attached per contract."""
    days = listed(((expirations or {}).get("expirations") or {}).get("date"))
    options = listed(((chain or {}).get("options") or {}).get("option"))
    q = listed(((quote or {}).get("quotes") or {}).get("quote"))
    if not days or not options or not q or q[0].get("last") is None:
        raise ProviderError("not_found", "no option chain")

    def one(o: dict) -> dict:
        g = o.get("greeks") or {}
        out = {"strike": float(o["strike"]), "bid": o.get("bid"), "ask": o.get("ask"), "last": o.get("last"),
               "volume": o.get("volume"), "oi": o.get("open_interest", 0), "iv_vendor": g.get("mid_iv"), "itm": False}
        if g:
            out["greeks"] = {"iv": g.get("mid_iv"), "delta": g.get("delta"), "gamma": g.get("gamma"), "theta": g.get("theta"),
                             "vega": g.get("vega"), "rho": g.get("rho")}
        return out

    return {
        "symbol": symbol, "spot": float(q[0]["last"]), "quote_time": (q[0].get("trade_date") or 0) / 1000 or None, "currency": "USD",
        "expirations": [epoch_of(d) for d in days], "expiry": epoch_of(requested_day),
        "calls": [one(o) for o in options if o.get("option_type") == "call"],
        "puts": [one(o) for o in options if o.get("option_type") == "put"],
        "vendor_greeks": True, "source": source,
    }


_MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def deribit_expiry(token: str) -> int:
    """`27NOV26` -> epoch of 08:00 UTC that day (Deribit settles at 08:00 UTC)."""
    from datetime import UTC, datetime

    day, mon, yr = int(token[:-5]), _MONTHS[token[-5:-2]], 2000 + int(token[-2:])
    return int(datetime(yr, mon, day, 8, tzinfo=UTC).timestamp())


def parse_deribit(book: dict, index: dict, currency: str, source: str) -> dict:
    """Deribit book summaries + index price -> {currency, index, expiries:[{expiry, forward, calls, puts}], source}. IV is `mark_iv`
    (percent) as a ratio; the forward of an expiry is the median `underlying_price` of its instruments."""
    rows = (book or {}).get("result") or []
    idx = ((index or {}).get("result") or {}).get("index_price")
    if not rows or idx is None:
        raise ProviderError("not_found", "no option book")
    by: dict[int, dict] = {}
    unders: dict[int, list[float]] = {}
    for r in rows:
        try:
            _, tok, strike, kind = str(r["instrument_name"]).split("-")
            ep = deribit_expiry(tok)
        except (KeyError, ValueError):
            continue
        iv = r.get("mark_iv")
        if iv is None or iv <= 0:
            continue
        e = by.setdefault(ep, {"expiry": ep, "forward": None, "calls": [], "puts": []})
        unders.setdefault(ep, []).append(float(r["underlying_price"]))
        e["calls" if kind == "C" else "puts"].append({"strike": float(strike), "iv": iv / 100.0, "oi": r.get("open_interest") or 0,
                                                     "volume": r.get("volume") or 0})
    for ep, e in by.items():
        u = sorted(unders[ep])
        e["forward"] = u[len(u) // 2]
    if not by:
        raise ProviderError("not_found", "no option book")
    return {"currency": currency, "index": float(idx), "expiries": [by[k] for k in sorted(by)], "source": source}
