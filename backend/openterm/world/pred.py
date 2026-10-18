"""PRED: prediction-market rows from Polymarket and Kalshi (read only, keyless). Pure parsers first, then the service behind `/api/world/pred`.

Every payload carries LABEL: a market price is a traded probability, not a forecast. Shapes (checked against the recordings of 2026-10-18):
- Polymarket gamma `markets`: `outcomes` and `outcomePrices` are JSON-encoded STRINGS ('["Yes", "No"]', '["0.145", "0.855"]'); volume is USD; a
  RESOLVED market still says `active: true` but `closed: true`, so `closed` and `archived` are what filter.
- Kalshi `markets`: prices are dollar strings in `*_dollars` fields ("0.9100"); older answers had integer cents (`yes_bid: 91`); both are read.
  Volume (`volume_fp`) is in contracts, each paying US$1, so it is not USD and is shown with its unit.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any

import orjson

from ..service import DataError

LABEL = "MARKET-IMPLIED PROBABILITY, NOT A FORECAST"
TTL_S = 120.0
DETAIL_TTL_S = 120.0
MAX_ROWS = 400
MAX_Q = 80
ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,160}$")
SOURCE_NAMES = ("polymarket", "kalshi")
MAX_SPREAD = 0.5  # a Kalshi book wider than 50 cents says nothing about probability


class ShapeError(ValueError):
    """A source answered, but not in the shape this build knows."""


def num(x: Any) -> float | None:
    if x is None or x == "" or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def jlist(x: Any) -> list:
    """Polymarket sends lists as JSON text; accept the real list too."""
    if isinstance(x, str):
        try:
            x = orjson.loads(x)
        except orjson.JSONDecodeError:
            return []
    return x if isinstance(x, list) else []


def unit(p: float | None) -> float | None:
    """A probability must lie in 0..1; anything else is a parse problem, never a clamped guess."""
    return p if p is not None and 0.0 <= p <= 1.0 else None


def pct(p: float | None) -> float | None:
    return None if p is None else round(p * 100, 1)


def _day(s: Any) -> str | None:
    return s[:10] if isinstance(s, str) and len(s) >= 10 and s[4:5] == "-" else None


# --- Polymarket ---------------------------------------------------------------------------------------------------------
def poly_outcomes(m: dict) -> list[tuple[str, float | None]]:
    names = [str(n) for n in jlist(m.get("outcomes"))]
    prices = jlist(m.get("outcomePrices"))
    if not names or len(names) != len(prices):
        return []
    return [(n, unit(num(p))) for n, p in zip(names, prices, strict=True)]


def poly_lead(outs: list[tuple[str, float | None]]) -> int:
    """The outcome a row shows: "Yes" when the market has one, else the first listed."""
    return next((i for i, (n, _) in enumerate(outs) if n.strip().lower() == "yes"), 0)


def poly_open(m: Any) -> bool:
    return isinstance(m, dict) and not m.get("closed") and not m.get("archived") and m.get("active") is not False


def poly_row(m: Any) -> dict[str, Any] | None:
    if not poly_open(m):
        return None
    outs = poly_outcomes(m)
    if not outs:
        return None
    i = poly_lead(outs)
    name, prob = outs[i]
    if prob is None:
        return None
    ev = (m.get("events") or [{}])[0] if isinstance(m.get("events"), list) else {}
    return {
        "id": str(m.get("id") or ""), "source": "polymarket", "question": str(m.get("question") or "").strip(), "outcome": name,
        "prob": prob, "pct": pct(prob), "volume": num(m.get("volumeNum")) or num(m.get("volume")) or 0.0, "vol_unit": "USD",
        "close": _day(m.get("endDateIso")) or _day(m.get("endDate")), "history": bool(jlist(m.get("clobTokenIds"))),
        "ref": str(m.get("slug") or ""), "event": (ev or {}).get("title"),
    }


def parse_polymarket(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, list):
        raise ShapeError("Polymarket answered with something other than a list")
    return [r for r in (poly_row(m) for m in body) if r and r["id"] and r["question"]]


# --- Kalshi -------------------------------------------------------------------------------------------------------------
def kprice(m: dict, name: str) -> float | None:
    """`<name>_dollars` ("0.9100") when the answer has it, else the older integer cents `<name>` (91)."""
    v = num(m.get(name + "_dollars"))
    if v is not None:
        return v
    c = num(m.get(name))
    return None if c is None else c / 100


def kalshi_prob(m: dict) -> tuple[float | None, str | None]:
    """YES probability: the last traded price, else the bid/ask midpoint of a book that is not empty or absurdly wide."""
    last = kprice(m, "last_price")
    if last is not None and last > 0:
        return unit(last), "last"
    bid, ask = kprice(m, "yes_bid"), kprice(m, "yes_ask")
    if bid is not None and ask is not None and ask > 0 and 0 <= ask - bid <= MAX_SPREAD:
        return unit((bid + ask) / 2), "mid"
    return None, None


def kalshi_open(m: Any) -> bool:
    return isinstance(m, dict) and m.get("status", "active") in ("active", "open") and not m.get("result")


def kalshi_question(m: dict) -> str:
    title = str(m.get("title") or "").strip()
    sub = str(m.get("yes_sub_title") or "").strip()
    if sub and sub.lower() not in ("yes", "") and sub.lower() not in title.lower():
        return f"{title} ({sub})"
    return title


def kalshi_row(m: Any) -> dict[str, Any] | None:
    if not kalshi_open(m):
        return None
    prob, basis = kalshi_prob(m)
    if prob is None:
        return None
    vol = num(m.get("volume_fp"))
    if vol is None:
        vol = num(m.get("volume")) or 0.0
    return {
        "id": str(m.get("ticker") or ""), "source": "kalshi", "question": kalshi_question(m), "outcome": "Yes", "prob": prob, "pct": pct(prob),
        "volume": vol, "vol_unit": "contracts", "close": _day(m.get("close_time")), "history": True, "ref": str(m.get("event_ticker") or ""),
        "event": None, "basis": basis,
    }


def parse_kalshi(body: Any) -> list[dict[str, Any]]:
    ms = body.get("markets") if isinstance(body, dict) else None
    if not isinstance(ms, list):
        raise ShapeError("Kalshi answered without a markets list")
    return [r for r in (kalshi_row(m) for m in ms) if r and r["id"] and r["question"]]


# --- list ---------------------------------------------------------------------------------------------------------------
def combine(lists: list[list[dict[str, Any]]], q: str = "", limit: int = MAX_ROWS) -> list[dict[str, Any]]:
    """Both sources' rows, filtered by every word of `q` (case-insensitive, in the question), biggest volume first."""
    words = q.lower().split()
    rows = [r for rows in lists for r in rows if all(w in r["question"].lower() for w in words)]
    rows.sort(key=lambda r: (-r["volume"], r["source"], r["question"]))
    return rows[:limit]


# --- detail -------------------------------------------------------------------------------------------------------------
def parse_poly_history(body: Any) -> dict[str, list]:
    """CLOB `prices-history`: {"history": [{"t": epoch seconds, "p": price}]}; points out of 0..1 are dropped, order is ascending time."""
    pts = body.get("history") if isinstance(body, dict) else None
    if not isinstance(pts, list):
        raise ShapeError("Polymarket price history has no history list")
    out = sorted((int(t), p) for x in pts if isinstance(x, dict) and (t := num(x.get("t"))) is not None and (p := unit(num(x.get("p")))) is not None)
    return {"t": [t for t, _ in out], "p": [p for _, p in out]}


def parse_kalshi_candles(body: Any) -> dict[str, list]:
    """Kalshi candlesticks: the close of each period that traded (`price.close_dollars`, older `price.close` in cents); empty periods are gaps, not zeros."""
    cs = body.get("candlesticks") if isinstance(body, dict) else None
    if not isinstance(cs, list):
        raise ShapeError("Kalshi candlesticks answer has no candlesticks list")
    out = []
    for c in cs:
        if not isinstance(c, dict) or not isinstance(c.get("price"), dict):
            continue
        t, p = num(c.get("end_period_ts")), kprice(c["price"], "close")
        if t is not None and unit(p) is not None:
            out.append((int(t), p))
    out.sort()
    return {"t": [t for t, _ in out], "p": [p for _, p in out]}


def poly_detail(market: Any, hist: dict[str, list] | None, hist_note: str | None) -> dict[str, Any]:
    if not isinstance(market, dict):
        raise ShapeError("Polymarket market answer is not an object")
    outs = poly_outcomes(market)
    if not outs:
        raise ShapeError("Polymarket market has no outcome prices")
    lead = poly_lead(outs)
    return {
        "source": "polymarket", "id": str(market.get("id") or ""), "question": str(market.get("question") or ""), "label": LABEL,
        "open": poly_open(market), "volume": num(market.get("volumeNum")) or num(market.get("volume")) or 0.0, "vol_unit": "USD",
        "liquidity": num(market.get("liquidityNum")) or num(market.get("liquidity")), "close": _day(market.get("endDateIso")) or _day(market.get("endDate")),
        "outcomes": [{"name": n, "prob": p, "pct": pct(p), "bid": None, "ask": None} for n, p in outs], "lead": outs[lead][0],
        "history": hist, "history_outcome": outs[lead][0], "history_note": hist_note, "basis": "outcome price",
    }


def kalshi_detail(body: Any, hist: dict[str, list] | None, hist_note: str | None) -> dict[str, Any]:
    m = body.get("market") if isinstance(body, dict) else None
    if not isinstance(m, dict):
        raise ShapeError("Kalshi market answer has no market object")
    prob, basis = kalshi_prob(m)
    bid, ask = kprice(m, "yes_bid"), kprice(m, "yes_ask")
    nbid, nask = kprice(m, "no_bid"), kprice(m, "no_ask")
    no = None if prob is None else round(1 - prob, 4)
    return {
        "source": "kalshi", "id": str(m.get("ticker") or ""), "question": kalshi_question(m), "label": LABEL, "open": kalshi_open(m),
        "volume": num(m.get("volume_fp")) or 0.0, "vol_unit": "contracts", "liquidity": None, "open_interest": num(m.get("open_interest_fp")),
        "close": _day(m.get("close_time")), "series": str(m.get("event_ticker") or "").split("-")[0],
        "outcomes": [{"name": "Yes", "prob": prob, "pct": pct(prob), "bid": bid, "ask": ask}, {"name": "No", "prob": no, "pct": pct(no), "bid": nbid, "ask": nask}],
        "lead": "Yes", "history": hist, "history_outcome": "Yes", "history_note": hist_note,
        "basis": {"last": "last traded price", "mid": "bid/ask midpoint"}.get(basis or "", "no price"),
    }


# --- service ------------------------------------------------------------------------------------------------------------
def _reason(e: Exception) -> str:
    return (getattr(e, "detail", None) or str(e))[:160]


async def _source_rows(svc: Any, name: str) -> dict[str, Any]:
    cap, parse = ("pred_poly", parse_polymarket) if name == "polymarket" else ("pred_kalshi", parse_kalshi)

    async def fetch() -> dict:
        try:
            raw, failed = await svc.router.call(cap, lambda p: p.pred_markets())
            rows = parse(raw)
        except ValueError as e:  # the source answered, but not in the shape this build knows
            raise DataError("unavailable", f"{name.upper()} ANSWER NOT UNDERSTOOD", str(e)) from e
        return {"data": rows, "fallback_from": failed, "source": name}

    return await svc._swr(f"w:pred:{name}", TTL_S, fetch)


async def pred(svc: Any, q: str) -> dict[str, Any]:
    """Rows of both sources. One source failing still answers with the other and says which failed; both failing is an error, never an empty table."""
    q = " ".join(q.split())[:MAX_Q]
    got = await asyncio.gather(*(_source_rows(svc, n) for n in SOURCE_NAMES), return_exceptions=True)
    ok: list[tuple[str, dict]] = []
    failed: list[dict[str, str]] = []
    first: DataError | None = None
    for name, g in zip(SOURCE_NAMES, got, strict=True):
        if isinstance(g, DataError):
            failed.append({"source": name, "reason": _reason(g)})
            first = first or g
        elif isinstance(g, BaseException):
            raise g
        else:
            ok.append((name, g))
    if not ok:
        detail = "; ".join(f"{f['source']}: {f['reason']}" for f in failed)
        raise DataError(first.kind if first else "unavailable", "PROVIDER DOWN: POLYMARKET AND KALSHI BOTH FAILED", detail)
    notes = [f"{f['source'].upper()} FAILED ({f['reason']}): ROWS ARE {ok[0][0].upper()} ONLY" for f in failed]
    rows = combine([e["data"] for _, e in ok], q)
    counts = {n: len(e["data"]) for n, e in ok}
    return {
        "data": {"rows": rows, "label": LABEL, "q": q, "counts": counts, "failed": failed, "notes": notes,
                 "sources": [n for n, _ in ok], "unit_note": "VOLUME: POLYMARKET IN USD, KALSHI IN CONTRACTS OF US$1 (NOT THE SAME UNIT)"},
        "source": " + ".join(n for n, _ in ok), "as_of": min(e["as_of"] for _, e in ok), "age_s": max(e["age_s"] for _, e in ok),
        "stale": any(e["stale"] for _, e in ok), "fallback_from": [f["source"] for f in failed],
    }


async def pred_detail(svc: Any, source: str, ident: str) -> dict[str, Any]:
    if source not in SOURCE_NAMES:
        raise DataError("bad_request", f"SOURCE MUST BE ONE OF {' '.join(SOURCE_NAMES).upper()}")
    if not ID_RE.match(ident):
        raise DataError("bad_request", f"BAD MARKET ID: {ident[:24]}")

    async def fetch() -> dict:
        if source == "polymarket":
            market, failed = await svc.router.call("pred_poly_market", lambda p: p.pred_market(ident))
            hist: dict[str, list] | None = None
            note: str | None = None
            try:
                outs = poly_outcomes(market) if isinstance(market, dict) else []
                tokens = jlist(market.get("clobTokenIds")) if isinstance(market, dict) else []
                if not outs or not tokens or len(tokens) <= poly_lead(outs):
                    note = "NO PRICE HISTORY: POLYMARKET GIVES NONE FOR THIS MARKET"
                else:
                    raw, _ = await svc.router.call("pred_poly_history", lambda p: p.pred_history(str(tokens[poly_lead(outs)])))
                    hist = parse_poly_history(raw)
            except Exception as e:  # noqa: BLE001  the history is optional: the outcome table still answers
                note = f"PRICE HISTORY UNAVAILABLE ({_reason(e)})"
            try:
                data = poly_detail(market, hist, note)
            except ValueError as e:
                raise DataError("unavailable", "POLYMARKET ANSWER NOT UNDERSTOOD", str(e)) from e
        else:
            body, failed = await svc.router.call("pred_kalshi_market", lambda p: p.pred_market(ident))
            hist = None
            note = None
            try:
                series = str((body.get("market") or {}).get("event_ticker") or "").split("-")[0] if isinstance(body, dict) else ""
                raw, _ = await svc.router.call("pred_kalshi_candles", lambda p: p.pred_history(series, ident))
                hist = parse_kalshi_candles(raw)
                if not hist["t"]:
                    note = "NO TRADES IN THE LAST 7 DAYS: NOTHING TO CHART"
            except Exception as e:  # noqa: BLE001  optional, as above
                note = f"PRICE HISTORY UNAVAILABLE ({_reason(e)})"
            try:
                data = kalshi_detail(body, hist, note)
            except ValueError as e:
                raise DataError("unavailable", "KALSHI ANSWER NOT UNDERSTOOD", str(e)) from e
        return {"data": data, "fallback_from": failed, "source": source}

    env = await svc._swr(f"w:pred:d:{source}:{ident}", DETAIL_TTL_S, fetch)
    return env
