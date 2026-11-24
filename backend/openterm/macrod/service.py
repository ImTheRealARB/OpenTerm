"""The async side of Phase 30: ask the providers through the router (or the existing FRED / curve / holiday services), build the table
payload (research/table.py), cache it with `svc.swr`. Each function returns the standard envelope. Pure maths lives in curves.py,
calendars.py and stats helpers below; source parsing in parse.py.

A board made of many series never fails because ONE series is missing: that row shows its reason and the rest still draws. It fails
only when every series failed (then the first reason is shown, like NRG).
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..errkinds import KEY_REQUIRED
from ..errors import DataError
from ..redact import redact
from ..research.table import col, head, payload, section
from ..router import AllFailed
from . import boards as B
from . import calendars as C
from . import curves as K
from . import parse as P

TTL = {"mmr": 1800.0, "nowc": 6 * 3600.0, "ecfc": 12 * 3600.0, "fomc": 6 * 3600.0, "board": 3600.0, "tsys": 1800.0, "wpe": 3600.0,
       "wcrs": 3600.0, "nrgf": 3600.0, "agri": 6 * 3600.0}
DAY = 86400
STALE_DAYS = 270  # a monthly or quarterly series with nothing newer than this is flagged as possibly stopped


def _today() -> date:
    return datetime.now(UTC).date()


def _local(data: dict, source: str) -> dict:
    """Envelope for a board computed here with no network call (CTM, CDR)."""
    return {"data": data, "source": source, "as_of": time.time(), "age_s": 0.0, "stale": False, "fallback_from": []}


async def _call(svc: Any, capability: str, fn) -> tuple[Any, list]:
    return await svc.router.call(capability, fn)


# --- series helpers (pure) ----------------------------------------------------------------------------------------------------


def _pairs(d: dict) -> list[tuple[int, float]]:
    """MacroSeries dict -> [(epoch, value)] ascending, missing values dropped."""
    return [(t, v) for t, v in zip(d["t"], d["v"], strict=True) if v is not None]


def value_before(pts: list[tuple[int, float]], days: int) -> float | None:
    """The last value at least `days` before the newest point (None if the series is shorter)."""
    if not pts:
        return None
    cut = pts[-1][0] - days * DAY
    for t, v in reversed(pts):
        if t <= cut:
            return v
    return None


def yoy_pct(pts: list[tuple[int, float]]) -> float | None:
    prev = value_before(pts, 360)
    return (pts[-1][1] / prev - 1.0) if prev not in (None, 0) and pts else None


def percentile(values: list[float], x: float) -> float | None:
    return sum(v <= x for v in values) / len(values) if values else None


async def _fred_many(svc: Any, ids: list[str], rng: str = "5Y") -> dict[str, dict | str]:
    """{id: MacroSeries dict | reason text}. A failure is the redacted reason, never an exception."""
    got = await asyncio.gather(*(svc.fred_series(i, rng) for i in ids), return_exceptions=True)
    out: dict[str, dict | str] = {}
    for i, g in zip(ids, got, strict=True):
        if isinstance(g, DataError):
            out[i] = (f"NO OBSERVATIONS IN THE LAST {rng} (FRED {i} MAY HAVE ENDED)" if g.kind == "not_found" else redact(str(g))[:80])
        elif isinstance(g, BaseException):
            raise g
        else:
            out[i] = g["data"]
    return out


def _all_failed(got: dict[str, dict | str]) -> None:
    if got and all(isinstance(v, str) for v in got.values()):
        raise DataError("unavailable", "EVERY FRED SERIES FAILED: " + next(iter(got.values())))


def _row_from(d: dict | str, kind: str, day_chg: int, yoy: bool = False, scale: float = 1.0) -> dict:
    """Common columns for a FRED row: last, date, change over `day_chg` days (points for a rate, percent for a level), 1Y change, y/y."""
    if isinstance(d, str):
        return {"note": d}
    pts = [(t, v * scale) for t, v in _pairs(d)]
    last = pts[-1][1] if pts else None
    prev, prev_y = value_before(pts, day_chg), value_before(pts, 365)
    row = {"last": last, "date": d.get("last_date"), "freq": (d.get("frequency") or _freq(pts)).upper()}
    if kind == "rate":
        row["chg"] = (last - prev) if prev is not None and last is not None else None
        row["chg_1y"] = (last - prev_y) if prev_y is not None and last is not None else None
    else:
        row["chg_pct"] = (last / prev - 1) if prev not in (None, 0) and last is not None else None
        row["chg_1y_pct"] = (last / prev_y - 1) if prev_y not in (None, 0) and last is not None else None
    if yoy:
        row["yoy"] = yoy_pct(pts)
    last_d = d.get("last_date")
    if last_d and (_today() - date.fromisoformat(str(last_d)[:10])).days > STALE_DAYS:
        row["note"] = f"LAST VALUE {last_d}: THE SERIES MAY HAVE STOPPED"
    return row


def _freq(pts: list[tuple[int, float]]) -> str:
    if len(pts) < 3:
        return "-"
    gap = (pts[-1][0] - pts[-3][0]) / 2 / DAY
    return "DAILY" if gap < 5 else "WEEKLY" if gap < 10 else "MONTHLY" if gap < 40 else "QUARTERLY" if gap < 120 else "ANNUAL"


# --- MMR ------------------------------------------------------------------------------------------------------------------------


async def mmr(svc: Any) -> dict:
    async def fetch() -> dict:
        res = await asyncio.gather(_call(svc, "nyfed_rates", lambda p: p.nyfed_rates()), _call(svc, "estr", lambda p: p.estr()),
                                   _call(svc, "sonia", lambda p: p.sonia()), return_exceptions=True)
        series: dict[str, tuple[str, list[dict]]] = {}
        notes, sources, failed = [], [], []
        ny, es, so = res
        if isinstance(ny, AllFailed):
            notes.append(f"NY FED RATES UNAVAILABLE: {redact(str(ny))[:80]}")
        elif isinstance(ny, BaseException):
            raise ny
        else:
            for k, rows in ny[0]["rates"].items():
                series[k] = ("USD", rows)
            sources.append(ny[0]["source"])
            failed += ny[0]["failed"]
        for name, r, ccy in (("ESTR", es, "EUR"), ("SONIA", so, "GBP")):
            if isinstance(r, AllFailed):
                notes.append(f"{name} UNAVAILABLE: {redact(str(r))[:80]}")
            elif isinstance(r, BaseException):
                raise r
            else:
                series[name] = (ccy, [{"date": d, "rate": v} for d, v in r[0]["points"]])
                sources.append(r[0]["source"])
        if not series:
            raise DataError("unavailable", "NO MONEY-MARKET RATE ANSWERED")
        rows, charts = [], []
        for name, (ccy, pts) in series.items():
            last, prev = pts[0], pts[1] if len(pts) > 1 else None
            month = pts[min(20, len(pts) - 1)]
            rows.append({"rate": name, "ccy": ccy, "last": last["rate"], "date": last["date"],
                         "chg_1d": (last["rate"] - prev["rate"]) * 100 if prev else None, "chg_1m": (last["rate"] - month["rate"]) * 100,
                         "p1": last.get("p1"), "p99": last.get("p99"), "volume": (last.get("volume_bn") or 0) * 1e9 or None})
            charts.append({"name": name, "points": [[-i, p["rate"]] for i, p in enumerate(pts)]})
        if failed:
            notes.append("NOT ANSWERED: " + ", ".join(failed))
        notes += ["CHANGES IN BASIS POINTS; 1M = 20 PUBLICATIONS AGO. P1 / P99 = 1ST AND 99TH PERCENTILE OF THE DAY'S TRADES (NY FED RATES ONLY)",
                  "SOURCES: FEDERAL RESERVE BANK OF NEW YORK (SOFR, TGCR, BGCR, EFFR, OBFR), ECB (ESTR), BANK OF ENGLAND (SONIA)"]
        sec = section("rates", "OVERNIGHT REFERENCE RATES", [
            col("rate", "RATE"), col("ccy", "CCY"), col("last", "LAST %", "num4"), col("date", "DATE", "date"), col("chg_1d", "1D BP", "bp"),
            col("chg_1m", "1M BP", "bp"), col("p1", "P1 %", "num"), col("p99", "P99 %", "num"), col("volume", "VOLUME", "money")], rows)
        sofr = next((r for r in rows if r["rate"] == "SOFR"), rows[0])
        data = payload("MMR", "MMR MONEY MARKET RATES", [head(sofr["rate"], f"{sofr['last']:.2f}% {sofr['date']}", sofr["last"]),
                                                         head("RATES", str(len(rows)), len(rows))], [sec], notes, " + ".join(sources),
                       charts=[{"id": "hist", "title": "LAST ~60 PUBLICATIONS", "xlabel": "PUBLICATIONS AGO", "ylabel": "%", "series": charts}])
        return {"data": data, "source": " + ".join(sources), "fallback_from": []}

    return await svc.swr("md:mmr", TTL["mmr"], fetch)


# --- NOWC -----------------------------------------------------------------------------------------------------------------------


async def nowc(svc: Any) -> dict:
    async def fetch() -> dict:
        out, failed = await _call(svc, "gdpnow", lambda p: p.gdpnow())
        path, past = out["path"], out["past"]
        rows = [{**r, "chg": (r["gdp"] - path[i - 1]["gdp"]) * 100 if i else None} for i, r in enumerate(path)]
        last = path[-1]
        hist = [{"quarter": q["quarter"], "first": q["first"], "final": q["final"], "rev": (q["final"] - q["first"]) * 100, "bea": q["bea"],
                 "err": (q["final"] - q["bea"]) * 100 if q["bea"] is not None else None, "n": q["n"], "final_date": q["final_date"]}
                for q in reversed(past[-12:])]
        m = re.search(r"(\d{2}):Q(\d)", path[0]["releases"])
        quarter = f"20{m.group(1)}Q{m.group(2)}" if m else "CURRENT QUARTER"
        secs = [section("path", f"{quarter} NOWCAST PATH (EACH DATA RELEASE)", [
                    col("date", "DATE", "date"), col("gdp", "NOWCAST % SAAR", "num"), col("chg", "CHANGE BP", "bp"), col("releases", "RELEASES")],
                    list(reversed(rows))),
                section("past", "PAST QUARTERS: FIRST VS FINAL NOWCAST", [
                    col("quarter", "QUARTER"), col("first", "FIRST %", "num"), col("final", "FINAL %", "num"), col("rev", "REVISION BP", "bp"),
                    col("bea", "BEA ADVANCE %", "num"), col("err", "FINAL - BEA BP", "bp"), col("n", "UPDATES", "int"), col("final_date", "FINAL ON", "date")], hist,
                    "FINAL = THE LAST NOWCAST BEFORE THE BEA ADVANCE ESTIMATE; BEA ADVANCE AS RECORDED IN THE GDPNOW WORKBOOK")]
        charts = [{"id": "path", "title": f"{quarter} NOWCAST PATH", "xlabel": "UPDATE NUMBER", "ylabel": "% SAAR",
                   "series": [{"name": "GDPNOW", "points": [[i, r["gdp"]] for i, r in enumerate(path)]}]}]
        for q in past[-3:]:
            charts[0]["series"].append({"name": q["quarter"], "points": [[i, r["gdp"]] for i, r in enumerate(q["path"])], "dash": True})
        notes = ["GDPNOW IS A MODEL ESTIMATE (ATLANTA FED), NOT AN OFFICIAL FORECAST: REAL GDP GROWTH, SEASONALLY ADJUSTED ANNUAL RATE",
                 "NY FED STAFF NOWCAST: NOT SHOWN (ITS PAGE IS SCRIPT-DRIVEN WITH NO CLEAN DOWNLOAD, CHECKED 2026-11-24)"]
        data = payload("NOWC", "NOWC GDP NOWCAST", [head("QUARTER", quarter), head("GDPNOW", f"{last['gdp']:.2f}% {last['date']}", last["gdp"]),
                                                   head("UPDATES", str(len(path)), len(path))], secs, notes, out["source"], charts=charts)
        return {"data": data, "source": out["source"], "fallback_from": failed}

    return await svc.swr("md:nowc", TTL["nowc"], fetch)


# --- ECFC -----------------------------------------------------------------------------------------------------------------------


async def ecfc(svc: Any) -> dict:
    countries = tuple(c for c, _ in B.ECFC_COUNTRIES)
    names = dict(B.ECFC_COUNTRIES)

    async def fetch() -> dict:
        y = _today().year
        tasks = [_call(svc, "imf_weo", lambda p: p.imf_weo(tuple(i for i, _ in B.IMF_INDICATORS), countries)),
                 _call(svc, "oecd_eo", lambda p: p.oecd_eo(countries, tuple(m for m, _ in B.OECD_MEASURES), y - 2)),
                 _call(svc, "spf", lambda p: p.spf())]
        imf, oecd, spf = await asyncio.gather(*tasks, return_exceptions=True)
        sep = await _fred_many(svc, [x for s in B.SEP for x in (s[0], s[2], s[3])], "MAX")
        secs, notes, sources = [], [], []
        years = [str(y), str(y + 1)]
        if isinstance(imf, BaseException):
            if not isinstance(imf, AllFailed):
                raise imf
            notes.append(f"IMF WEO UNAVAILABLE: {redact(str(imf))[:80]}")
        else:
            v = imf[0]["values"]
            rows = [{"country": names[c], **{f"{i}_{yy}": v.get(i, {}).get(c, {}).get(yy) for i, _ in B.IMF_INDICATORS for yy in years}}
                    for c in countries]
            secs.append(section("imf", "IMF WORLD ECONOMIC OUTLOOK", [col("country", "COUNTRY")] + [
                col(f"{i}_{yy}", f"{lbl.split(' %')[0][:14]} {yy}", "num") for i, lbl in B.IMF_INDICATORS for yy in years], rows,
                "IMF PROJECTIONS (WEO, LATEST VINTAGE ON THE DATAMAPPER). INFLATION = ANNUAL AVERAGE CPI"))
            sources.append(imf[0]["source"])
        if isinstance(oecd, BaseException):
            if not isinstance(oecd, AllFailed):
                raise oecd
            notes.append(f"OECD ECONOMIC OUTLOOK UNAVAILABLE: {redact(str(oecd))[:80]}")
        else:
            v = oecd[0]["values"]
            rows = [{"country": names[c], **{f"{m}_{yy}": v.get((c, m), {}).get(yy) for m, _ in B.OECD_MEASURES for yy in years}}
                    for c in countries if any((c, m) in v for m, _ in B.OECD_MEASURES)]
            secs.append(section("oecd", "OECD ECONOMIC OUTLOOK", [col("country", "COUNTRY")] + [
                col(f"{m}_{yy}", f"{lbl.split(' %')[0][:14]} {yy}", "num") for m, lbl in B.OECD_MEASURES for yy in years], rows,
                "OECD PROJECTIONS (LATEST ECONOMIC OUTLOOK). COUNTRIES THE OUTLOOK DOES NOT COVER ARE LEFT OUT"))
            sources.append(oecd[0]["source"])
        if isinstance(spf, BaseException):
            if not isinstance(spf, AllFailed):
                raise spf
            notes.append(f"SPF UNAVAILABLE: {redact(str(spf))[:80]}")
        else:
            rows = []
            for k, d in spf[0]["vars"].items():
                label = P.SPF_FILES[k][3]
                for q in d["quarterly"]:
                    rows.append({"var": label, "survey": d["survey"], "period": q["period"], "kind": "QUARTER", "value": q["value"]})
                for a in d["annual"]:
                    rows.append({"var": label, "survey": d["survey"], "period": a["period"], "kind": "YEAR AVERAGE", "value": a["value"]})
            secs.append(section("spf", "SURVEY OF PROFESSIONAL FORECASTERS (MEDIAN)", [
                col("var", "VARIABLE"), col("survey", "SURVEY"), col("period", "PERIOD"), col("kind", "KIND"), col("value", "MEDIAN", "num")],
                rows, "PHILADELPHIA FED SURVEY: A REAL CONSENSUS OF PRIVATE FORECASTERS. QUARTER ROWS: THE FIRST IS THE LAST KNOWN QUARTER"))
            sources.append(spf[0]["source"])
        sep_rows = []
        for med, label, hi, lo in B.SEP:
            d = sep.get(med)
            if not isinstance(d, dict):
                sep_rows.append({"var": label, "note": d})
                continue
            hd, ld = sep.get(hi), sep.get(lo)
            his = dict(_pairs(hd)) if isinstance(hd, dict) else {}
            los = dict(_pairs(ld)) if isinstance(ld, dict) else {}
            for t, v in _pairs(d):
                yr = datetime.fromtimestamp(t, UTC).year
                if yr < y:
                    continue
                sep_rows.append({"var": label, "year": str(yr), "median": v, "high": his.get(t), "low": los.get(t),
                                 "spread": (his[t] - los[t]) if t in his and t in los else None})
        if any("median" in r for r in sep_rows):
            secs.append(section("sep", "FOMC SUMMARY OF ECONOMIC PROJECTIONS", [
                col("var", "VARIABLE"), col("year", "YEAR"), col("median", "MEDIAN", "num"), col("low", "RANGE LOW", "num"),
                col("high", "RANGE HIGH", "num"), col("spread", "SPREAD", "num"), col("note", "NOTE")], sep_rows,
                "MEDIAN AND FULL RANGE OF FOMC PARTICIPANTS' PROJECTIONS (FRED REPUBLISHES THE LATEST SEP)"))
            sources.append("fred_csv")
        else:
            notes.append("FOMC SEP UNAVAILABLE FROM FRED")
        if not secs:
            raise DataError("unavailable", "NO FORECAST SOURCE ANSWERED: " + "; ".join(notes))
        notes.append("FORECASTS ARE THE SOURCES' OWN PROJECTIONS, SHOWN AS PUBLISHED; NOT OPENTERM'S")
        data = payload("ECFC", "ECFC ECONOMIC FORECASTS", [head("SOURCES", str(len(secs)), len(secs)), head("YEARS", " ".join(years))],
                       secs, notes, " + ".join(sources))
        return {"data": data, "source": " + ".join(sources), "fallback_from": []}

    return await svc.swr("md:ecfc", TTL["ecfc"], fetch)


# --- FOMC -----------------------------------------------------------------------------------------------------------------------

FED = "https://www.federalreserve.gov/monetarypolicy"


async def fomc(svc: Any) -> dict:
    async def fetch() -> dict:
        async def dates_fetch() -> dict:
            out, failed = await _call(svc, "fomc_dates", lambda p: p.fomc_dates())
            return {"data": out, "fallback_from": failed}

        dates = (await svc.swr("d:fomc", 86400.0, dates_fetch))["data"]
        today = _today().isoformat()
        past = [d for d in dates if d <= today]
        if len(past) < 2:
            raise DataError("not_found", "FEWER THAN TWO PAST FOMC MEETINGS ON THE CALENDAR")
        new_d, old_d = past[-1], past[-2]
        got = await asyncio.gather(*(_call(svc, "fomc_statement", lambda p, d=d: p.fomc_statement(d)) for d in (old_d, new_d)))
        old, new = got[0][0], got[1][0]
        diff = P.word_diff(old["paragraphs"], new["paragraphs"])
        changes = [r for r in diff if r["op"] != "SAME"]
        cal = []
        for d in dates[-16:]:
            ymd = d.replace("-", "")
            done = d <= today
            cal.append({"date": d, "status": "HELD" if done else "SCHEDULED", "statement": done,
                        "url": f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{ymd}a.htm" if done else f"{FED}/fomccalendars.htm",
                        "minutes": f"{FED}/fomcminutes{ymd}.htm" if done else None, "presser": f"{FED}/fomcpresconf{ymd}.htm" if done else None})
        sep = await _fred_many(svc, ["FEDTARMD", "FEDTARRH", "FEDTARRL"], "MAX")
        dots = []
        if isinstance(sep.get("FEDTARMD"), dict):
            hi = dict(_pairs(sep["FEDTARRH"])) if isinstance(sep.get("FEDTARRH"), dict) else {}
            lo = dict(_pairs(sep["FEDTARRL"])) if isinstance(sep.get("FEDTARRL"), dict) else {}
            for t, v in _pairs(sep["FEDTARMD"]):
                dots.append({"year": str(datetime.fromtimestamp(t, UTC).year), "median": v, "low": lo.get(t), "high": hi.get(t),
                             "spread": (hi[t] - lo[t]) if t in hi and t in lo else None})
        secs = [section("changes", f"STATEMENT CHANGES {old_d} -> {new_d}", [col("op", "CHANGE"), col("text", "WORDS")], changes,
                        "WORD-LEVEL DIFF OF THE TWO LATEST STATEMENTS (¶ = PARAGRAPH BREAK)"),
                section("statement", f"STATEMENT {new_d}", [col("n", "PARA", "int"), col("text", "TEXT")],
                        [{"n": i + 1, "text": t, "url": new["url"]} for i, t in enumerate(new["paragraphs"])]),
                section("calendar", "MEETINGS (ENTER OPENS THE STATEMENT)", [
                    col("date", "DECISION DAY", "date"), col("status", "STATUS"), col("minutes", "MINUTES"), col("presser", "PRESS CONFERENCE")], cal,
                    "MINUTES ARE PUBLISHED THREE WEEKS AFTER A MEETING; LINKS FOLLOW THE FED'S PAGE NAMES"),
                section("dots", "SEP FED FUNDS PROJECTIONS (THE DOTS)", [
                    col("year", "YEAR"), col("median", "MEDIAN %", "num"), col("low", "LOWEST DOT %", "num"), col("high", "HIGHEST DOT %", "num"),
                    col("spread", "SPREAD PTS", "num")], dots, "FROM FRED (FEDTARMD, FEDTARRH, FEDTARRL): MEDIAN AND RANGE OF THE PARTICIPANTS' DOTS")]
        nxt = next((d for d in dates if d > today), None)
        data = payload("FOMC", "FOMC STATEMENTS AND PROJECTIONS", [
            head("LATEST", new_d), head("NEXT", nxt), head("CHANGED PASSAGES", str(len(changes)), len(changes))], secs,
            ["SOURCES: federalreserve.gov (CALENDAR, STATEMENTS); FRED (SEP)"], f"{new['source']} + fomc + fred_csv")
        return {"data": data, "source": new["source"], "fallback_from": []}

    return await svc.swr("md:fomc", TTL["fomc"], fetch)


# --- WB, CRPR, RE (FRED boards) -------------------------------------------------------------------------------------------------


async def wb(svc: Any) -> dict:
    async def fetch() -> dict:
        ids = ["DGS2", "DGS10", *(B.wb_id(cc) for _, cc in B.WB_MONTHLY)]
        got = await _fred_many(svc, ids, "2Y")
        _all_failed(got)
        curves = await asyncio.gather(*(_call(svc, cap, lambda p, c=cap: getattr(p, c)()) for _, cap in B.WB_CURVES), return_exceptions=True)
        rows = []
        us10 = got["DGS10"]["last_value"] if isinstance(got.get("DGS10"), dict) else None
        for country, s2, s10 in B.WB_US:
            for tenor, sid in (("10Y", s10), ("2Y", s2)):
                rows.append({"country": country, "tenor": tenor, "source": f"FRED {sid}", **_row_from(got[sid], "rate", 7)})
        for (label, cap), res in zip(B.WB_CURVES, curves, strict=True):
            if isinstance(res, BaseException):
                if not isinstance(res, AllFailed):
                    raise res
                rows.append({"country": label, "tenor": "10Y", "note": redact(str(res))[:80]})
                continue
            cv = res[0]["curve"]
            for t in cv["tenors"]:
                if t["tenor"] not in ("2Y", "10Y"):
                    continue
                vals = [v for v in t["values"] if v is not None]
                if not vals:
                    continue
                wk = t["values"][-6] if len(t["values"]) >= 6 else None
                rows.append({"country": label, "tenor": t["tenor"], "last": vals[-1], "date": cv["dates"][-1], "freq": "DAILY",
                             "chg": (vals[-1] - wk) if wk is not None else None, "source": res[0]["source"]})
        for country, cc in B.WB_MONTHLY:
            rows.append({"country": country, "tenor": "10Y", "source": f"FRED {B.wb_id(cc)} (OECD)", **_row_from(got[B.wb_id(cc)], "rate", 28)})
        for r in rows:
            r["chg"] = r["chg"] * 100 if r.get("chg") is not None else None
            r["chg_1y"] = r["chg_1y"] * 100 if r.get("chg_1y") is not None else None
            r["vs_us"] = (r["last"] - us10) * 100 if r.get("last") is not None and us10 is not None and r["tenor"] == "10Y" else None
        sec = section("yields", "GOVERNMENT BOND YIELDS", [
            col("country", "COUNTRY"), col("tenor", "TENOR"), col("last", "YIELD %", "num4"), col("date", "DATE", "date"), col("freq", "FREQ"),
            col("chg", "CHG BP", "bp"), col("chg_1y", "1Y BP", "bp"), col("vs_us", "VS US 10Y BP", "bp"), col("source", "SOURCE"),
            col("note", "NOTE")], rows,
            "CHG = 1 WEEK FOR DAILY ROWS, 1 MONTH FOR MONTHLY ROWS. MONTHLY ROWS ARE MONTH AVERAGES (OECD MAIN ECONOMIC INDICATORS VIA FRED)")
        data = payload("WB", "WB WORLD BOND YIELDS", [head("US 10Y", f"{us10:.2f}%" if us10 is not None else None, us10),
                                                     head("ROWS", str(len(rows)), len(rows))], [sec],
                       ["2Y IS SHOWN WHERE A FREE DAILY SOURCE HAS IT (US, EURO AAA, JAPAN)",
                        "EURO AREA ROW IS THE ECB AAA SPOT CURVE, NOT A SINGLE COUNTRY'S BOND"], "fred_csv + ecb + boe + mof")
        return {"data": data, "source": "fred_csv + ecb + boe + mof", "fallback_from": []}

    return await svc.swr("md:wb", TTL["board"], fetch)


async def crpr(svc: Any) -> dict:
    async def fetch() -> dict:
        got = await _fred_many(svc, [c[0] for c in B.CRPR], "5Y")
        _all_failed(got)
        rows = []
        for sid, name, group in B.CRPR:
            d = got[sid]
            if isinstance(d, str):
                rows.append({"name": name, "group": group, "id": sid, "note": d})
                continue
            pts = [(t, v * 100) for t, v in _pairs(d)]  # FRED prints percent; spreads read in basis points
            vals = [v for _, v in pts]
            last = vals[-1]

            def chg(days: int, pts=pts, last=last) -> float | None:
                prev = value_before(pts, days)
                return last - prev if prev is not None else None

            rows.append({"name": name, "group": group, "id": sid, "oas": last, "date": d["last_date"], "chg_1w": chg(7), "chg_1m": chg(30),
                         "chg_1y": chg(365), "pctl": percentile(vals, last), "lo": min(vals), "hi": max(vals),
                         "since": datetime.fromtimestamp(pts[0][0], UTC).date().isoformat()})
        sec = section("oas", "OPTION-ADJUSTED SPREADS (ICE BOFA)", [
            col("name", "INDEX"), col("group", "GROUP"), col("oas", "OAS BP", "bp"), col("date", "DATE", "date"), col("chg_1w", "1W BP", "bp"),
            col("chg_1m", "1M BP", "bp"), col("chg_1y", "1Y BP", "bp"), col("pctl", "PCTL SINCE", "pct"), col("lo", "LOW BP", "bp"),
            col("hi", "HIGH BP", "bp"), col("since", "SINCE", "date"), col("note", "NOTE")], rows,
            "PERCENTILE, LOW AND HIGH ARE OVER THE HISTORY FRED SERVES (SINCE THE DATE SHOWN)")
        ig = next((r for r in rows if r["id"] == "BAMLC0A0CM" and r.get("oas") is not None), None)
        hy = next((r for r in rows if r["id"] == "BAMLH0A0HYM2" and r.get("oas") is not None), None)
        data = payload("CRPR", "CRPR CREDIT SPREADS", [head("US IG", f"{ig['oas']:.0f} BP" if ig else None), head("US HY", f"{hy['oas']:.0f} BP" if hy else None)],
                       [sec], ["FRED KEEPS ONLY THE LAST 3 YEARS OF THE ICE BOFA SERIES (ICE LICENCE, CHECKED 2026-11-24): LONGER HISTORY IS NOT AVAILABLE HERE",
                               "SOURCE: ICE DATA INDICES, LLC, VIA FRED (FEDERAL RESERVE BANK OF ST. LOUIS)"], "fred_csv")
        return {"data": data, "source": "fred_csv", "fallback_from": []}

    return await svc.swr("md:crpr", TTL["board"], fetch)


async def re_board(svc: Any) -> dict:
    async def fetch() -> dict:
        got = await _fred_many(svc, [r[0] for r in B.RE], "5Y")
        _all_failed(got)
        rows = []
        for sid, label, unit, kind, yoy in B.RE:
            r = {"name": label, "unit": unit, "id": sid, **_row_from(got[sid], kind, 30, yoy)}
            if kind == "rate" and r.get("chg") is not None:
                r["chg_pts"] = r["chg"]
            rows.append(r)
        sec = section("housing", "US HOUSING", [
            col("name", "SERIES"), col("last", "LAST", "num"), col("unit", "UNIT"), col("date", "DATE", "date"), col("freq", "FREQ"),
            col("chg_pct", "1M %", "pct"), col("chg_pts", "1M PTS", "num"), col("yoy", "Y/Y %", "pct"), col("id", "FRED ID"), col("note", "NOTE")], rows,
            "1M = CHANGE OVER ABOUT ONE MONTH (ONE PERIOD FOR MONTHLY SERIES); RATES CHANGE IN PERCENTAGE POINTS")
        data = payload("RE", "RE US HOUSING", [head("SERIES", str(len(rows)), len(rows))], [sec],
                       ["SOURCE: FRED (S&P COTALITY CASE-SHILLER, FHFA, US CENSUS BUREAU, FREDDIE MAC)",
                        "ZILLOW RESEARCH DATA: NOT USED (ITS TERMS WERE NOT CHECKED AS ALLOWING REUSE IN AN OPEN-SOURCE APP)"], "fred_csv")
        return {"data": data, "source": "fred_csv", "fallback_from": []}

    return await svc.swr("md:re", TTL["board"], fetch)


# --- FWCV -----------------------------------------------------------------------------------------------------------------------


async def fwcv(svc: Any) -> dict:
    env = await svc.rates()
    c = env["data"]
    try:
        zc = K.bootstrap(c["years"], c["yields"])
    except ValueError as e:
        raise DataError("unavailable", str(e)) from e
    fw = K.forward_table(zc)
    for r in fw:
        r["vs_spot"] = (r["rate"] - r["spot_end"]) * 100 if r["rate"] is not None and r["spot_end"] is not None else None
    one = K.one_year_forwards(zc)
    curve_rows = [{"t": p["t"], "par": p["par"], "zero": p["zero"], "df": p["df"]} for p in zc if p["t"] in (0.5, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30)]
    secs = [section("fwd", "FORWARD RATES", [col("name", "FORWARD"), col("start", "START Y", "num"), col("end", "END Y", "num"),
                                             col("rate", "FORWARD %", "num4"), col("spot_end", "SPOT TO END %", "num4"), col("vs_spot", "FWD - SPOT BP", "bp")], fw,
                    "1Y2Y = THE 2-YEAR RATE STARTING IN 1 YEAR. SEMIANNUAL COMPOUNDING (TREASURY CONVENTION)"),
            section("zero", "BOOTSTRAPPED ZERO CURVE", [col("t", "YEARS", "num"), col("par", "PAR %", "num4"), col("zero", "ZERO %", "num4"),
                                                        col("df", "DISCOUNT FACTOR", "num4")], curve_rows)]
    charts = [{"id": "curves", "title": f"US TREASURY {c['date']}: PAR, ZERO, 1Y FORWARD", "xlabel": "YEARS", "ylabel": "%", "series": [
        {"name": "PAR", "points": [[p["t"], p["par"]] for p in zc]}, {"name": "ZERO", "points": [[p["t"], p["zero"]] for p in zc]},
        {"name": "1Y FORWARD", "points": [[s + 0.5, f] for s, f in one], "dash": True}]}]
    f55 = next((r for r in fw if r["name"] == "5y5y"), None)
    data = payload("FWCV", "FWCV FORWARD CURVE", [head("CURVE DATE", c["date"]), head("5Y5Y", f"{f55['rate']:.2f}%" if f55 and f55["rate"] else None)],
                   secs, ["BOOTSTRAPPED FROM THE TREASURY PAR CURVE WITH LINEAR INTERPOLATION BETWEEN QUOTED TENORS: FORWARDS KINK AT THE TENORS",
                          "A FORWARD RATE IS WHAT TODAY'S CURVE LOCKS IN, NOT A FORECAST (IT INCLUDES TERM PREMIUM)"], env.get("source"), charts=charts)
    return {**env, "data": data}


# --- BTMM -----------------------------------------------------------------------------------------------------------------------


async def btmm(svc: Any, country: str) -> dict:
    cc = (country or "US").upper()
    if cc not in B.BTMM:
        raise DataError("bad_request", f"COUNTRY: {' '.join(B.BTMM)}")
    spec = B.BTMM[cc]

    async def fetch() -> dict:
        ids = [v for k, v in spec.items() if k in {f[0] for f in B.BTMM_FIELDS} and v and ":" not in v]
        got = await _fred_many(svc, ids, "2Y")
        _all_failed(got)
        rows = []
        for field, label, kind, yoy in B.BTMM_FIELDS:
            sid = spec.get(field)
            name = f"{label} ({spec['fx_label']})" if field == "fx" else f"{label} ({spec['gdp_label']})" if field == "gdp" else label
            if not sid:
                q = B.BTMM_INDEX_QUOTES.get(cc) if field == "index" else None
                if q:
                    rows.append(await _quote_row(svc, name, q))
                else:
                    rows.append({"field": name, "note": "NO FREE KEYLESS SERIES WIRED FOR THIS COUNTRY"})
                continue
            if sid.startswith(("curve:", "policy:")):
                rows.append({"field": name, **await _daily_row(svc, sid)})
                continue
            r = _row_from(got[sid], kind, 30, yoy)
            if yoy:
                r["last"], r["chg"] = (r.get("yoy") * 100 if r.get("yoy") is not None else None), None
            if kind == "rate" and r.get("chg") is not None:
                r["chg"] = r["chg"] * 100
            rows.append({"field": name, "id": sid, **r})
        releases = await _next_releases(svc) if cc == "US" else []
        secs = [section("monitor", f"{spec['name']} MONITOR", [
            col("field", "ITEM"), col("last", "LAST", "num"), col("date", "DATE", "date"), col("freq", "FREQ"), col("chg", "1M CHG BP", "bp"),
            col("chg_pct", "1M %", "pct"), col("id", "SOURCE ID"), col("note", "NOTE")], rows,
            "RATES CHANGE IN BASIS POINTS, LEVELS IN PERCENT. CPI ROW = YEAR-ON-YEAR % OF THE INDEX")]
        notes = ["SOURCES: FRED (FEDERAL RESERVE, OECD, NATIONAL STATISTICS); INDEX QUOTES THROUGH THE NORMAL QUOTE CHAIN"]
        if releases:
            secs.append(section("next", "NEXT US RELEASES (ECO)", [col("date", "DATE", "date"), col("time", "TIME"), col("event", "RELEASE"),
                                                                   col("agency", "AGENCY")], releases))
        elif cc != "US":
            notes.append(f"NEXT RELEASES: ONLY THE US CALENDAR (BLS, BEA) IS WIRED; NO FREE CALENDAR FOR {spec['name']}")
        data = payload(f"BTMM {cc}", f"BTMM {spec['name']}", [head("COUNTRY", spec["name"]), head("ITEMS", str(len(rows)))], secs, notes, "fred_csv")
        return {"data": data, "source": "fred_csv", "fallback_from": []}

    return await svc.swr(f"md:btmm:{cc}", TTL["board"], fetch)


async def _daily_row(svc: Any, ref: str) -> dict:
    """A BTMM row from a RATES curve ("curve:curve_eur:10Y") or CENB's policy-rate source ("policy:BOE")."""
    kind, _, rest = ref.partition(":")
    try:
        if kind == "policy":
            out, _ = await _call(svc, "policy_rates", lambda p: p.policy_rates())
            one = out.get(rest) or {}
            if one.get("rate") is None:
                return {"id": f"{rest} POLICY RATE", "note": redact(str(one.get("error") or "NO VALUE"))[:60]}
            return {"id": f"{rest} POLICY RATE", "last": one["rate"], "date": one.get("as_of"), "freq": "DAILY"}
        cap, _, tenor = rest.partition(":")
        out, _ = await _call(svc, cap, lambda p: getattr(p, cap)())
        cv = out["curve"]
        t = next((x for x in cv["tenors"] if x["tenor"] == tenor), None)
        vals = [v for v in (t or {}).get("values", []) if v is not None]
        if not vals:
            return {"id": f"{out['source']} {tenor}", "note": f"NO {tenor} ON THE CURVE"}
        wk = t["values"][-21] if len(t["values"]) >= 21 and t["values"][-21] is not None else None
        return {"id": f"{out['source']} {tenor}", "last": vals[-1], "date": cv["dates"][-1], "freq": "DAILY",
                "chg": (vals[-1] - wk) * 100 if wk is not None else None}
    except AllFailed as e:
        return {"id": ref, "note": redact(str(e))[:60]}


async def _quote_row(svc: Any, name: str, symbol: str) -> dict:
    """A BTMM row from the normal quote chain. `svc.quotes` answers {symbol: envelope | {"error", "kind"}} and never raises for one symbol."""
    got = (await svc.quotes([symbol])).get(symbol) or {}
    q = got.get("data")
    q = q.model_dump() if hasattr(q, "model_dump") else q
    if not isinstance(q, dict) or q.get("price") is None:
        return {"field": name, "id": symbol, "note": redact(str(got.get("error") or "NO QUOTE"))[:60]}
    pct = q.get("change_pct")
    return {"field": name, "id": symbol, "last": q["price"], "chg_pct": pct / 100 if pct is not None else None,
            "freq": "QUOTE", "note": "CHANGE = TODAY"}


async def _next_releases(svc: Any) -> list[dict]:
    try:
        env = await svc.eco(None, 14)
    except (DataError, AllFailed):
        return []
    rows = env.get("data", {}).get("events") if isinstance(env.get("data"), dict) else env.get("data")
    out = []
    for e in (rows or [])[:12]:
        e = e if isinstance(e, dict) else e.model_dump()
        out.append({"date": e.get("date"), "time": e.get("time"), "event": e.get("event") or e.get("title"), "agency": e.get("agency") or e.get("source")})
    return out


# --- WCRS -----------------------------------------------------------------------------------------------------------------------


def rank_returns(rows: list[dict], today: date) -> dict[str, list[dict]]:
    """Frankfurter rows {date, quote, rate (units of quote per USD)} -> per base (USD, INR) a list of {ccy, <period>: return}.
    A currency's return vs USD over a period = rate_then / rate_now - 1 (fewer units per dollar now = the currency gained)."""
    by_ccy: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        if isinstance(r.get("rate"), (int, float)):
            by_ccy.setdefault(r["quote"], []).append((r["date"], float(r["rate"])))
    for v in by_ccy.values():
        v.sort()
    by_ccy["USD"] = [(d, 1.0) for d, _ in by_ccy.get("EUR", [])]

    def at(series: list[tuple[str, float]], day: str) -> float | None:
        best = None
        for d, x in series:
            if d <= day:
                best = x
            else:
                break
        return best

    out: dict[str, list[dict]] = {"USD": [], "INR": []}
    starts = {p: (date(today.year, 1, 1) - timedelta(days=1) if n == 0 else today - timedelta(days=n)).isoformat() for p, n in B.WCRS_PERIODS}
    inr = by_ccy.get("INR", [])
    for ccy, s in sorted(by_ccy.items()):
        if not s:
            continue
        last_d, last = s[-1]
        row_usd = {"ccy": ccy, "last": 1 / last if ccy != "USD" else 1.0, "date": last_d}
        row_inr = {"ccy": ccy, "date": last_d}
        inr_last = at(inr, last_d)
        row_inr["last"] = inr_last / last if inr_last else None
        for p, day in starts.items():
            then = at(s, day)
            row_usd[p] = (then / last - 1) if then and ccy != "USD" else None
            inr_then = at(inr, day)
            row_inr[p] = ((inr_last / last) / (inr_then / then) - 1) if then and inr_then and inr_last and ccy != "INR" else None
        if ccy != "USD":
            out["USD"].append(row_usd)
        if ccy != "INR":
            out["INR"].append(row_inr)
    return out


async def wcrs(svc: Any, sort: str) -> dict:
    period = (sort or "1M").upper()
    if period not in dict(B.WCRS_PERIODS):
        raise DataError("bad_request", f"SORT: {' '.join(p for p, _ in B.WCRS_PERIODS)}")

    async def fetch() -> dict:
        start = _today() - timedelta(days=370)
        out, failed = await _call(svc, "fx_panel", lambda p: p.fx_panel(start, list(B.WCRS_CCYS)))
        return {"data": out["rows"], "source": out["source"], "fallback_from": failed}

    env = await svc.swr("md:wcrs", TTL["wcrs"], fetch)
    ranked = rank_returns(env["data"], _today())
    cols = [col("rank", "#", "int"), col("ccy", "CCY"), col("last", "LAST", "num4")] + [col(p, p, "pct") for p, _ in B.WCRS_PERIODS] + [col("date", "FIX DATE", "date")]
    secs = []
    for base, label in (("USD", "VS US DOLLAR (USD PER UNIT)"), ("INR", "VS INDIAN RUPEE (INR PER UNIT)")):
        rows = sorted(ranked[base], key=lambda r: (r.get(period) is None, -(r.get(period) or 0)))
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        secs.append(section(base.lower(), f"RANKED {label}, BY {period}", cols, rows,
                            "POSITIVE = THE CURRENCY GAINED AGAINST THE BASE. ECB REFERENCE RATES (ONE FIX A DAY, ~16:00 CET)"))
    data = payload("WCRS", "WCRS CURRENCY RANKS", [head("SORT", period), head("CURRENCIES", str(len(ranked["USD"])))], secs,
                   ["CROSSES VS INR ARE COMPUTED FROM THE USD FIXES (INR/USD / CCY/USD)", "SOURCE: ECB REFERENCE RATES VIA FRANKFURTER"], env.get("source"))
    return {**env, "data": data}


# --- CTM, CDR (no network apart from the existing holiday calendar) -------------------------------------------------------------


def ctm(root: str) -> dict:
    r = (root or "CL").upper()
    today = _today()
    try:
        rows = C.contracts(r, today)
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e
    for row in rows:
        row["go_fn"], row["go_args"] = "CT", [r]
    rule = C.RULES[r][3]
    roots = [{"root": k, "name": C.fp.ROOTS[k][4], "settle": v[2], "rule": v[3], "go_fn": "CTM", "go_args": [k]} for k, v in C.RULES.items()]
    secs = [section("contracts", f"{r} CONTRACTS ({C.fp.ROOTS[r][4]})", [
        col("contract", "CONTRACT"), col("month", "MONTH"), col("last_trade", "LAST TRADE", "date"), col("days_left", "DAYS", "int"),
        col("first_notice", "FIRST NOTICE", "date"), col("notice_days_left", "DAYS TO FN", "int"), col("settle", "SETTLE")], rows, rule),
        section("roots", "ROOTS (ENTER OPENS ONE)", [col("root", "ROOT"), col("name", "NAME"), col("settle", "SETTLE"), col("rule", "RULE")], roots)]
    nxt = rows[0] if rows else None
    data = payload(f"CTM {r}", f"CTM {r} CONTRACT TABLE", [head("FRONT", nxt["contract"] if nxt else None),
                                                          head("LAST TRADE", nxt["last_trade"] if nxt else None)], secs,
                   ["DATES ESTIMATED FROM THE EXCHANGE'S RULE AND THE NYSE HOLIDAY CALENDAR: THE EXCHANGE'S OWN CALENDAR IS THE AUTHORITY",
                    "ENTER ON A CONTRACT OPENS CT FOR THE ROOT"], "rules (CME Group contract specifications)")
    return _local(data, "rules")


async def cdr(svc: Any, year: int | None) -> dict:
    from ..world.holidays import MARKETS, calendar

    today = _today()
    yr = year or today.year
    hours = [{"market": k, "name": v[0], "tz": v[1], "sessions": "  ".join(v[2]), "weekend": "SAT SUN"} for k, v in C.HOURS.items()]
    rows, notes, sources = [], [], []
    for mkt in MARKETS:
        for y in (yr, yr + 1) if year is None else (yr,):
            try:
                env = await calendar(svc, mkt, y)
            except (DataError, AllFailed) as e:
                notes.append(f"{mkt} {y}: NOT LOADED ({getattr(e, 'kind', 'error').upper()})")
                continue
            d = env["data"]
            sources.append(d.get("source", ""))
            for h in d["holidays"]:
                rows.append({"date": h["date"], "market": mkt, "what": "CLOSED", "name": h["name"], "basis": d["label"]})
            for h in d.get("early", []):
                rows.append({"date": h["date"], "market": mkt, "what": "EARLY CLOSE 13:00", "name": h["name"], "basis": d["label"]})
    if year is None:
        rows = [r for r in rows if r["date"] >= today.isoformat() and r["date"] <= (today + timedelta(days=365)).isoformat()]
    rows.sort(key=lambda r: (r["date"], r["market"]))
    for r in rows:
        r["days_away"] = (date.fromisoformat(r["date"]) - today).days
    secs = [section("closures", "CLOSURES AND EARLY CLOSES" + (f" {yr}" if year else " (NEXT 12 MONTHS)"), [
        col("date", "DATE", "date"), col("days_away", "DAYS", "int"), col("market", "MKT"), col("what", "WHAT"), col("name", "NAME"), col("basis", "BASIS")], rows),
        section("hours", "REGULAR HOURS (LOCAL TIME)", [col("market", "MKT"), col("name", "EXCHANGE"), col("tz", "TIME ZONE"),
                                                        col("sessions", "SESSIONS"), col("weekend", "CLOSED")], hours,
                "THE SAME TABLE THE MARKET LIGHTS USE. NO PRE / POST-MARKET OR AUCTION PERIODS")]
    nxt = rows[0] if rows else None
    data = payload("CDR", "CDR EXCHANGE CALENDAR", [head("NEXT", f"{nxt['market']} {nxt['date']} {nxt['name']}" if nxt else None)], secs,
                   notes + ["NY: NYSE RULES (CHECKED 2024-2027). IN: FIXED-DATE HOLIDAYS + GOOD FRIDAY ONLY (FESTIVALS MISSING). LN / TK / HK: PUBLIC HOLIDAYS (EXCHANGE MAY DIFFER)"],
                   " + ".join(sorted(set(sources))))
    return _local(data, "holiday rules + nager")


# --- TSYS -----------------------------------------------------------------------------------------------------------------------

TSY_TYPES = ("BILL", "NOTE", "BOND", "TIPS", "FRN", "CMB")


async def tsys(svc: Any, kind: str) -> dict:
    k = (kind or "").upper()
    if k and k not in TSY_TYPES:
        raise DataError("bad_request", f"TYPE: {' '.join(TSY_TYPES)}")

    async def fetch() -> dict:
        out, failed = await _call(svc, "tsy_securities", lambda p: p.tsy_securities(90))
        return {"data": out, "source": out["source"], "fallback_from": failed}

    env = await svc.swr("md:tsys", TTL["tsys"], fetch)
    d = env["data"]

    def keep(r: dict) -> bool:
        if not k:
            return True
        t = (r.get("securityType") or "").upper()
        if k == "TIPS":
            return "TIPS" in (r.get("type") or "").upper() or "TIPS" in (r.get("securityTerm") or "").upper()
        if k == "FRN":
            return "FRN" in (r.get("type") or "").upper()
        if k == "CMB":
            return "CMB" in (r.get("type") or "").upper() or "CASH MANAGEMENT" in (r.get("type") or "").upper()
        return t == k

    def row(r: dict) -> dict:
        y = r.get("highYield") or r.get("highInvestmentRate")
        out = {"cusip": r["cusip"], "type": r.get("type") or r.get("securityType"), "term": r.get("securityTerm"), "auction": r.get("auctionDate"),
               "issue": r.get("issueDate"), "maturity": r.get("maturityDate"), "coupon": r.get("interestRate"), "yield": y,
               "discount": r.get("highDiscountRate"), "btc": r.get("bidToCoverRatio"), "offer": r.get("offeringAmount")}
        if r.get("maturityDate") and y is not None:
            out["go_fn"] = "YAS"
            out["go_args"] = [f"CPN={r.get('interestRate') or 0}", f"MAT={r['maturityDate']}", f"YLD={y}"]
        return out

    done = [row(r) for r in d["auctioned"] if keep(r)]
    done.sort(key=lambda r: r["auction"] or "", reverse=True)
    up = [row(r) for r in d["upcoming"] if keep(r)]
    up.sort(key=lambda r: r["auction"] or "")
    cols = [col("cusip", "CUSIP"), col("type", "TYPE"), col("term", "TERM"), col("auction", "AUCTION", "date"), col("issue", "ISSUE", "date"),
            col("maturity", "MATURITY", "date"), col("coupon", "COUPON %", "num4"), col("yield", "HIGH YIELD %", "num4"), col("discount", "DISC RATE %", "num4"),
            col("btc", "BID/COVER", "num"), col("offer", "OFFERING", "money")]
    secs = [section("auctioned", f"AUCTIONED, LAST 90 DAYS{' ' + k if k else ''}", cols, done, "ENTER OPENS YAS WITH THE COUPON, MATURITY AND AUCTION HIGH YIELD"),
            section("upcoming", "ANNOUNCED UPCOMING AUCTIONS", cols, up)]
    data = payload("TSYS", "TSYS US TREASURY SECURITIES", [head("AUCTIONED", str(len(done))), head("UPCOMING", str(len(up)))], secs,
                   ["SOURCE: TREASURYDIRECT SECURITIES API (BUREAU OF THE FISCAL SERVICE). BILLS: DISCOUNT RATE AND INVESTMENT RATE, NO COUPON"], env.get("source"))
    return {**env, "data": data}


# --- NRGF -----------------------------------------------------------------------------------------------------------------------


async def nrgf(svc: Any) -> dict:
    async def fetch() -> dict:
        got = await asyncio.gather(*(_call(svc, "eia_series", lambda p, s=s: p.eia_series(s)) for s, _, _ in B.NRGF), return_exceptions=True)
        if all(isinstance(g, AllFailed) and g.kind == KEY_REQUIRED for g in got):
            data = payload("NRGF", "NRGF ENERGY FUNDAMENTALS", [], [], ["KEY REQUIRED: set EIA_API_KEY in APIKEYS (FREE: eia.gov/opendata)"],
                           "eia", key_required=[{"key": "EIA_API_KEY", "what": "EIA weekly petroleum status and gas storage (free)"}])
            return {"data": data, "source": "eia", "fallback_from": []}
        rows, source = [], "eia"
        for (sid, label, unit), g in zip(B.NRGF, got, strict=True):
            if isinstance(g, AllFailed):
                rows.append({"name": label, "unit": unit, "id": sid, "note": redact(str(g))[:70]})
                continue
            if isinstance(g, BaseException):
                raise g
            out = g[0]
            source = out["source"]
            pts = out["points"]
            vals = [v for _, v in pts]
            last = vals[0]
            rows.append({"name": label, "unit": unit, "id": sid, "last": last, "date": pts[0][0],
                         "chg_w": last - vals[1] if len(vals) > 1 else None, "chg_y": last - vals[52] if len(vals) > 52 else None,
                         "pctl": percentile(vals, last), "lo": min(vals), "hi": max(vals)})
        if all("note" in r for r in rows):
            raise DataError("unavailable", "NO EIA SERIES ANSWERED: " + rows[0]["note"])
        sec = section("wpsr", "WEEKLY PETROLEUM STATUS AND GAS STORAGE", [
            col("name", "SERIES"), col("last", "LAST", "num"), col("unit", "UNIT"), col("date", "WEEK", "date"), col("chg_w", "W/W", "num"),
            col("chg_y", "VS YEAR AGO", "num"), col("pctl", "2Y PCTL", "pct"), col("lo", "2Y LOW", "num"), col("hi", "2Y HIGH", "num"),
            col("note", "NOTE")], rows, "STOCKS IN THOUSAND BARRELS; GAS STORAGE IN BILLION CUBIC FEET. PERCENTILE OVER THE LAST 104 WEEKS")
        data = payload("NRGF", "NRGF ENERGY FUNDAMENTALS", [head("SERIES", str(len(rows)))], [sec],
                       ["SOURCE: US ENERGY INFORMATION ADMINISTRATION (WEEKLY PETROLEUM STATUS REPORT, WEEKLY NATURAL GAS STORAGE REPORT)"], source)
        return {"data": data, "source": source, "fallback_from": []}

    return await svc.swr("md:nrgf", TTL["nrgf"], fetch)


# --- AGRI -----------------------------------------------------------------------------------------------------------------------


async def agri(svc: Any) -> dict:
    async def fetch() -> dict:
        out, failed = await _call(svc, "wasde", lambda p: p.wasde())
        secs, notes, key_required = [], [], []
        for t in out["tables"]:
            cols = [col("item", "ITEM")] + [col(f"c{i}", c[:18], "num") for i, c in enumerate(t["columns"])]
            rows = [{"item": r["item"], **{f"c{i}": r["values"].get(c) for i, c in enumerate(t["columns"])}} for r in t["rows"]]
            secs.append(section(t["label"].lower().replace(" ", "_"), f"{t['label']} SUPPLY AND USE ({out['month']})", cols, rows, t["title"]))
        files = [{"month": r["mmyy"], "xml": r.get("xml"), "url": r.get("txt") or r.get("xml")} for r in out["links"]]
        secs.append(section("files", "WASDE RELEASES (ENTER OPENS THE TEXT FILE)", [col("month", "MMYY"), col("xml", "XML")], files))
        source = out["source"]
        year = _today().year if _today().month >= 4 else _today().year - 1
        cond = await asyncio.gather(*(_call(svc, "nass_crop", lambda p, c=c: p.nass_crop(c, year)) for c in B.AGRI_CROPS), return_exceptions=True)
        if all(isinstance(c, AllFailed) and c.kind == KEY_REQUIRED for c in cond):
            notes.append("KEY REQUIRED: set NASS_API_KEY in APIKEYS (CROP CONDITION NOT LOADED; THE WASDE TABLES NEED NO KEY)")
            key_required = [{"key": "NASS_API_KEY", "what": "USDA NASS weekly crop condition (free)"}]
        else:
            rows = []
            for crop, c in zip(B.AGRI_CROPS, cond, strict=True):
                if isinstance(c, BaseException):
                    if not isinstance(c, AllFailed):
                        raise c
                    rows.append({"crop": crop, "note": redact(str(c))[:70]})
                    continue
                source += f" + {c[0]['source']}"
                weeks = sorted({r["week_ending"] for r in c[0]["rows"] if r["week_ending"]}, reverse=True)
                for w in weeks[:2]:
                    vals = {r["unit"].replace("PCT ", ""): r["value"] for r in c[0]["rows"] if r["week_ending"] == w}
                    ge = (vals.get("GOOD") or 0) + (vals.get("EXCELLENT") or 0) if vals.get("GOOD") is not None else None
                    rows.append({"crop": crop, "week": w, "ve": vals.get("EXCELLENT"), "g": vals.get("GOOD"), "f": vals.get("FAIR"), "p": vals.get("POOR"),
                                 "vp": vals.get("VERY POOR"), "ge": ge})
            secs.insert(0, section("condition", f"US CROP CONDITION {year} (% OF ACREAGE)", [
                col("crop", "CROP"), col("week", "WEEK ENDING", "date"), col("ge", "GOOD+EXC", "num"), col("ve", "EXCELLENT", "num"), col("g", "GOOD", "num"),
                col("f", "FAIR", "num"), col("p", "POOR", "num"), col("vp", "VERY POOR", "num"), col("note", "NOTE")], rows,
                "USDA NASS CROP PROGRESS (WEEKLY, IN SEASON ONLY)"))
        notes.append("WASDE: USDA WORLD AGRICULTURAL OUTLOOK BOARD, READ FROM THE CORNELL MANN LIBRARY ARCHIVE COPY")
        data = payload("AGRI", "AGRI CROPS: WASDE AND CONDITION", [head("WASDE", out["month"])], secs, notes, source, key_required=key_required)
        return {"data": data, "source": source, "fallback_from": failed}

    return await svc.swr("md:agri", TTL["agri"], fetch)


# --- WPE ------------------------------------------------------------------------------------------------------------------------


async def wpe(svc: Any) -> dict:
    async def fetch() -> dict:
        got = await asyncio.gather(*(_call(svc, "etf_valuation", lambda p, s=s: p.etf_valuation(s)) for _, s in B.WPE_ETFS), return_exceptions=True)
        rows = []
        for (region, etf), g in zip(B.WPE_ETFS, got, strict=True):
            if isinstance(g, AllFailed):
                rows.append({"region": region, "proxy": f"PROXY: {etf}", "note": redact(str(g))[:60]})
                continue
            if isinstance(g, BaseException):
                raise g
            v = g[0]
            rows.append({"region": region, "proxy": f"PROXY: {etf}", "pe": v["pe"], "pb": v["pb"], "ps": v["ps"], "yield": v["yield"],
                         "price": v["price"], "basis": "HOLDINGS" if v["pe_source"] == "holdings" else "FUND", "go_fn": "DES", "go_sym": etf})
        if all("note" in r for r in rows):
            raise DataError("unavailable", "NO ETF VALUATION ANSWERED: " + rows[0]["note"])
        sec = section("valuation", "INDEX VALUATION THROUGH INDEX ETFS", [
            col("region", "MARKET"), col("proxy", "PROXY"), col("pe", "P/E", "num"), col("pb", "P/B", "num"), col("ps", "P/S", "num"),
            col("yield", "YIELD", "pct"), col("price", "ETF PRICE", "price"), col("basis", "P/E BASIS"), col("note", "NOTE")], rows,
            "EVERY ROW IS AN ETF PROXY FOR THE INDEX, NOT THE INDEX ITSELF. P/E BASIS: HOLDINGS = WEIGHTED HOLDINGS' P/E, FUND = THE FUND'S TRAILING P/E")
        data = payload("WPE", "WPE WORLD INDEX VALUATION (ETF PROXIES)", [head("MARKETS", str(len(rows)))], [sec],
                       ["VALUES AS YAHOO FINANCE REPORTS THEM FOR EACH FUND (UNOFFICIAL; FUND DATA UPDATES SLOWLY)"], "yahoo_funds")
        return {"data": data, "source": "yahoo_funds", "fallback_from": []}

    return await svc.swr("md:wpe", TTL["wpe"], fetch)
