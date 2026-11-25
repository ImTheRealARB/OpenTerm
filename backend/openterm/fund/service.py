"""Phase 29 fundamentals service: `GET /api/fund/{fn}` -> the research table payload (research/table.py).

  GF     `<SYM> GF [METRIC] [Q] [VS=MSFT,GOOGL]`  a metric over time from SEC filings (+ daily price for multiples)
  EM     `<SYM> EM`                              earnings matrix: quarters x fiscal years, SEC EPS/revenue + surprises
  DDIS   `<SYM> DDIS`                            debt maturity ladder from the latest 10-K that tags it
  SCORE  `<SYM> SCORE`                           Altman Z / Z'', Piotroski F, Beneish M, Ohlson O, Merton DD
  FRM    `FRM <TAG> [CY2024] [ASOF=date]`        one XBRL concept for every filer (frames API), point in time
  EQSBT  `EQS BT <RULES> UNIV=LIST:A,B [FROM=2021] [VS=SPY]`  monthly screen backtest on frames data
  IBQ    `IBQ [YEAR] [INDUSTRY]`                 sector / industry roll-ups (medians, dispersion)
  REVS   `<SYM> REVS`                            estimate revision score (inputs shown)

All maths is in fund/{metrics,scores,frames,estimates}.py (pure, unit-tested). This file only fetches and lays out tables.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, date, datetime
from itertools import pairwise
from statistics import median
from typing import TYPE_CHECKING, Any

from ..barfetch import fetch_bars
from ..errors import DataError
from ..options import market as mk
from ..providers.base import ProviderError
from ..research.table import col, head, payload, section
from ..service import envelope
from ..symbols import resolve
from . import estimates as es
from . import frames as fr
from . import metrics as mt
from . import scores as sc

if TYPE_CHECKING:
    from ..service import DataService

SCORE_LABEL = "FORMULA SCORE, NOT A RATING"
SURVIVORSHIP = "SURVIVORSHIP BIAS: DELISTED COMPANIES MISSING (NO FREE DELISTED PRICES)"
BT_LABEL = "HISTORICAL SIMULATION, NOT A FORECAST"
MAX_PEERS = 4
MAX_UNIVERSE = 60
FRAME_TTL = 86400.0  # a calendar year's frame changes only when late filers file
EQSFUND_FIELDS = ("MARGIN", "OPMARGIN", "ROE", "GROWTH", "DE")  # order = the columns of the `rows` lists
EQSFUND_MIN_FILERS = 3000  # a calendar year with fewer revenue filers than this is "not filed yet" (about 5,000 file a year)


def _env(data: dict) -> dict:
    return envelope({"data": data, "source": data.get("source")}, time.time(), stale=False)


def _year_x(day: str | float) -> float:
    """Date -> fractional year (2024.5) for the numeric chart axis."""
    d = datetime.fromtimestamp(day, UTC).date() if isinstance(day, (int, float)) else date.fromisoformat(day)
    return round(d.year + (d.timetuple().tm_yday - 1) / 365.25, 4)


def _pct(v: float | None) -> str | None:
    return f"{v * 100:.1f}%" if v is not None else None


def _num(v: float | None, d: int = 2) -> str | None:
    return f"{v:,.{d}f}" if v is not None else None


class Fund:
    def __init__(self, svc: DataService):
        self.svc = svc

    async def run(self, fn: str, **params: Any) -> dict:
        method = getattr(self, f"fn_{fn.lower()}", None)
        if method is None:
            raise DataError("not_found", f"NO FUNDAMENTALS FUNCTION {fn.upper()}")
        return await method(**params)

    # --- shared fetches --------------------------------------------------------------------------
    @property
    def sec(self):
        p = self.svc.router.providers.get("sec")
        if p is None:
            raise DataError("unavailable", "SEC PROVIDER NOT CONFIGURED")
        return p

    async def facts(self, symbol: str) -> dict:
        """The FA company facts (cached with FA): {A, Q, extra, name, cik, source}."""
        env = await self.svc._sec(f"fa2:{symbol}", "facts", "fundamentals", symbol, lambda p: p.fundamentals(symbol))
        return env["data"]

    async def rows(self, symbol: str, mode: str = "A") -> tuple[dict, list[dict], list[str]]:
        """(facts, per-period rows oldest first on today's share basis, notes naming any split inferred)."""
        d = await self.facts(symbol)
        rows, splits = mt.split_adjust(mt.rows_of(d[mode], (d.get("extra") or {}).get(mode)))
        return d, rows, splits

    async def bars(self, symbol: str, range_: str = "10Y") -> tuple[list[float], list[float], str]:
        env = await self.svc.history(symbol, range_, "1d")
        data = env["data"]
        return list(data["t"]), list(data["c"]), env.get("source") or data.get("source") or "?"

    async def frame(self, tag: str, unit: str, period: str) -> dict[int, dict]:
        async def fetch() -> dict:
            try:
                body = await self.sec.frame(tag, unit, period)
            except ProviderError as e:
                if e.kind in ("not_found",) or str(e).startswith("404"):
                    return {"data": {"rows": {}}, "fallback_from": []}  # SEC has no frame yet (a future year)
                raise DataError("unavailable" if e.kind != "bad_request" else "bad_request", str(e)) from e
            return {"data": {"rows": {str(k): v for k, v in fr.parse_frame(body).items()}}, "fallback_from": []}

        env = await self.svc.swr(f"frame:{tag}:{unit}:{period}", FRAME_TTL, fetch)
        return {int(k): v for k, v in env["data"]["rows"].items()}

    async def concept_year(self, concept: str, year: int) -> dict[int, dict]:
        """One screen concept for every filer in one calendar year (first tag found per filer wins)."""
        maps = [await self.frame(tag, unit, fr.frame_period(year, inst)) for tag, unit, inst in fr.CONCEPTS[concept]]
        return fr.merge_concept(maps)

    # --- GF -----------------------------------------------------------------------------------------
    async def fn_gf(self, symbol: str | None = None, metric: str | None = None, period: str | None = None,
                    vs: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "USAGE: <SYM> GF [METRIC] [Q] [VS=MSFT,GOOGL]")
        code = (metric or "REVENUE").upper()
        if code not in mt.METRICS:
            raise DataError("bad_request", f"UNKNOWN METRIC {code}: {' '.join(mt.METRICS)}")
        mode = "Q" if (period or "A").upper() == "Q" else "A"
        syms = [resolve(symbol)] + [resolve(s) for s in (vs or "").split(",") if s.strip()][:MAX_PEERS]
        results = await asyncio.gather(*(self._gf_one(s, code, mode) for s in syms), return_exceptions=True)
        main = results[0]
        if isinstance(main, BaseException):
            raise main
        series, notes = [], []
        for s, r in zip(syms, results, strict=True):
            if isinstance(r, BaseException):
                notes.append(f"{s}: {r}")  # a peer that failed is named, never dropped silently
                continue
            series.append({"name": s, "points": [[_year_x(t), v] for t, v in r["points"]]})
        label = mt.FUNDAMENTAL[code][0] if code in mt.FUNDAMENTAL else mt.VALUATION[code][0]
        vals = [v for _, v in main["points"] if v is not None]
        unit = mt.FUNDAMENTAL[code][1] if code in mt.FUNDAMENTAL else "x"
        fmt = _pct if unit == "pct" else (lambda v: _num(v, 1)) if unit == "x" else (lambda v: _num(v / 1e9, 2) + "B" if v is not None else None) if unit == "money" else _num
        rows = [{"period": p, "value": v} for p, v in main["table"]]
        kind = "pct" if unit == "pct" else "money" if unit == "money" else "num"
        headline = [head("METRIC", label), head("LATEST", fmt(vals[-1]) if vals else None),
                    head("MEDIAN", fmt(median(vals)) if vals else None), head("MIN", fmt(min(vals)) if vals else None),
                    head("MAX", fmt(max(vals)) if vals else None), head("BASIS", main["basis"])]
        out = payload(syms[0], f"GF {syms[0]} · {label}", headline,
                      [section("values", "BY PERIOD" if code in mt.FUNDAMENTAL else "MONTH END",
                               [col("period", "PERIOD", "text", 14), col("value", label[:24], kind)], rows[::-1])],
                      [f"SOURCE: SEC XBRL COMPANY FACTS (10-K / 10-Q){' + DAILY CLOSES' if code in mt.VALUATION else ''}",
                       *(["MULTIPLES USE THE NEWEST PERIOD FILED ON OR BEFORE EACH DAY (NO LOOK-AHEAD); SHARES = DILUTED WEIGHTED AVERAGE"]
                         if code in mt.VALUATION else []), *main["splits"], *notes],
                      main["source"],
                      charts=[{"id": "gf", "title": f"{label} · {'QUARTERLY' if mode == 'Q' else 'ANNUAL'}", "xlabel": "YEAR",
                               "ylabel": label, "series": series}])
        return _env(out)

    async def _gf_one(self, sym: str, code: str, mode: str) -> dict:
        d, rows, splits = await self.rows(sym, mode)
        source = d.get("source")
        if code in mt.FUNDAMENTAL:
            pts = mt.fundamental_series(rows, code)
            table = [(r["label"], v) for r, (_, v) in zip(rows, pts, strict=True)]
            return {"points": pts, "table": table, "source": source, "basis": "QUARTERLY" if mode == "Q" else "ANNUAL", "splits": splits}
        t, c, psrc = await self.bars(sym, "10Y")
        base = mt.ttm(rows) if mode == "Q" else rows
        pts = mt.valuation_series(base, code, t, c)
        # Month-end table rows keep the table short; the chart has every day.
        month: dict[str, float | None] = {}
        for ts, v in pts:
            month[datetime.fromtimestamp(ts, UTC).strftime("%Y-%m")] = v
        return {"points": pts, "table": list(month.items()), "source": f"{source} + {psrc}",
                "basis": "DAILY, TTM FROM QUARTERS" if mode == "Q" else "DAILY, LAST FISCAL YEAR", "splits": splits}

    # --- EM -----------------------------------------------------------------------------------------
    async def fn_em(self, symbol: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "USAGE: <SYM> EM")
        sym = resolve(symbol)
        d, q_rows, splits = await self.rows(sym, "Q")
        surprises, est_note = [], None
        try:
            eeo = (await self.svc.research.fn_eeo(sym))["data"]
            surprises = next((s["rows"] for s in eeo["sections"] if s["id"] == "surprises"), [])
        except DataError as e:
            est_note = f"ESTIMATES NOT AVAILABLE: {e}"
        m = es.matrix(q_rows, surprises)
        years = m["years"][-8:]
        qs = ("Q1", "Q2", "Q3", "Q4")

        def grid(field: str) -> list[dict]:
            return [{"fy": f"FY{y}", **{q: (m["cells"].get((q, y)) or {}).get(field) for q in qs}} for y in reversed(years)]

        def cols(kind: str) -> list[dict]:
            return [col("fy", "FISCAL YEAR", "text", 12), *(col(q, q, kind) for q in qs)]

        sur_years = [y for y in years if any((m["cells"].get((q, y)) or {}).get("surprise") is not None for q in qs)]
        heat = {"id": "em", "title": "EPS SURPRISE (YAHOO ACTUAL VS ESTIMATE)", "xlabel": "FISCAL QUARTER", "ylabel": "FISCAL YEAR",
                "x": [1, 2, 3, 4], "y": [f"FY{y}" for y in sur_years],
                "z": [[(m["cells"].get((q, y)) or {}).get("surprise") for q in qs] for y in sur_years], "unit": "pct"} if sur_years else None
        out = payload(sym, f"EM {sym} · EARNINGS MATRIX", [head("COMPANY", d.get("name")), head("FISCAL YEARS", str(len(years)))],
                      [section("eps", "EPS DILUTED (SEC, GAAP)", cols("num"), grid("eps")),
                       section("revenue", "REVENUE (SEC)", cols("money"), grid("revenue")),
                       section("est", "EPS ESTIMATE (YAHOO CONSENSUS)", cols("num"), grid("est")),
                       section("surprise", "SURPRISE (YAHOO ACTUAL VS ESTIMATE)", cols("pct"), grid("surprise"))],
                      [("SEC EPS IS GAAP DILUTED; THE ESTIMATE AND ITS ACTUAL ARE YAHOO'S (USUALLY ADJUSTED EPS), SO THE SURPRISE "
                       "COMPARES YAHOO TO YAHOO"), "Q4 = FISCAL YEAR MINUS THE THREE 10-Q QUARTERS WHEN THE 10-K GIVES NO QUARTER",
                       "YAHOO KEEPS ONLY THE LAST FOUR QUARTERS OF ESTIMATES", *splits, *([est_note] if est_note else [])],
                      d.get("source"), heat=heat)
        return _env(out)

    # --- DDIS ---------------------------------------------------------------------------------------
    async def fn_ddis(self, symbol: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "USAGE: <SYM> DDIS")
        sym = resolve(symbol)
        d, rows, _splits = await self.rows(sym, "A")
        tagged = [r for r in rows if any(r.get(k) is not None for k in ("mat_y1", "mat_y2", "mat_y3", "mat_y4", "mat_y5", "mat_after"))]
        if not tagged:
            raise DataError("not_found", f"NO DEBT MATURITY TABLE TAGGED IN {sym}'S 10-K FILINGS (LongTermDebtMaturitiesRepaymentsOfPrincipal...)")
        r = tagged[-1]
        lad = mt.ladder(r)
        total = sum(x["amount"] for x in lad if x["amount"] is not None)
        debt = (r.get("long_term_debt") or 0.0) + (r.get("current_debt") or 0.0)
        url = None
        if r.get("accn") and d.get("cik"):
            url = f"https://www.sec.gov/Archives/edgar/data/{int(d['cik'])}/{r['accn'].replace('-', '')}/"
        for x in lad:
            x["url"] = url
        start = date.fromisoformat(r["end"]).year
        out = payload(sym, f"DDIS {sym} · DEBT MATURITY LADDER", [
            head("BALANCE SHEET DATE", r["end"]), head("FILING", f"{r.get('form') or '10-K'} FILED {r.get('filed') or '?'}"),
            head("ACCESSION", r.get("accn")), head("LADDER TOTAL", _num(total / 1e9, 2) + "B"),
            head("DEBT ON BALANCE SHEET", _num(debt / 1e9, 2) + "B" if debt else None),
        ], [section("ladder", f"PRINCIPAL DUE (FISCAL YEARS AFTER {start})",
                    [col("bucket", "WHEN", "text", 16), col("amount", "PRINCIPAL", "money"), col("share", "SHARE", "pct"),
                     col("tag", "XBRL TAG", "text", 40)], lad)],
            ["PRINCIPAL AT FACE VALUE FROM THE 10-K DEBT NOTE; THE BALANCE SHEET CARRIES DEBT NET OF DISCOUNTS, SO THE TOTALS DIFFER",
             "ENTER OPENS THE FILING", "COMMERCIAL PAPER AND LEASES ARE USUALLY NOT IN THE LADDER"], d.get("source"))
        return _env(out)

    # --- SCORE --------------------------------------------------------------------------------------
    async def fn_score(self, symbol: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "USAGE: <SYM> SCORE")
        sym = resolve(symbol)
        d, rows, splits = await self.rows(sym, "A")
        if len(rows) < 2:
            raise DataError("not_found", f"{sym}: NEEDS TWO ANNUAL REPORTS")
        cur, prev = rows[-1], rows[-2]
        notes = list(splits)
        mcap = sigma = r = None
        price_src = None
        try:
            _t, c, price_src = await self.bars(sym, "1Y")
            sh, sh_name = (cur.get("shares_out"), "SHARES OUTSTANDING") if cur.get("shares_out") else (cur.get("shares_diluted"), "DILUTED SHARES (AVG)")
            if c and sh:
                mcap = c[-1] * sh
                notes.append(f"MARKET CAP = LAST CLOSE {c[-1]:,.2f} x {sh_name} {sh:,.0f} FROM THE {cur['label']} FILING")
            lr = [math.log(b / a) for a, b in pairwise(c) if a and b and a > 0 and b > 0]
            if len(lr) > 60:
                mu = sum(lr) / len(lr)
                sigma = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1)) * math.sqrt(252)
        except DataError as e:
            notes.append(f"PRICE NOT AVAILABLE ({e}): ALTMAN Z AND MERTON NEED IT")
        try:
            curve = (await self.svc.rates())["data"]
            r, _par = mk.treasury_rate(curve, 1.0)
            notes.append(f"RISK-FREE = 1Y US TREASURY FROM THE CURVE OF {curve.get('date')}")
        except DataError as e:
            notes.append(f"RATES NOT AVAILABLE ({e}): MERTON NEEDS THE RISK-FREE RATE")
        scores = [
            ("ALTMAN Z (MANUFACTURERS)", sc.altman_z(cur, mcap)),
            ("ALTMAN Z'' (NON-MANUFACTURERS)", sc.altman_z2(cur)),
            ("PIOTROSKI F (0-9)", sc.piotroski_f(cur, prev)),
            ("BENEISH M", sc.beneish_m(cur, prev)),
            ("OHLSON O", sc.ohlson_o(cur, prev)),
            ("MERTON DISTANCE TO DEFAULT", sc.merton_dd(mcap, sigma, cur.get("current_liabilities"), cur.get("long_term_debt"), r)),
        ]
        summary = [{"name": n, "score": s["score"], "zone": s["zone"] or ("NOT COMPUTABLE: " + ", ".join(s["missing"]).upper())}
                   for n, s in scores]
        sections = [section("summary", f"SCORES · {cur['label']} VS {prev['label']}",
                            [col("name", "SCORE", "text", 30), col("score", "VALUE", "num"), col("zone", "READS AS", "text", 40)], summary)]
        for i, (n, s) in enumerate(scores):
            if s["inputs"]:
                sections.append(section(f"score{i}", n,
                                        [col("input", "INPUT", "text", 36), col("value", "VALUE", "num4")],
                                        [{"input": a, "value": b} for a, b in s["inputs"]], note=f"FORMULA: {s['formula']}"))
        filing = f"{cur.get('form') or '10-K'} FILED {cur.get('filed') or '?'} (ACCESSION {cur.get('accn') or '?'})"
        out = payload(sym, f"SCORE {sym} · {SCORE_LABEL}", [head("COMPANY", d.get("name")), head("FILING", filing),
                                                            head("LABEL", SCORE_LABEL)],
                      sections, [SCORE_LABEL, ("EBIT = OPERATING INCOME; Z IS BUILT FOR MANUFACTURERS, Z'' FOR OTHERS; "
                                 "SCORES ARE NOT MEANINGFUL FOR BANKS AND INSURERS"), *notes],
                      f"{d.get('source')}{' + ' + price_src if price_src else ''}")
        return _env(out)

    # --- FRM: one concept for every filer, point in time ------------------------------------------------
    async def fn_frm(self, tag: str | None = None, period: str | None = None, unit: str | None = None,
                     asof: str | None = None, **_: Any) -> dict:
        if not tag:
            raise DataError("bad_request", "USAGE: FRM <US-GAAP TAG> [CY2024|CY2024Q4|CY2024Q4I] [UNIT=USD] [ASOF=YYYY-MM-DD]")
        unit = (unit or "USD").upper().replace("SHARES", "shares")
        per = (period or f"CY{date.today().year - 1}").upper()
        rows_by_cik = await self.frame(tag, unit, per)
        if not rows_by_cik:
            raise DataError("not_found", f"SEC HAS NO FRAME {tag} {per} (NOT FILED YET, OR NOT A US-GAAP TAG)")
        annual = "Q" not in per or per.endswith("I") and per[6:8] == "Q4"
        cutoff = date.fromisoformat(asof) if asof else None
        tick = await self.sec.tickers_by_cik()
        rows, hidden = [], 0
        for cik, r in rows_by_cik.items():
            known = fr.known_date(r["end"], annual)
            if cutoff and known > cutoff:
                hidden += 1
                continue
            rows.append({"ticker": ",".join(tick.get(cik, [])[:2]) or None, "name": r["name"], "value": r["val"], "end": r["end"],
                         "known": known.isoformat(), "accn": r["accn"]})
        rows.sort(key=lambda x: -x["value"])
        out = payload(None, f"FRM {tag} · {per}", [
            head("FILERS", f"{len(rows):,}"), head("HIDDEN BY ASOF", f"{hidden:,}" if cutoff else None),
            head("ASOF", asof), head("UNIT", unit)],
            [section("frame", f"{tag} · {per}", [col("ticker", "TICKER", "text", 10), col("name", "FILER", "text", 34),
                                                 col("value", "VALUE", "money" if unit == "USD" else "num"), col("end", "PERIOD END", "date"),
                                                 col("known", "KNOWN BY", "date"), col("accn", "ACCESSION", "text", 22)], rows[:500])],
            [fr.KNOWN_RULE, "TOP 500 BY VALUE; SEC FITS EACH FILER'S FISCAL PERIOD TO THE CALENDAR PERIOD"], "SEC XBRL FRAMES")
        return _env(out)

    # --- EQS BT: monthly screen backtest ------------------------------------------------------------------
    async def fn_eqsbt(self, rules: str | None = None, univ: str | None = None, start: str | None = None,
                       vs: str | None = None, **_: Any) -> dict:
        try:
            parsed = fr.parse_rules((rules or "").split())
        except ValueError as e:
            raise DataError("bad_request", str(e)) from e
        syms = [resolve(s) for s in (univ or "").removeprefix("LIST:").split(",") if s.strip()]
        if not syms:
            raise DataError("bad_request", "UNIV=LIST:AAPL,MSFT,... IS REQUIRED: NO FREE WHOLE-MARKET PRICE HISTORY")
        if len(syms) > MAX_UNIVERSE:
            raise DataError("bad_request", f"UNIVERSE CAPPED AT {MAX_UNIVERSE} NAMES (YAHOO PACING)")
        y0 = int(start or date.today().year - 5)
        bench = resolve(vs or "SPY")
        envs, errs = await fetch_bars(self.svc, [*syms, bench], "10Y", tolerate=True)
        if not any(s in envs for s in syms):
            raise DataError("not_found", "NO PRICE HISTORY FOR ANY NAME: " + "; ".join(f"{s} {e}" for s, e in errs.items()))
        ciks = {}
        for s in syms:
            try:
                ciks[s] = await self.sec.cik(s)
            except ProviderError:
                pass
        years = list(range(y0 - 2, date.today().year + 1))
        need_mom = any(f == "MOM12" for f, _, _ in parsed)
        concepts = {k: {y: await self.concept_year(k, y) for y in years} for k in fr.CONCEPTS}

        # Monthly calendar from the first name with bars.
        ref = next(envs[s]["data"] for s in syms if s in envs)
        t_all = list(ref["t"])
        ends = [i for i in fr.month_ends(t_all) if datetime.fromtimestamp(t_all[i], UTC).year >= y0]
        closes = {s: dict(zip(envs[s]["data"]["t"], envs[s]["data"]["c"], strict=False)) for s in envs}

        def px(s: str, ts: float) -> float | None:
            return closes.get(s, {}).get(ts)

        rets, bench_rets, held_counts, months = [], [], [], []
        for a, b in pairwise(ends):
            ta, tb = t_all[a], t_all[b]
            asof = datetime.fromtimestamp(ta, UTC).date()
            picks = []
            for s in syms:
                if s not in envs or s not in ciks:
                    continue
                vals = self._known_fields(concepts, ciks[s], asof, years)
                if need_mom:
                    t12 = t_all[max(0, a - 252)]
                    p0, p1 = px(s, t12), px(s, ta)
                    vals["MOM12"] = p1 / p0 - 1 if p0 and p1 else None
                if fr.passes(vals, parsed):
                    pa, pb = px(s, ta), px(s, tb)
                    if pa and pb:
                        picks.append(pb / pa - 1)
            rets.append(sum(picks) / len(picks) if picks else 0.0)  # no match = cash at 0% that month
            held_counts.append(len(picks))
            ba, bb = px(bench, ta), px(bench, tb)
            bench_rets.append(bb / ba - 1 if ba and bb else None)
            months.append(datetime.fromtimestamp(tb, UTC).strftime("%Y-%m"))
        st = fr.stats(rets)
        bvals = [x for x in bench_rets if x is not None]
        bst = fr.stats(bvals) if len(bvals) == len(bench_rets) else None

        def curve(rs):
            eq, pts = 1.0, []
            for m, r in zip(months, rs, strict=True):
                if r is None:
                    continue
                eq *= 1 + r
                pts.append([_year_x(m + "-28"), eq])
            return pts

        series = [{"name": "SCREEN", "points": curve(rets)}]
        if bst:
            series.append({"name": bench, "points": curve(bench_rets), "dash": True})
        stat_rows = [{"what": n, "screen": st.get(k), "bench": (bst or {}).get(k)} for n, k in
                     (("TOTAL RETURN", "total"), ("CAGR", "cagr"), ("VOLATILITY (ANNUAL)", "vol"), ("MAX DRAWDOWN", "maxdd"),
                      ("MONTHS UP", "hit"))]
        monthly = [{"month": m, "held": h, "ret": r, "bench": br} for m, h, r, br in zip(months, held_counts, rets, bench_rets, strict=True)]
        notes = [SURVIVORSHIP, BT_LABEL, fr.KNOWN_RULE, ("EQUAL WEIGHT, REBALANCED MONTHLY AT THE CLOSE; NO FEES OR SLIPPAGE; "
                 "A MONTH WITH NO MATCH IS HELD IN CASH AT 0%"), "CLOSES ARE ADJUSTED AS THE PRICE SOURCE SENDS THEM"]
        missing = [s for s in syms if s not in envs] + [s for s in syms if s in envs and s not in ciks]
        if missing:
            notes.append("LEFT OUT (NO PRICES OR NOT AN SEC FILER): " + ", ".join(missing))
        if bench in errs:
            notes.append(f"BENCHMARK {bench} NOT AVAILABLE: {errs[bench]}")
        out = payload(None, f"EQS BT · {' '.join(rules.split()) if rules else ''}", [
            head("LABEL", SURVIVORSHIP), head("UNIVERSE", f"{len(syms)} NAMES"), head("FROM", str(y0)),
            head("AVG NAMES HELD", _num(sum(held_counts) / len(held_counts), 1) if held_counts else None),
            head("CAGR", _pct(st["cagr"])), head(f"{bench} CAGR", _pct(bst["cagr"]) if bst else None)],
            [section("stats", "RESULT", [col("what", "", "text", 20), col("screen", "SCREEN", "pct"), col("bench", bench, "pct")], stat_rows),
             section("monthly", "MONTH BY MONTH", [col("month", "MONTH", "text", 10), col("held", "HELD", "int"),
                                                   col("ret", "SCREEN", "pct"), col("bench", bench, "pct")], monthly[::-1])],
            notes, "SEC XBRL FRAMES + " + ", ".join(sorted({envs[s].get("source") or "?" for s in envs})),
            status=BT_LABEL,
            charts=[{"id": "eqsbt", "title": f"GROWTH OF 1 · {BT_LABEL}", "xlabel": "YEAR", "ylabel": "GROWTH OF 1", "series": series}])
        return _env(out)

    @staticmethod
    def _known_fields(concepts: dict[str, dict[int, dict[int, dict]]], cik: int, asof: date, years: list[int]) -> dict:
        """Screen fields from the newest calendar year whose numbers were KNOWN on `asof` (fr.known_date)."""
        for y in sorted(years, reverse=True):
            rev = concepts["revenue"].get(y, {}).get(cik) or concepts["net_income"].get(y, {}).get(cik)
            if rev is None or fr.known_date(rev["end"]) > asof:
                continue
            cur = {k: (concepts[k].get(y, {}).get(cik) or {}).get("val") for k in fr.CONCEPTS}
            prev = {k: (concepts[k].get(y - 1, {}).get(cik) or {}).get("val") for k in fr.CONCEPTS}
            return fr.fields_for(cur, prev)
        return {}

    # --- IBQ: industry roll-ups -----------------------------------------------------------------------
    async def fn_ibq(self, year: str | None = None, by: str | None = None, **_: Any) -> dict:
        y = int(year or date.today().year - 1)
        group_by = "industry" if (by or "").upper().startswith("IND") else "sector"
        scr = (await self.svc.screener())["data"]
        names = scr["industries"] if group_by == "industry" else scr["sectors"]
        gi = scr["columns"].index(group_by)
        mi, si = scr["columns"].index("mcap"), scr["columns"].index("symbol")
        ciks = await self.sec.tickers_by_cik()
        by_ticker = {t: c for c, ts in ciks.items() for t in ts}
        cur = {k: await self.concept_year(k, y) for k in ("revenue", "net_income", "operating_income")}
        prev_rev = await self.concept_year("revenue", y - 1)
        groups: dict[str, dict[str, list[float]]] = {}
        matched = 0
        for row in scr["rows"]:
            cik = by_ticker.get(row[si]) or by_ticker.get(str(row[si]).replace("/", "-"))
            g = names[row[gi]] if row[gi] is not None and row[gi] < len(names) else ""
            if cik is None or not g:
                continue
            rev = (cur["revenue"].get(cik) or {}).get("val")
            if not rev or rev <= 0:
                continue
            matched += 1
            ni = (cur["net_income"].get(cik) or {}).get("val")
            oi = (cur["operating_income"].get(cik) or {}).get("val")
            pr = (prev_rev.get(cik) or {}).get("val")
            mcap = row[mi]
            b = groups.setdefault(g, {"nm": [], "om": [], "gr": [], "ps": [], "pe": [], "n": []})
            b["n"].append(1.0)
            if ni is not None:
                b["nm"].append(ni / rev)
            if oi is not None:
                b["om"].append(oi / rev)
            if pr and pr > 0:
                b["gr"].append(rev / pr - 1)
            if mcap:
                b["ps"].append(mcap / rev)
                if ni and ni > 0:
                    b["pe"].append(mcap / ni)
        rows = [{"group": g, "n": len(b["n"]), "nm": fr.median_or_none(b["nm"]), "nm_iqr": fr.iqr(b["nm"]),
                 "om": fr.median_or_none(b["om"]), "gr": fr.median_or_none(b["gr"]), "gr_iqr": fr.iqr(b["gr"]),
                 "ps": fr.median_or_none(b["ps"]), "pe": fr.median_or_none(b["pe"])} for g, b in groups.items()]
        rows.sort(key=lambda r: -r["n"])
        out = payload(None, f"IBQ · {group_by.upper()} ROLL-UPS · CY{y}", [
            head("COMPANIES MATCHED", f"{matched:,}"), head("GROUPS", str(len(rows))), head("YEAR", f"CY{y}"),
            head("GROUPED BY", f"{group_by.upper()} (NASDAQ SCREENER)")],
            [section("ibq", f"MEDIANS BY {group_by.upper()}", [
                col("group", group_by.upper(), "text", 30), col("n", "N", "int"), col("nm", "NET MARGIN", "pct"),
                col("nm_iqr", "NM IQR", "pct"), col("om", "OP MARGIN", "pct"), col("gr", "REV GROWTH", "pct"),
                col("gr_iqr", "GROWTH IQR", "pct"), col("ps", "P/S", "num"), col("pe", "P/E", "num")], rows)],
            [("FUNDAMENTALS: SEC XBRL FRAMES FOR THE CALENDAR YEAR; MARKET CAP: TODAY'S SCREENER (SO P/S AND P/E MIX TODAY'S PRICE "
             "WITH THAT YEAR'S NUMBERS)"), "IQR = 75TH MINUS 25TH PERCENTILE (DISPERSION); P/E ONLY OVER PROFITABLE COMPANIES",
             "SIC CODES ARE NOT IN THE FREE SCREENER: GROUPS ARE NASDAQ'S SECTOR / INDUSTRY", "GROUPS WITH FEW NAMES ARE NOISY"],
            f"SEC XBRL FRAMES + {scr.get('source')}")
        return _env(out)

    # --- EQS fundamentals columns (live screener) -----------------------------------------------------
    async def fn_eqsfund(self, year: str | None = None, **_: Any) -> dict:
        """Formula fields (MARGIN OPMARGIN ROE GROWTH DE) for every screener name that files with the SEC.

        The live EQS panel joins this to its universe by symbol and lets `ROE>15 MARGIN>10` filter and sort on it. Same
        concepts and formulas as EQS BT (`frames.fields_for`), on the newest calendar year most filers have reported.
        Ratios that are fractions in `fields_for` are served here in PERCENT (so `ROE>15` and `ROE>15%` mean the same).
        """
        y = int(year) if year else date.today().year - 1
        notes: list[str] = []
        concepts = {k: await self.concept_year(k, y) for k in fr.CONCEPTS}
        if not year and len(concepts["revenue"]) < EQSFUND_MIN_FILERS:
            # Early in the year most 10-Ks are not in yet: use the year before and say so.
            y -= 1
            concepts = {k: await self.concept_year(k, y) for k in fr.CONCEPTS}
            notes.append(f"CY{y + 1} IS NOT FILED BY MOST COMPANIES YET: SHOWING CY{y}")
        prev_rev = await self.concept_year("revenue", y - 1)
        scr = (await self.svc.screener())["data"]
        si = scr["columns"].index("symbol")
        by_ticker = {t: c for c, ts in (await self.sec.tickers_by_cik()).items() for t in ts}
        rows: dict[str, list[float | None]] = {}
        for row in scr["rows"]:
            sym = row[si]
            cik = by_ticker.get(sym) or by_ticker.get(str(sym).replace("/", "-"))
            if cik is None:
                continue
            cur = {k: (m.get(cik) or {}).get("val") for k, m in concepts.items()}
            f = fr.fields_for(cur, {"revenue": (prev_rev.get(cik) or {}).get("val")})
            vals = [None if f[k] is None else round(f[k] * (1 if k == "DE" else 100), 4) for k in EQSFUND_FIELDS]
            if any(v is not None for v in vals):
                rows[sym] = vals
        notes += [f"SEC XBRL FRAMES, CALENDAR YEAR {y}; MARKET DATA IS TODAY'S SCREENER", "US SEC FILERS ONLY: OTHER NAMES NEVER PASS A FUNDAMENTALS FILTER",
                  "MARGIN OPMARGIN ROE GROWTH ARE PERCENT; DE = LIABILITIES / EQUITY (A RATIO); ROE AND DE NEED POSITIVE EQUITY"]
        return _env({"year": y, "fields": list(EQSFUND_FIELDS), "rows": rows, "notes": notes, "source": "SEC XBRL FRAMES"})

    # --- REVS: estimate revision score ---------------------------------------------------------------
    async def fn_revs(self, symbol: str | None = None, **_: Any) -> dict:
        if not symbol:
            raise DataError("bad_request", "USAGE: <SYM> REVS")
        sym = resolve(symbol)
        eeo = (await self.svc.research.fn_eeo(sym))["data"]
        sec = {s["id"]: s["rows"] for s in eeo["sections"]}
        res = es.revision_score(sec.get("trend", []), sec.get("revisions", []))
        if res["score"] is None:
            raise DataError("not_found", f"{sym}: NO ESTIMATE TREND OR REVISION COUNTS AT THE SOURCE")
        out = payload(sym, f"REVS {sym} · ESTIMATE REVISION SCORE", [
            head("SCORE (-100 TO +100)", _num(res["score"], 0), res["score"]), head("BREADTH", _num(res["breadth"], 2)),
            head("DRIFT", _num(res["drift"], 2))],
            [section("inputs", "INPUTS PER PERIOD", [
                col("period", "PERIOD", "text", 14), col("now", "EPS EST NOW", "num"), col("ch30", "30D CHANGE", "pct"),
                col("ch90", "90D CHANGE", "pct"), col("up30", "UP 30D", "int"), col("down30", "DOWN 30D", "int"),
                col("breadth", "BREADTH", "num")], res["rows"])],
            ["SCORE = 50 x BREADTH + 50 x DRIFT", "BREADTH = MEAN (UP - DOWN) / (UP + DOWN) OVER 30 DAYS",
             "DRIFT = MEAN 30-DAY ESTIMATE CHANGE / 5%, CAPPED TO -1..+1", "INPUTS: YAHOO EPS TREND AND REVISIONS (EEO)",
             "A TRANSPARENT HEURISTIC, NOT A FORECAST"], eeo.get("source"))
        return _env(out)
