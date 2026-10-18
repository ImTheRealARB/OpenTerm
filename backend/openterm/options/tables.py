"""Table payloads for OMON and PCR (spec decisions E, F). Pure: the service passes in the chain, the clock-derived T and the market
inputs; nothing here touches I/O. Numbers are never invented: a contract with no usable IV prints dashes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..research.table import col, head, payload, section
from . import chain as ch

GREEKS_COMPUTED = "COMPUTED HERE (BLACK-SCHOLES, EUROPEAN), NOT VENDOR"
GREEKS_VENDOR = "VENDOR (TRADIER), AS SENT"
MONEYNESS = ("ALL", "ITM", "OTM")


def day(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d") if epoch else None


def keep(kind: str, strike: float, spot: float, moneyness: str) -> bool:
    if moneyness == "ALL":
        return True
    in_money = strike < spot if kind == "call" else strike > spot
    return in_money if moneyness == "ITM" else not in_money


def side_rows(contracts: list[dict], kind: str, S: float, T: float, r: float, q: float, moneyness: str) -> list[dict]:
    out = []
    for c in sorted(contracts, key=lambda c: c["strike"]):
        if not keep(kind, c["strike"], S, moneyness):
            continue
        g = ch.greeks_row(c, kind, S, T, r, q)
        out.append({
            "strike": c["strike"], "bid": c["bid"], "ask": c["ask"], "last": c["last"], "volume": c["volume"], "oi": c["oi"],
            **g, "itm": "ITM" if (c["strike"] < S if kind == "call" else c["strike"] > S) else "",
        })
    return out


CHAIN_COLUMNS = [
    col("strike", "STRIKE", "price"), col("bid", "BID", "price"), col("ask", "ASK", "price"), col("last", "LAST", "price"),
    col("volume", "VOLUME", "int"), col("oi", "OPEN INT", "int"), col("iv", "IV", "pct"), col("iv_src", "IV SRC"),
    col("delta", "DELTA", "num4"), col("gamma", "GAMMA", "num4"), col("theta", "THETA", "num4"), col("vega", "VEGA", "num4"),
    col("rho", "RHO", "num4"), col("itm", "ITM"),
]


def mid(c: dict) -> float | None:
    return ch.mid_price(c)


def strads(calls: list[dict], puts: list[dict]) -> list[dict]:
    by: dict[float, dict] = {}
    for side, rows in (("c", calls), ("p", puts)):
        for r in rows:
            e = by.setdefault(r["strike"], {"strike": r["strike"]})
            e[f"{side}_mid"] = mid(r)
            e[f"{side}_iv"] = r["iv"]
            e[f"{side}_oi"] = r["oi"]
    return [by[k] for k in sorted(by)]


def omon_payload(chain: dict, T: float, r: float, y_par: float | None, curve_date: str | None, q: float | None, q_note: str | None,
                 moneyness: str, key_required: list[dict]) -> dict:
    S = chain["spot"]
    q_used = 0.0 if q is None else q
    calls = side_rows(chain["calls"], "call", S, T, r, q_used, moneyness)
    puts = side_rows(chain["puts"], "put", S, T, r, q_used, moneyness)
    vendor = chain.get("vendor_greeks")
    rate_txt = f"{r * 100:.3f}% CONT." + (f" (UST PAR {y_par:.2f}%, {curve_date})" if y_par is not None else "")
    headline = [
        head("SPOT", f"{S:,.2f}", S), head("EXPIRY", day(chain["expiry"]), chain["expiry"]), head("T (YEARS)", f"{T:.4f}", T),
        head("RATE", rate_txt, r),
        head("DIV YIELD", f"{q * 100:.3f}%" if q is not None else "NOT FOUND, 0 USED", q_used),
        head("GREEKS", GREEKS_VENDOR if vendor else GREEKS_COMPUTED),
        head("EXPIRIES", str(len(chain["expirations"])), len(chain["expirations"])),
    ]
    notes = ["THETA PER CALENDAR DAY; VEGA AND RHO PER 1 VOL POINT AND PER 1 RATE POINT",
             "AMERICAN EARLY EXERCISE IS IGNORED: THE GREEKS ARE EUROPEAN BLACK-SCHOLES APPROXIMATIONS",
             "IV SRC: MID = SOLVED FROM THE BID/ASK MID, YAHOO = THE VENDOR'S OWN IV (NO TWO-SIDED MARKET), DASH = NEITHER USABLE"]
    if q_note:
        notes.append(q_note)
    sections = [
        section("calls", "CALLS", CHAIN_COLUMNS, calls), section("puts", "PUTS", CHAIN_COLUMNS, puts),
        section("strads", "BY STRIKE", [
            col("strike", "STRIKE", "price"), col("c_mid", "CALL MID", "price"), col("c_iv", "CALL IV", "pct"),
            col("c_oi", "CALL OI", "int"), col("p_mid", "PUT MID", "price"), col("p_iv", "PUT IV", "pct"),
            col("p_oi", "PUT OI", "int")], strads(calls, puts)),
    ]
    return payload(chain["symbol"], f"OMON {chain['symbol']} {day(chain['expiry'])}", headline, sections, notes, chain["source"],
                   key_required)


def pcr_payload(symbol: str, chains: list[dict], planned: int, source: str, key_required: list[dict]) -> dict:
    rows = []
    for c in chains:
        cv = sum(x["volume"] or 0 for x in c["calls"])
        pv = sum(x["volume"] or 0 for x in c["puts"])
        co = sum(x["oi"] or 0 for x in c["calls"])
        po = sum(x["oi"] or 0 for x in c["puts"])
        rows.append({"expiry": day(c["expiry"]), "call_vol": cv, "put_vol": pv, "pcr_vol": pv / cv if cv else None,
                     "call_oi": co, "put_oi": po, "pcr_oi": po / co if co else None})
    tcv, tpv = sum(r["call_vol"] for r in rows), sum(r["put_vol"] for r in rows)
    tco, tpo = sum(r["call_oi"] for r in rows), sum(r["put_oi"] for r in rows)
    pv_ratio = tpv / tcv if tcv else None
    po_ratio = tpo / tco if tco else None
    fmt = lambda v: f"{v:.3f}" if v is not None else "-"
    headline: list[dict[str, Any]] = [
        head("PCR VOL", fmt(pv_ratio), pv_ratio), head("PCR OI", fmt(po_ratio), po_ratio),
        head("EXPIRIES", f"{len(chains)} OF {planned}", len(chains)),
    ]
    sec = section("expiry", "BY EXPIRY", [
        col("expiry", "EXPIRY", "date"), col("call_vol", "CALL VOL", "int"), col("put_vol", "PUT VOL", "int"),
        col("pcr_vol", "PCR VOL", "num"), col("call_oi", "CALL OI", "int"), col("put_oi", "PUT OI", "int"),
        col("pcr_oi", "PCR OI", "num")], rows)
    notes = ["PUT/CALL RATIO = PUT / CALL; VOLUME IS TODAY'S SESSION, OPEN INTEREST IS THE PRIOR CLOSE",
             "THE EIGHT EXPIRIES ARE THE NEAREST PLUS THE ONES CLOSEST TO +7, +30, +60, +90, +180, +270 AND +365 DAYS AFTER IT"]
    return payload(symbol, f"PCR {symbol}", headline, [sec], notes, source, key_required)
