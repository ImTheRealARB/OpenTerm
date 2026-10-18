"""CDEP / FUND / LIQ / STBL / DEFI: pure parsers and maths for Binance, OKX and DefiLlama answers (no network, no pandas).

Order book prices and sizes arrive as strings. Funding is annualised from the interval the exchange reports (8h, 4h, 1h): rate x (24 / hours) x 365.
A perpetual has no expiry, so its premium (mark vs index) is NOT annualised; dated quarterly futures are (basis x 365 / days to expiry).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from typing import Any

from ..providers.base import ProviderError

QUOTES = ("USDT", "USDC", "USD", "EUR", "BTC", "ETH")
USD_QUOTES = {"USDT", "USDC", "USD"}
MAJORS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX", "BCH", "ATOM", "NEAR")
BANDS_PCT = (0.1, 0.5, 1.0)
LADDER_LEVELS = 25
MIN_TVL = 1_000_000
YIELD_ROWS = 100
_BASE = re.compile(r"^[A-Z0-9]{2,12}$")


def parse_pair(text: str) -> tuple[str, str]:
    """`BTCUSDT`, `BTC-USDT`, `btc/usdt`, `BTC` (= BTC/USDT) -> (base, quote). Raises ValueError with the usage text."""
    t = re.sub(r"[\s/_-]+", "", text.strip().upper())
    if not t:
        return "BTC", "USDT"
    for q in QUOTES:
        if t.endswith(q) and len(t) > len(q) and _BASE.match(t[: -len(q)]):
            return t[: -len(q)], q
    if _BASE.match(t) and len(t) <= 8:
        return t, "USDT"
    raise ValueError("PAIR: BTCUSDT, BTC-USDT OR JUST BTC (= BTC/USDT)")


def parse_base(text: str) -> str:
    """`FUND` / `LIQ` argument: a coin (BTC) or a perp name (BTCUSDT, BTC-USDT-SWAP). Empty = ''."""
    t = re.sub(r"[\s/_-]+", "", text.strip().upper())
    t = t.removesuffix("SWAP")
    for q in ("USDT", "USDC", "USD"):
        if t.endswith(q) and len(t) > len(q):
            t = t[: -len(q)]
            break
    if t and not _BASE.match(t):
        raise ValueError("SYMBOL: A COIN LIKE BTC, ETH OR SOL")
    return t


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# --- order book -----------------------------------------------------------------------------------
def _levels(raw: Any) -> list[tuple[float, float]]:
    out = []
    for lv in raw or []:
        px, qty = _f(lv[0]), _f(lv[1])
        if px is not None and qty is not None and px > 0 and qty > 0:
            out.append((px, qty))
    return out


def parse_binance_book(body: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]], int | None]:
    if not isinstance(body, dict) or "bids" not in body or "asks" not in body:
        raise ProviderError("unavailable", "BINANCE DEPTH ANSWER HAS NO BIDS / ASKS")
    return _levels(body["bids"]), _levels(body["asks"]), None


def parse_okx_book(body: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]], int | None]:
    data = body.get("data") if isinstance(body, dict) else None
    if not data or not isinstance(data[0], dict):
        raise ProviderError("not_found" if isinstance(body, dict) and body.get("code") not in (None, "0") else "unavailable", f"OKX BOOK: {(body or {}).get('msg') or 'NO DATA'}" if isinstance(body, dict) else "OKX BOOK: NO DATA")
    d = data[0]
    return _levels(d.get("bids")), _levels(d.get("asks")), int(d["ts"]) if str(d.get("ts", "")).isdigit() else None


def depth_summary(bids: list[tuple[float, float]], asks: list[tuple[float, float]], quote: str) -> dict[str, Any]:
    """Cumulative ladder (best price first), spread, mid, whole-book imbalance and notional within 0.1 / 0.5 / 1 % of mid."""
    if not bids or not asks:
        raise ProviderError("unavailable", "ORDER BOOK IS EMPTY ON ONE SIDE")
    bids = sorted(bids, key=lambda x: -x[0])
    asks = sorted(asks, key=lambda x: x[0])
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0

    def ladder(side: list[tuple[float, float]]) -> list[list[float]]:
        cq = cn = 0.0
        rows = []
        for px, qty in side:
            cq += qty
            cn += qty * px
            rows.append([px, qty, cq, cn])
        return rows

    lb, la = ladder(bids), ladder(asks)
    bq, aq = lb[-1][2], la[-1][2]
    bands = []
    for pct in BANDS_PCT:
        lo, hi = mid * (1 - pct / 100), mid * (1 + pct / 100)
        bn = sum(q * p for p, q in bids if p >= lo)
        an = sum(q * p for p, q in asks if p <= hi)
        bands.append({"pct": pct, "bid": bn, "ask": an, "imbalance_pct": None if bn + an == 0 else (bn - an) / (bn + an) * 100})
    return {"bids": lb, "asks": la, "best_bid": best_bid, "best_ask": best_ask, "mid": mid, "spread": best_ask - best_bid,
            "spread_pct": (best_ask - best_bid) / mid * 100, "imbalance_pct": (bq - aq) / (bq + aq) * 100, "bid_qty": bq, "ask_qty": aq,
            "levels": [len(bids), len(asks)], "bands": bands, "usd": quote in USD_QUOTES, "quote": quote}


# --- funding and basis ----------------------------------------------------------------------------------
def annualise(rate: float, interval_h: float) -> float:
    """Funding rate per interval (a fraction, 0.0001 = 0.01 %) -> simple annual percent."""
    return rate * (24.0 / interval_h) * 365.0 * 100.0


def basis_pct(mark: float, index: float) -> float | None:
    return None if not index else (mark - index) / index * 100.0


def quarterly_expiry(symbol: str) -> date | None:
    """`BTCUSDT_261225` -> 2026-12-25."""
    m = re.search(r"_(\d{2})(\d{2})(\d{2})$", symbol)
    if not m:
        return None
    try:
        return date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def annualised_basis(basis: float, today: date, expiry: date) -> float | None:
    days = (expiry - today).days
    return None if days <= 0 else basis * 365.0 / days


def binance_intervals(info: Any) -> dict[str, float]:
    return {x["symbol"]: float(x["fundingIntervalHours"]) for x in info or [] if isinstance(x, dict) and x.get("fundingIntervalHours")}


def binance_board(prem: Any, intervals: dict[str, float], today: date) -> list[dict[str, Any]]:
    """USD-M perpetuals of the majors, then dated quarterlies of the same coins (annualised basis)."""
    if not isinstance(prem, list):
        raise ProviderError("unavailable", "BINANCE PREMIUM INDEX IS NOT A LIST")
    by = {x["symbol"]: x for x in prem if isinstance(x, dict) and "symbol" in x}
    rows = []
    for base in MAJORS:
        x = by.get(f"{base}USDT")
        if x:
            rows.append(_perp_row(base, x, intervals.get(x["symbol"], 8.0), "binance"))
    for sym in sorted(by):
        exp = quarterly_expiry(sym)
        if exp and sym.split("_")[0].removesuffix("USDT") in MAJORS and exp > today:
            x = by[sym]
            mark, idx = _f(x.get("markPrice")), _f(x.get("indexPrice"))
            b = basis_pct(mark, idx) if mark and idx else None
            rows.append({"sym": sym, "base": sym.split("_")[0].removesuffix("USDT"), "kind": "QUARTERLY", "mark": mark, "index": idx, "basis_pct": b,
                         "rate_pct": None, "interval_h": None, "ann_pct": None, "next_ms": None, "expiry": exp.isoformat(), "days": (exp - today).days,
                         "ann_basis_pct": None if b is None else annualised_basis(b, today, exp), "source": "binance"})
    return rows


def _perp_row(base: str, x: dict[str, Any], hours: float, src: str) -> dict[str, Any]:
    mark, idx, rate = _f(x.get("markPrice")), _f(x.get("indexPrice")), _f(x.get("lastFundingRate"))
    return {"sym": x["symbol"], "base": base, "kind": "PERP", "mark": mark, "index": idx, "basis_pct": basis_pct(mark, idx) if mark and idx else None,
            "rate_pct": None if rate is None else rate * 100.0, "interval_h": hours, "ann_pct": None if rate is None else annualise(rate, hours),
            "next_ms": x.get("nextFundingTime"), "expiry": None, "days": None, "ann_basis_pct": None, "source": src}


def okx_board(funding: Any, marks: Any, index: Any) -> list[dict[str, Any]]:
    """OKX majors from `funding-rate?instId=ANY`, `mark-price?instType=SWAP` and `index-tickers?quoteCcy=USDT`."""
    for body in (funding, marks, index):
        if not isinstance(body, dict) or body.get("code") not in (None, "0"):
            raise ProviderError("unavailable", f"OKX: {(body or {}).get('msg') if isinstance(body, dict) else 'BAD ANSWER'}")
    mk = {x["instId"]: x for x in marks.get("data", [])}
    ix = {x["instId"]: x for x in index.get("data", [])}
    rows = []
    fr = {x["instId"]: x for x in funding.get("data", [])}
    for base in MAJORS:
        f = fr.get(f"{base}-USDT-SWAP")
        if not f:
            continue
        hours = _interval_okx(f)
        x = {"symbol": f"{base}-USDT-SWAP", "markPrice": (mk.get(f["instId"]) or {}).get("markPx"), "indexPrice": (ix.get(f"{base}-USDT") or {}).get("idxPx"),
             "lastFundingRate": f.get("fundingRate"), "nextFundingTime": _int(f.get("fundingTime"))}
        rows.append(_perp_row(base, x, hours, "okx"))
    return rows


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _interval_okx(f: dict[str, Any]) -> float:
    """OKX does not state the interval: it is the gap between this settlement and the previous one (default 8 h)."""
    a, b = _int(f.get("fundingTime")), _int(f.get("prevFundingTime")) or _int(f.get("nextFundingTime"))
    if a and b and abs(a - b) > 0:
        h = abs(a - b) / 3_600_000.0
        if 0.5 <= h <= 24:
            return round(h, 2)
    return 8.0


def funding_history(rows: list[tuple[int, float]], interval_h: float) -> dict[str, Any]:
    """(time_ms, rate) newest last -> prints with annualised percent and the mean of the prints."""
    prints = [{"t": t, "rate_pct": r * 100.0, "ann_pct": annualise(r, interval_h)} for t, r in rows]
    mean = sum(r for _, r in rows) / len(rows) if rows else None
    return {"prints": prints, "interval_h": interval_h, "mean_rate_pct": None if mean is None else mean * 100.0, "mean_ann_pct": None if mean is None else annualise(mean, interval_h)}


def parse_binance_history(body: Any) -> list[tuple[int, float]]:
    if not isinstance(body, list):
        raise ProviderError("unavailable", "BINANCE FUNDING HISTORY IS NOT A LIST")
    return sorted((int(x["fundingTime"]), float(x["fundingRate"])) for x in body if isinstance(x, dict) and _f(x.get("fundingRate")) is not None)


def parse_okx_history(body: Any) -> list[tuple[int, float]]:
    data = body.get("data") if isinstance(body, dict) else None
    if data is None:
        raise ProviderError("unavailable", "OKX FUNDING HISTORY HAS NO DATA")
    return sorted((int(x["fundingTime"]), float(x["fundingRate"])) for x in data if _f(x.get("fundingRate")) is not None and str(x.get("fundingTime", "")).isdigit())


# --- liquidations -------------------------------------------------------------------------------------------
def parse_okx_liquidations(body: Any, ct_val: float, linear: bool) -> list[dict[str, Any]]:
    """OKX `liquidation-orders` (state=filled). `sz` is contracts: base amount = sz x ctVal; USD = base x bankruptcy price (linear)."""
    data = body.get("data") if isinstance(body, dict) else None
    if data is None:
        raise ProviderError("unavailable", f"OKX LIQUIDATIONS: {(body or {}).get('msg') if isinstance(body, dict) else 'BAD ANSWER'}")
    out = []
    for grp in data:
        for d in grp.get("details", []):
            px, sz, ts = _f(d.get("bkPx")), _f(d.get("sz")), _int(d.get("ts") or d.get("time"))
            if px is None or sz is None or ts is None:
                continue
            base = sz * ct_val
            usd = base * px if linear else sz * ct_val
            out.append({"t": ts, "side": "LONG" if d.get("posSide") == "long" else "SHORT" if d.get("posSide") == "short" else ("LONG" if d.get("side") == "sell" else "SHORT"),
                        "px": px, "base": base if linear else usd / px, "usd": usd, "inst": grp.get("instId")})
    out.sort(key=lambda e: e["t"])
    return out


def aggregate_liquidations(events: list[dict[str, Any]], max_events: int = 40) -> dict[str, Any]:
    """Totals per liquidated side, the span the sample covers (OKX returns only the latest ~100), and the biggest and newest events."""
    longs = [e for e in events if e["side"] == "LONG"]
    shorts = [e for e in events if e["side"] == "SHORT"]
    span = (events[-1]["t"] - events[0]["t"]) / 1000.0 if len(events) > 1 else 0.0
    return {"events": len(events), "span_s": span, "since_ms": events[0]["t"] if events else None, "until_ms": events[-1]["t"] if events else None,
            "long": {"n": len(longs), "usd": sum(e["usd"] for e in longs)}, "short": {"n": len(shorts), "usd": sum(e["usd"] for e in shorts)},
            "largest": max(events, key=lambda e: e["usd"]) if events else None, "recent": list(reversed(events))[:max_events]}


# --- DefiLlama ---------------------------------------------------------------------------------------------------
def _usd(x: Any) -> float:
    return float(x.get("peggedUSD") or 0.0) if isinstance(x, dict) else 0.0


def parse_stablecoins(body: Any, chain: str = "", top: int = 30) -> dict[str, Any]:
    """Coins by circulating USD with 1d / 7d / 30d change, peg deviation and top chains; chain totals over ALL coins in the answer."""
    assets = body.get("peggedAssets") if isinstance(body, dict) else None
    if not isinstance(assets, list) or not assets:
        raise ProviderError("unavailable", "DEFILLAMA STABLECOINS: NO ASSETS")
    chain_tot: dict[str, float] = {}
    coins = []
    want = chain.strip().lower()
    for a in assets:
        circ = _usd(a.get("circulating"))
        per_chain = {c: _usd((v or {}).get("current")) for c, v in (a.get("chainCirculating") or {}).items()}
        for c, usd in per_chain.items():
            chain_tot[c] = chain_tot.get(c, 0.0) + usd
        in_chain = next((usd for c, usd in per_chain.items() if c.lower() == want), None) if want else circ
        if want and in_chain is None:
            continue
        price = _f(a.get("price"))
        peg = a.get("pegType") or ""
        prev = {"1d": _usd(a.get("circulatingPrevDay")), "7d": _usd(a.get("circulatingPrevWeek")), "30d": _usd(a.get("circulatingPrevMonth"))}
        chg = {k: (None if not v else (circ - v) / v * 100.0) for k, v in prev.items()}
        coins.append({"name": a.get("name"), "symbol": a.get("symbol"), "peg": peg, "mechanism": a.get("pegMechanism"), "circulating": circ,
                      "value": in_chain, "chg_1d": chg["1d"], "chg_7d": chg["7d"], "chg_30d": chg["30d"], "price": price,
                      "peg_dev_pct": (price - 1.0) * 100.0 if price is not None and peg == "peggedUSD" else None,
                      "chains": [c for c, _ in sorted(per_chain.items(), key=lambda kv: -kv[1])[:4]]})
    if want and not coins:
        raise ProviderError("not_found", f"NO STABLECOIN SUPPLY ON CHAIN {chain.upper()[:24]}")
    coins.sort(key=lambda c: -(c["value"] or 0))
    total = sum(chain_tot.values()) if not want else chain_tot.get(next((c for c in chain_tot if c.lower() == want), ""), 0.0)
    chains = [{"chain": c, "usd": v, "share_pct": None} for c, v in sorted(chain_tot.items(), key=lambda kv: -kv[1]) if v > 0][:25]
    all_total = sum(chain_tot.values())
    for c in chains:
        c["share_pct"] = c["usd"] / all_total * 100.0 if all_total else None
    return {"coins": coins[:top], "chains": chains, "total_usd": total, "n_coins": len(coins), "chain": chain or None}


def filter_pools(body: Any, min_tvl: float = MIN_TVL) -> list[dict[str, Any]]:
    """DefiLlama yields: keep pools with TVL above `min_tvl` and only the fields the panel shows (the raw list is ~11 MB / 20 000 pools)."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ProviderError("unavailable", "DEFILLAMA YIELDS: NO POOL LIST")
    out = []
    for p in data:
        tvl = p.get("tvlUsd")
        if not isinstance(tvl, (int, float)) or tvl <= min_tvl or p.get("apy") is None:
            continue
        out.append({"chain": p.get("chain"), "project": p.get("project"), "symbol": p.get("symbol"), "tvl": tvl, "apy": p.get("apy"), "apy_base": p.get("apyBase"),
                    "apy_reward": p.get("apyReward"), "stable": bool(p.get("stablecoin")), "il": p.get("ilRisk"), "apy_30d": p.get("apyMean30d"), "pool": p.get("pool")})
    return out


def select_pools(pools: list[dict[str, Any]], q: str, rows: int = YIELD_ROWS) -> dict[str, Any]:
    """`DEFI [chain|project]`: exact chain name first, else a project-name match; highest APY first."""
    key = q.strip().lower()
    pick = pools
    mode = "ALL"
    if key:
        by_chain = [p for p in pools if (p["chain"] or "").lower() == key]
        if by_chain:
            pick, mode = by_chain, "CHAIN"
        else:
            pick = [p for p in pools if key in (p["project"] or "").lower()]
            mode = "PROJECT"
        if not pick:
            raise ProviderError("not_found", f"NO POOL FOR CHAIN OR PROJECT {q.upper()[:30]}")
    pick = sorted(pick, key=lambda p: -p["apy"])
    return {"rows": pick[:rows], "matched": len(pick), "mode": mode, "query": q.strip() or None, "pools_over_tvl": len(pools), "min_tvl": MIN_TVL}


def ms_iso(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")
