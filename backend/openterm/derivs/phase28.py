"""Phase 28 functions on the derivatives service (a mixin of Derivs, like calc_service / fut_service):

  CONE  `GET /api/deriv/cone?symbol=`   ATM IV per listed expiry -> 1 and 2 SD price ranges (GP draws them: `GP AAPL CONE`)
  EMOV  `<SYM> EMOV`                     implied move of the nearest expiry vs the stock's moves on its last 12 earnings reports
  OIB   `<F&O SYM> OIB [1M] [1D]`        India F&O open-interest buildup per bar (Kite bars carry OI)
  PGRK  `PGRK <PORTFOLIO> [VS SPY]`      Greeks of the option positions in a portfolio, beta-weighted delta to an index

The maths is in options/analytics.py (pure, tested). Every model number is labelled as one on screen.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from ..errors import DataError
from ..options import analytics as an
from ..options import chain as ch
from ..options import tables as ot
from ..research.table import col, head, payload, section
from ..router import AllFailed
from ..service import envelope
from ..symbols import resolve

if TYPE_CHECKING:
    from ..service import DataService

EARNINGS_ITEM = "2.02"   # 8-K item "Results of Operations and Financial Condition" = the earnings release
REPORTS = 12


def _env(data: dict) -> dict:
    return envelope({"data": data, "source": data["source"]}, time.time(), stale=False)


def _beta(t_a: list[float], c_a: list[float], t_b: list[float], c_b: list[float]) -> float | None:
    """Beta of A to B from daily log returns on their common days (at least 60). Pure."""
    pa, pb = dict(zip(t_a, c_a, strict=False)), dict(zip(t_b, c_b, strict=False))
    days = sorted(set(pa) & set(pb))
    ra, rb = [], []
    for d0, d1 in pairwise(days):
        if pa[d0] > 0 and pa[d1] > 0 and pb[d0] > 0 and pb[d1] > 0:
            ra.append(math.log(pa[d1] / pa[d0]))
            rb.append(math.log(pb[d1] / pb[d0]))
    if len(ra) < 60:
        return None
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    var = sum((x - mb) ** 2 for x in rb)
    return None if var == 0 else sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True)) / var


class Phase28Mixin:
    svc: DataService
    db: Any

    # shared helpers live on Derivs (service.py): chain, chains, spot, rate_and_yield, now
    async def _expiry_atm(self, sym: str) -> tuple[float, list[tuple[float, float, float]], str]:
        """(spot, [(expiry epoch, T, ATM IV)], source) over the expiries Derivs.chains picks."""
        base, chains, _planned = await self.chains(sym)  # type: ignore[attr-defined]
        S = base["spot"]
        pts = []
        for c in chains:
            T = ch.years_to_expiry(c["expiry"], self.now())  # type: ignore[attr-defined]
            if T <= 0:
                continue
            r, _p, _d, q, _n = await self.rate_and_yield(sym, T, None)  # type: ignore[attr-defined]
            calls = ot.side_rows(c["calls"], "call", S, T, r, q or 0.0, "ALL")
            puts = ot.side_rows(c["puts"], "put", S, T, r, q or 0.0, "ALL")
            iv = ch.atm_iv(calls, puts, S)
            if iv:
                pts.append((float(c["expiry"]), T, iv))
        return S, pts, base["source"]

    # --- CONE -----------------------------------------------------------------------------------
    async def fn_cone(self, symbol: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "CONE NEEDS A SYMBOL")
        sym = resolve(symbol)
        try:
            S, pts, source = await self._expiry_atm(sym)
        except AllFailed as e:
            raise DataError("unavailable", f"NO OPTION CHAIN FOR {sym}") from e
        rows = an.cone(S, pts)
        if not rows:
            raise DataError("not_found", f"NO ATM IV FOR {sym}: THE CHAIN HAS NO TWO-SIDED QUOTES NEAR THE MONEY")
        return _env({"symbol": sym, "spot": S, "points": rows, "source": source,
                     "label": "MODEL RANGE, LOGNORMAL FROM EACH EXPIRY'S ATM IV (1 AND 2 SD), NOT A FORECAST"})

    # --- EMOV -----------------------------------------------------------------------------------
    async def fn_emov(self, symbol: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "EMOV NEEDS A SYMBOL")
        sym = resolve(symbol)
        try:
            fil = await self.svc.filings(sym)
        except (DataError, AllFailed) as e:
            raise DataError("unavailable", f"NO SEC FILINGS FOR {sym} (US FILERS ONLY)") from e
        rows = (fil.get("data") or {}).get("filings") or []
        dates = sorted({f["filed"] for f in rows if f.get("form") == "8-K" and EARNINGS_ITEM in (f.get("items") or "").split(",")},
                       reverse=True)[:REPORTS]
        bars = (await self.svc.history(sym, "5Y", "1d"))["data"]
        moves = an.report_moves(sorted(dates), bars["t"], bars["c"])
        avg = sum(abs(m["move"]) for m in moves) / len(moves) if moves else None
        implied = None
        exp_txt = "-"
        try:
            c = (await self.chain(sym))["data"]  # type: ignore[attr-defined]
            T = ch.years_to_expiry(c["expiry"], self.now())  # type: ignore[attr-defined]
            r, _p, _d, q, _n = await self.rate_and_yield(sym, T, None)  # type: ignore[attr-defined]
            calls = ot.side_rows(c["calls"], "call", c["spot"], T, r, q or 0.0, "ALL")
            puts = ot.side_rows(c["puts"], "put", c["spot"], T, r, q or 0.0, "ALL")
            implied = an.expected_move(c["spot"], T, calls, puts, ch.atm_iv(calls, puts, c["spot"]))
            exp_txt = ot.day(c["expiry"]) or "-"
        except (DataError, AllFailed):
            pass  # shown as "-" with the note below; the report history still stands on its own
        imp = implied["straddle_pct"] if implied else None
        headline = [
            head("IMPLIED MOVE", "-" if imp is None else f"±{imp * 100:.1f}%", imp),
            head("TO EXPIRY", exp_txt),
            head("AVG ACTUAL MOVE", "-" if avg is None else f"±{avg * 100:.1f}%", avg),
            head("REPORTS", str(len(moves)), len(moves)),
        ]
        table = [{"date": m["date"], "before": m["before"], "after": m["after"], "move": m["move"],
                  "abs": abs(m["move"]), "vs": None if imp is None else ("BIGGER" if abs(m["move"]) > imp else "SMALLER")}
                 for m in reversed(moves)]
        notes = ["IMPLIED MOVE = ATM STRADDLE OF THE NEAREST LISTED EXPIRY / SPOT (IT INCLUDES ANY EARNINGS INSIDE THAT EXPIRY)",
                 ("REPORT DATES = FILING DATES OF 8-K ITEM 2.02 (EARNINGS RELEASE); MOVE = CLOSE BEFORE THE FILING DAY TO THE CLOSE "
                  "OF THE SESSION AFTER IT, SO BEFORE-OPEN AND AFTER-CLOSE REPORTS ARE BOTH COVERED"),
                 "HISTORICAL MOVES, NOT A FORECAST"]
        if implied is None:
            notes.append("NO OPTION CHAIN ANSWERED: IMPLIED MOVE NOT SHOWN")
        data = payload(sym, f"EMOV {sym}", headline, [section("moves", "EARNINGS REPORTS", [
            col("date", "FILED", "date"), col("before", "CLOSE BEFORE", "price"), col("after", "CLOSE AFTER", "price"),
            col("move", "MOVE", "pct"), col("abs", "ABS MOVE", "pct"), col("vs", "VS IMPLIED")], table)], notes,
            "sec (8-K item 2.02) + history + options")
        return _env(data)

    # --- OIB ------------------------------------------------------------------------------------
    async def fn_oib(self, symbol: str | None = None, range: str | None = None, interval: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "OIB NEEDS AN F&O SYMBOL, E.G. NIFTY26NOVFUT.NFO")
        sym = resolve(symbol)
        bars = (await self.svc.history(sym, (range or "1M").upper(), (interval or "1d").lower()))["data"]
        oi = bars.get("oi")
        if not oi:
            raise DataError("not_found", f"{sym}: THESE BARS CARRY NO OPEN INTEREST (KITE F&O CONTRACTS ONLY: .NFO .BFO .MCX .CDS)")
        rows = an.oi_rows(bars["t"], bars["c"], oi)
        for r in rows:
            r["date"] = datetime.fromtimestamp(r["time"], UTC).strftime("%Y-%m-%d %H:%M")
        count = {k: sum(1 for r in rows if r["reading"] == k) for k in ("LONG BUILDUP", "SHORT BUILDUP", "SHORT COVERING", "LONG UNWINDING")}
        last = rows[-1] if rows else None
        headline = [head("LAST READING", (last or {}).get("reading") or "-"),
                    head("OI", "-" if not last or last["oi"] is None else f"{last['oi']:,.0f}", (last or {}).get("oi")),
                    *(head(k, str(v), v) for k, v in count.items())]
        data = payload(sym, f"OIB {sym}", headline, [section("bars", "OPEN INTEREST BY BAR", [
            col("date", "TIME"), col("close", "CLOSE", "price"), col("chg", "CHG", "num"), col("oi", "OI", "int"),
            col("oi_chg", "OI CHG", "int"), col("reading", "READING")], list(reversed(rows)))],
            [("READING: PRICE UP + OI UP = LONG BUILDUP; PRICE DOWN + OI UP = SHORT BUILDUP; PRICE UP + OI DOWN = SHORT COVERING; "
              "PRICE DOWN + OI DOWN = LONG UNWINDING (THE USUAL F&O CONVENTION, AN INTERPRETATION, NOT A FACT ABOUT WHO TRADED)")],
            bars.get("source"))
        return _env(data)

    # --- PGRK -----------------------------------------------------------------------------------
    async def fn_pgrk(self, symbol: str | None = None, name: str | None = None, vs: str | None = None, **_: Any) -> dict:
        from ..portfolio import Portfolios, UserDataError
        from ..quant import options as qo

        pname = name or symbol
        if not pname or self.db is None:
            raise DataError("bad_request", "USAGE: PGRK <PORTFOLIO> [VS=SPY]")
        try:
            pf = await Portfolios(self.db).get(pname)
        except UserDataError as e:
            raise DataError("not_found", str(e)) from e
        index = resolve(vs or "SPY")
        opts, skipped = [], []
        for p in pf["positions"]:
            o = an.parse_occ(p["symbol"])
            (opts if o else skipped).append((p, o))
        if not opts:
            raise DataError("not_found", f"PORTFOLIO {pf['name']} HAS NO OCC OPTION SYMBOLS (E.G. AAPL260116C00200000)")
        roots = sorted({o["root"] for _, o in opts})
        idx_bars = (await self.svc.history(index, "1Y", "1d"))["data"]
        idx_level = idx_bars["c"][-1]

        async def root_info(root: str):
            S, _ = await self.spot(root)  # type: ignore[attr-defined]
            b = (await self.svc.history(root, "1Y", "1d"))["data"]
            return root, S, _beta(b["t"], b["c"], idx_bars["t"], idx_bars["c"])

        info = {r: (S, beta) for r, S, beta in await asyncio.gather(*(root_info(r) for r in roots))}
        rows, tot = [], dict.fromkeys(("delta", "gamma", "theta", "vega", "bwd"), 0.0)
        now = self.now()  # type: ignore[attr-defined]
        for p, o in opts:
            S, beta = info[o["root"]]
            exp = datetime.strptime(o["expiry"], "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
            T = ch.years_to_expiry(int(exp), now)
            r, _p, _d, q, _n = await self.rate_and_yield(o["root"], max(T, 1 / 365), None)  # type: ignore[attr-defined]
            kind = "call" if o["type"] == "C" else "put"
            iv = None
            try:
                found = await self.atm_iv(o["root"], exp, None)  # type: ignore[attr-defined]
                iv = found[0] if found else None
            except (DataError, AllFailed):
                iv = None
            row = {"symbol": p["symbol"], "qty": p["qty"], "under": o["root"], "strike": o["strike"], "type": o["type"],
                   "expiry": o["expiry"], "iv": iv, "beta": beta}
            if iv and T > 0:
                g = qo.bs_greeks(S, o["strike"], T, r, iv, kind, q or 0.0)
                m = p["qty"] * 100  # US equity contract size
                row |= {k: g[k] * m for k in ("delta", "gamma", "theta", "vega")}
                row["bwd"] = an.beta_weighted_delta(row["delta"], S, beta, idx_level)
                for k in ("delta", "gamma", "theta", "vega"):
                    tot[k] += row[k]
                tot["bwd"] += row["bwd"] or 0.0
            rows.append(row)
        headline = [head("NET DELTA (SHARES)", f"{tot['delta']:,.1f}", tot["delta"]),
                    head(f"BETA-WEIGHTED DELTA ({index} SHARES)", f"{tot['bwd']:,.1f}", tot["bwd"]),
                    head("NET GAMMA", f"{tot['gamma']:,.2f}", tot["gamma"]), head("NET THETA / DAY", f"{tot['theta']:,.2f}", tot["theta"]),
                    head("NET VEGA / VOL PT", f"{tot['vega']:,.2f}", tot["vega"])]
        notes = ["GREEKS: BLACK-SCHOLES, EUROPEAN, AT EACH UNDERLYING'S ATM IV FOR THAT EXPIRY (A SMILE IS IGNORED); x QTY x 100",
                 f"BETA = 1 YEAR OF DAILY LOG RETURNS VS {index}; BETA-WEIGHTED DELTA = DELTA x SPOT x BETA / {index} LEVEL",
                 "STOCK POSITIONS ARE LEFT OUT" + (f" ({len(skipped)} NOT AN OCC OPTION SYMBOL)" if skipped else "")]
        data = payload(pf["name"], f"PGRK {pf['name']}", headline, [section("legs", "OPTION POSITIONS", [
            col("symbol", "CONTRACT"), col("qty", "QTY", "num"), col("under", "UNDER"), col("strike", "STRIKE", "price"),
            col("type", "C/P"), col("expiry", "EXPIRY"), col("iv", "ATM IV", "pct"), col("delta", "DELTA", "num"),
            col("gamma", "GAMMA", "num4"), col("theta", "THETA", "num"), col("vega", "VEGA", "num"), col("beta", "BETA", "num"),
            col("bwd", f"BW DELTA ({index})", "num")], rows)], notes, "portfolio + quotes + options + history")
        return _env(data)
