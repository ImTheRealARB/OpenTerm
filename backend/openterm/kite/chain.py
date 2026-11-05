"""OMON and CT for NFO / MCX underlyings from the Kite instruments dump and `GET /quote` (spec "Chains"). Pure payload building plus the
quote calls; nothing here talks to anything but the Kite client it is given.

Bid and ask are the first depth level, `oi` is the quote's open interest. IV and the Greeks are computed here, only when `R=` (and
`Q=`) are typed (Kite sends none and there is no free Indian rate source); without them those cells are empty and the table says `NEEDS R=`.
Time to expiry is the expiry date at 15:30 IST minus the clock (the pinned fixture clock in fixture mode).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..options import chain as ch
from ..options import tables as ot
from ..research.table import col, head, payload, section
from . import FIXTURE_LABEL
from .session import EXPIRED_MESSAGE, IST, KEY_REQUIRED_MESSAGE, LOGGED_OUT_MESSAGE
from .symbols import FUTURE_SPOT_EXCHANGES, derivative_root, spot_key

COMPUTED = "COMPUTED HERE (BLACK-SCHOLES), NOT VENDOR"
NEEDS_R = "NEEDS R=<PERCENT> (AND Q=<PERCENT>)"
CLOSE_IST = (15, 30)
NO_GREEKS = {"iv": None, "iv_src": None, "delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}
WHAT = {"omon": "INDIAN OPTION CHAINS WITH OPEN INTEREST", "ct": "INDIAN FUTURES WITH OPEN INTEREST"}


def _error(kind: str, message: str):
    from ..service import DataError

    return DataError(kind, message)


def expiry_epoch(day: str) -> float:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, *CLOSE_IST, tzinfo=IST).timestamp()


def years_to(day: str, now_epoch: float) -> float:
    return max(0.0, (expiry_epoch(day) - now_epoch) / ch.SECONDS_PER_YEAR)


def today_ist(now_epoch: float) -> str:
    return datetime.fromtimestamp(now_epoch, IST).strftime("%Y-%m-%d")


def source_label(fixtures: bool) -> str:
    return f"KITE ({FIXTURE_LABEL})" if fixtures else "KITE CONNECT (ZERODHA)"


def gate(session, symbol: str, fn: str, fixtures: bool) -> dict | None:
    """The payload that says why Kite cannot answer (no key, logged out, expired), or None when it can."""
    st = session.state
    if st == "OK":
        return None
    status = {"NO KEY": KEY_REQUIRED_MESSAGE, "LOGGED OUT": LOGGED_OUT_MESSAGE, "KITE LOGIN EXPIRED": EXPIRED_MESSAGE}[st]
    key_required = [{"key": "KITE_API_KEY", "what": WHAT[fn]}] if st == "NO KEY" else []
    return payload(symbol, f"{fn.upper()} {symbol}", [head("KITE", status)], [], [f"{WHAT[fn]} NEED A KITE CONNECT LOGIN: {status}"],
                   source_label(fixtures) if st != "NO KEY" else None, key_required, status=status)


def contract_of(inst: dict, quote: dict | None) -> dict:
    q = quote or {}
    depth = q.get("depth") or {}
    best = lambda side: ((depth.get(side) or [{}])[0] or {}).get("price")
    return {"strike": inst["strike"], "bid": best("buy"), "ask": best("sell"), "last": q.get("last_price"), "volume": q.get("volume"),
            "oi": q.get("oi"), "iv_vendor": None}


def plain_rows(contracts: list[dict], kind: str, spot: float | None, moneyness: str) -> list[dict]:
    """OI and quote columns with every Greek cell empty (no R typed, or no spot)."""
    out = []
    for c in sorted(contracts, key=lambda c: c["strike"]):
        if spot is not None and not ot.keep(kind, c["strike"], spot, moneyness):
            continue
        itm = spot is not None and (c["strike"] < spot if kind == "call" else c["strike"] > spot)
        out.append({k: c[k] for k in ("strike", "bid", "ask", "last", "volume", "oi")} | NO_GREEKS | {"itm": "ITM" if itm else ""})
    return out


async def spot_of(client, dump, exchange: str, name: str, expiry: str, quotes: dict[str, dict]) -> tuple[float | None, str | None]:
    """(spot, basis text). Index and stock options (NFO, BFO): the underlying's own quote. MCX and CDS: the nearest future at or after the option's expiry."""
    if exchange in FUTURE_SPOT_EXCHANGES:
        futs = sorted((r for r in dump.chain_rows(exchange, name, ("FUT",)) if (r["expiry"] or "") >= expiry), key=lambda r: r["expiry"] or "")
        if not futs:
            return None, None
        key = f"{exchange}:{futs[0]['tradingsymbol']}"
        q = quotes.get(key) or (await client.quote([key])).get(key)
        return ((q or {}).get("last_price"), f"UNDERLYING = {futs[0]['tradingsymbol']} FUTURE") if q else (None, None)
    key = spot_key(exchange, name)
    q = quotes.get(key) if key else None
    return ((q or {}).get("last_price"), f"UNDERLYING = {key}") if q else (None, None)


async def omon(session, client, instruments, symbol: str, now_epoch: float, fixtures: bool, day: str | None = None,
               moneyness: str = "ALL", r: float | None = None, q: float | None = None) -> dict:
    """`r` and `q` are continuous rates as decimals (`R=6.5` typed is 0.065)."""
    if (stop := gate(session, symbol, "omon", fixtures)) is not None:
        return stop
    exchange, name = derivative_root(symbol) or (None, None)
    if exchange is None:
        raise _error("bad_request", "OMON ON KITE NEEDS <UNDERLYING>.NFO, .BFO, .MCX OR .CDS")
    dump = await instruments.get()
    options = dump.chain_rows(exchange, name, ("CE", "PE"))
    if not options:
        raise _error("not_found", f"NO {name} OPTIONS ON {exchange} IN THE KITE INSTRUMENT DUMP")
    today = today_ist(now_epoch)
    expiries = sorted({o["expiry"] for o in options if o["expiry"] and o["expiry"] >= today})
    if not expiries:
        raise _error("not_found", f"NO LIVE {name} EXPIRIES IN THE KITE INSTRUMENT DUMP")
    if day:
        try:
            date.fromisoformat(day.strip())
        except ValueError as e:
            raise _error("bad_request", "DATE: YYYY-MM-DD") from e
        if day.strip() not in expiries:
            raise _error("bad_request", f"NOT AN EXPIRY. NEXT EXPIRIES: {' '.join(expiries[:6])}")
        expiry = day.strip()
    else:
        expiry = expiries[0]
    pick = [o for o in options if o["expiry"] == expiry]
    keys = [f"{exchange}:{o['tradingsymbol']}" for o in pick]
    spot_quote_key = spot_key(exchange, name)
    quotes = await client.quote(keys + ([spot_quote_key] if spot_quote_key else []))
    spot, spot_basis = await spot_of(client, dump, exchange, name, expiry, quotes)
    contracts = {"CE": [], "PE": []}
    for o in pick:
        contracts[o["instrument_type"]].append(contract_of(o, quotes.get(f"{exchange}:{o['tradingsymbol']}")))
    T = years_to(expiry, now_epoch)
    computed = r is not None and spot is not None
    if computed:
        q_used = q or 0.0
        calls = ot.side_rows(contracts["CE"], "call", spot, T, r, q_used, moneyness)
        puts = ot.side_rows(contracts["PE"], "put", spot, T, r, q_used, moneyness)
    else:
        calls, puts = plain_rows(contracts["CE"], "call", spot, moneyness), plain_rows(contracts["PE"], "put", spot, moneyness)
    lot = pick[0]["lot_size"]
    qtime = next((v.get("last_trade_time") or v.get("timestamp") for k, v in quotes.items() if k in keys), None)
    headline = [
        head("SPOT", f"{spot:,.2f}" if spot is not None else "NO QUOTE", spot), head("EXPIRY", expiry, expiry),
        head("T (YEARS)", f"{T:.4f}", T),
        head("RATE", f"{r * 100:.3f}% CONT. (TYPED)" if r is not None else NEEDS_R, r),
        head("DIV YIELD", f"{q * 100:.3f}% (TYPED)" if q is not None else ("0 USED (Q= NOT TYPED)" if r is not None else "-"), q or 0.0),
        head("GREEKS", COMPUTED if computed else NEEDS_R), head("LOT SIZE", str(lot), lot),
        head("EXPIRIES", str(len(expiries)), len(expiries)), head("QUOTE TIME", qtime or "-"),
    ]
    if fixtures:
        headline.append(head("DATA", f"KITE {FIXTURE_LABEL}"))
    notes = [f"KITE SENDS NO IV OR GREEKS: THEY ARE {COMPUTED}, ONLY WHEN R= (AND Q=) ARE TYPED, E.G. OMON {symbol} R=6.5 Q=1.2"
             if r is None else f"IV AND GREEKS ARE {COMPUTED}, FROM THE BID/ASK MID, R AND Q AS TYPED, EUROPEAN-STYLE EXERCISE",
             "BID AND ASK ARE THE BEST DEPTH LEVEL; OPEN INT IS KITE'S QUOTE OI; A CONTRACT KITE DID NOT QUOTE SHOWS DASHES",
             f"TIME TO EXPIRY = {expiry} 15:30 IST MINUS THE CLOCK, ACT/365" + ("; MCX / CDS EXPIRY TIME IS TAKEN AS 15:30 IST" if exchange in FUTURE_SPOT_EXCHANGES else "")]
    if spot_basis:
        notes.append(spot_basis)
    else:
        notes.append("NO UNDERLYING QUOTE FROM KITE: SPOT, MONEYNESS AND GREEKS ARE NOT AVAILABLE")
    if fixtures:
        notes.append(f"KITE {FIXTURE_LABEL}: INVENTED VALUES IN THE DOCUMENTED LAYOUT, NOT MARKET DATA")
    sections = [
        section("calls", "CALLS", ot.CHAIN_COLUMNS, calls), section("puts", "PUTS", ot.CHAIN_COLUMNS, puts),
        section("strads", "BY STRIKE", [
            col("strike", "STRIKE", "price"), col("c_mid", "CALL MID", "price"), col("c_iv", "CALL IV", "pct"),
            col("c_oi", "CALL OI", "int"), col("p_mid", "PUT MID", "price"), col("p_iv", "PUT IV", "pct"),
            col("p_oi", "PUT OI", "int")], ot.strads(calls, puts)),
    ]
    return payload(symbol, f"OMON {symbol} {expiry}", headline, sections, notes, source_label(fixtures), [], status="RUNNABLE")


async def futures(session, client, instruments, symbol: str, now_epoch: float, fixtures: bool) -> dict:
    """CT for `<UNDERLYING>.NFO` / `.MCX`: every listed future with its price and open interest."""
    if (stop := gate(session, symbol, "ct", fixtures)) is not None:
        return stop
    exchange, name = derivative_root(symbol) or (None, None)
    if exchange is None:
        raise _error("bad_request", "CT ON KITE NEEDS <UNDERLYING>.NFO, .BFO, .MCX OR .CDS")
    dump = await instruments.get()
    today = today_ist(now_epoch)
    futs = sorted((f for f in dump.chain_rows(exchange, name, ("FUT",)) if (f["expiry"] or "") >= today), key=lambda f: f["expiry"] or "")
    if not futs:
        raise _error("not_found", f"NO {name} FUTURES ON {exchange} IN THE KITE INSTRUMENT DUMP")
    keys = [f"{exchange}:{f['tradingsymbol']}" for f in futs]
    quotes = await client.quote(keys)
    rows: list[dict[str, Any]] = []
    front = None
    missing = []
    for f, k in zip(futs, keys, strict=True):
        qd = quotes.get(k) or {}
        price = qd.get("last_price")
        if price is None:
            missing.append(f["tradingsymbol"])
        front = price if front is None else front
        rows.append({"symbol": f"{f['tradingsymbol']}.{exchange}", "contract": f["tradingsymbol"], "expiry": f["expiry"], "price": price,
                     "change": qd.get("net_change"), "volume": qd.get("volume"), "oi": qd.get("oi"), "lot": f["lot_size"],
                     "spread": price - front if price is not None and front is not None else None})
    sec = section("contracts", f"{name} FUTURES", [
        col("symbol", "SYMBOL"), col("contract", "CONTRACT"), col("expiry", "EXPIRY", "date"), col("price", "PRICE", "price"),
        col("change", "CHG", "num"), col("volume", "VOLUME", "int"), col("oi", "OPEN INT", "int"), col("lot", "LOT", "int"),
        col("spread", "SPREAD TO FRONT", "num")], rows, "OPEN INT AND PRICES ARE KITE'S QUOTE; DASHES WHERE KITE SENT NO QUOTE")
    headline = [head("UNDERLYING", f"{name} ({exchange})"), head("CONTRACTS", str(len(rows)), len(rows)),
                head("FRONT", f"{rows[0]['price']:,.2f}" if rows[0]["price"] is not None else "NO QUOTE", rows[0]["price"])]
    if fixtures:
        headline.append(head("DATA", f"KITE {FIXTURE_LABEL}"))
    notes = ["CURRENT FUTURES FROM THE KITE INSTRUMENT DUMP; EXPIRED CONTRACTS ARE NOT LISTED"]
    if missing:
        notes.append("NO KITE QUOTE FOR: " + " ".join(missing))
    if fixtures:
        notes.append(f"KITE {FIXTURE_LABEL}: INVENTED VALUES IN THE DOCUMENTED LAYOUT, NOT MARKET DATA")
    return payload(symbol, f"CT {symbol}", headline, [sec], notes, source_label(fixtures), [], status="RUNNABLE")

