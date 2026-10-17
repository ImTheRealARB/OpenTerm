"""Pure parsers: Yahoo quoteSummary modules -> table payloads (EE, EEO, ANR, MGMT) and small shared extracts.

No I/O. Yahoo wraps most numbers as {"raw": n, "fmt": "..."}; `_raw` unwraps them. An empty wrapper ({}) is None.
"""

from __future__ import annotations

from typing import Any

from ..providers.base import ProviderError
from ..providers.yahoo import _raw
from .table import col, head, iso_date, payload, section

PERIODS = {"0q": "CURRENT QTR", "+1q": "NEXT QTR", "0y": "CURRENT YEAR", "+1y": "NEXT YEAR"}


def _module(result: dict, name: str) -> dict:
    m = result.get(name)
    if not m:
        raise ProviderError("not_found", f"no {name}")
    return m


def _trend(result: dict) -> list[dict]:
    rows = [t for t in _module(result, "earningsTrend").get("trend") or [] if t.get("period") in PERIODS]
    if not rows:
        raise ProviderError("not_found", "no estimates")
    return rows


def estimates(symbol: str, result: dict, source: str) -> dict:
    """EE. EPS and revenue consensus for the four forward periods."""
    eps_rows, rev_rows = [], []
    for t in _trend(result):
        e, r = t.get("earningsEstimate") or {}, t.get("revenueEstimate") or {}
        label, end = PERIODS[t["period"]], t.get("endDate")
        eps_rows.append({"period": label, "end": end, "avg": _raw(e, "avg"), "low": _raw(e, "low"),
                         "high": _raw(e, "high"), "analysts": _raw(e, "numberOfAnalysts"),
                         "year_ago": _raw(e, "yearAgoEps"), "growth": _raw(e, "growth")})
        rev_rows.append({"period": label, "end": end, "avg": _raw(r, "avg"), "low": _raw(r, "low"),
                         "high": _raw(r, "high"), "analysts": _raw(r, "numberOfAnalysts"),
                         "year_ago": _raw(r, "yearAgoRevenue"), "growth": _raw(r, "growth")})
    cur = (_trend(result)[0].get("earningsEstimate") or {}).get("earningsCurrency")
    common = [col("period", "PERIOD", "text", 14), col("end", "ENDS", "date", 10)]
    tail = [col("analysts", "ANALYSTS", "int", 9), col("growth", "GROWTH", "pct", 8)]
    return payload(
        symbol, f"EE {symbol} · ESTIMATES",
        [head("CURRENCY", cur), head("METHOD", str(_module(result, "earningsTrend").get("defaultMethodology") or "").upper() or None)],
        [section("eps", "EPS CONSENSUS",
                 [*common, col("avg", "AVG", "num"), col("low", "LOW", "num"), col("high", "HIGH", "num"),
                  col("year_ago", "YEAR AGO", "num"), *tail], eps_rows),
         section("revenue", "REVENUE CONSENSUS",
                 [*common, col("avg", "AVG", "money"), col("low", "LOW", "money"), col("high", "HIGH", "money"),
                  col("year_ago", "YEAR AGO", "money"), *tail], rev_rows)],
        ["CONSENSUS FROM YAHOO FINANCE (UNOFFICIAL); ANALYST COUNT IS PER PERIOD"], source)


def revisions_and_surprises(symbol: str, result: dict, source: str) -> dict:
    """EEO. How the EPS estimate moved, who revised it, and what the last four quarters did against it."""
    trend_rows, rev_rows = [], []
    for t in _trend(result):
        label = PERIODS[t["period"]]
        tr, rv = t.get("epsTrend") or {}, t.get("epsRevisions") or {}
        trend_rows.append({"period": label, "now": _raw(tr, "current"), "d7": _raw(tr, "7daysAgo"),
                           "d30": _raw(tr, "30daysAgo"), "d60": _raw(tr, "60daysAgo"), "d90": _raw(tr, "90daysAgo")})
        rev_rows.append({"period": label, "up7": _raw(rv, "upLast7days"), "up30": _raw(rv, "upLast30days"),
                         "down7": _raw(rv, "downLast7Days"), "down30": _raw(rv, "downLast30days"),
                         "down90": _raw(rv, "downLast90days")})
    sur_rows = []
    for h in (result.get("earningsHistory") or {}).get("history") or []:
        q = (h.get("quarter") or {}).get("fmt")
        sur_rows.append({"quarter": q, "actual": _raw(h, "epsActual"), "estimate": _raw(h, "epsEstimate"),
                         "diff": _raw(h, "epsDifference"), "surprise": _raw(h, "surprisePercent")})
    sur_rows.sort(key=lambda r: r["quarter"] or "", reverse=True)
    beats = sum(1 for r in sur_rows if (r["diff"] or 0) > 0)
    return payload(
        symbol, f"EEO {symbol} · REVISIONS AND SURPRISES",
        [head("BEATS IN LAST QUARTERS", f"{beats} OF {len(sur_rows)}" if sur_rows else None, beats if sur_rows else None)],
        [section("trend", "EPS ESTIMATE TREND",
                 [col("period", "PERIOD", "text", 14), col("now", "NOW", "num"), col("d7", "7D AGO", "num"),
                  col("d30", "30D AGO", "num"), col("d60", "60D AGO", "num"), col("d90", "90D AGO", "num")], trend_rows),
         section("revisions", "ANALYST REVISIONS",
                 [col("period", "PERIOD", "text", 14), col("up7", "UP 7D", "int"), col("up30", "UP 30D", "int"),
                  col("down7", "DOWN 7D", "int"), col("down30", "DOWN 30D", "int"), col("down90", "DOWN 90D", "int")],
                 rev_rows),
         section("surprises", "EPS SURPRISES",
                 [col("quarter", "QUARTER", "date", 10), col("actual", "ACTUAL", "num"), col("estimate", "ESTIMATE", "num"),
                  col("diff", "DIFF", "num"), col("surprise", "SURPRISE", "pct")], sur_rows)],
        ["UP/DOWN = ANALYSTS WHO RAISED/LOWERED THE CURRENT-PERIOD EPS ESTIMATE IN THE WINDOW"], source)


def ratings(symbol: str, result: dict, source: str) -> dict:
    """ANR. Recommendation mix, price targets and the latest rating changes."""
    fd = result.get("financialData") or {}
    trend = (result.get("recommendationTrend") or {}).get("trend") or []
    hist = (result.get("upgradeDowngradeHistory") or {}).get("history") or []
    if not fd and not trend and not hist:
        raise ProviderError("not_found", "no analyst data")
    price, mean_t = _raw(fd, "currentPrice"), _raw(fd, "targetMeanPrice")
    upside = mean_t / price - 1 if price and mean_t else None

    def pct(v: float | None) -> str | None:
        return f"{v * 100:+.1f}%" if v is not None else None

    def num(v: Any) -> str | None:
        return f"{v:,.2f}" if isinstance(v, (int, float)) else None

    headline = [
        head("CONSENSUS", str(fd.get("recommendationKey") or "").upper() or None),
        head("MEAN RATING", num(_raw(fd, "recommendationMean")), _raw(fd, "recommendationMean")),
        head("ANALYSTS", str(_raw(fd, "numberOfAnalystOpinions")) if _raw(fd, "numberOfAnalystOpinions") else None,
             _raw(fd, "numberOfAnalystOpinions")),
        head("PRICE", num(price), price),
        head("TARGET MEAN", num(mean_t), mean_t),
        head("TARGET MEDIAN", num(_raw(fd, "targetMedianPrice")), _raw(fd, "targetMedianPrice")),
        head("TARGET HIGH", num(_raw(fd, "targetHighPrice")), _raw(fd, "targetHighPrice")),
        head("TARGET LOW", num(_raw(fd, "targetLowPrice")), _raw(fd, "targetLowPrice")),
        head("UPSIDE TO MEAN TARGET", pct(upside), upside),
    ]
    months = {"0m": "THIS MONTH", "-1m": "1 MONTH AGO", "-2m": "2 MONTHS AGO", "-3m": "3 MONTHS AGO"}
    mix = [{"period": months.get(t.get("period"), t.get("period")), "strong_buy": t.get("strongBuy"), "buy": t.get("buy"),
            "hold": t.get("hold"), "sell": t.get("sell"), "strong_sell": t.get("strongSell")} for t in trend]
    acts = []
    for h in sorted(hist, key=lambda x: x.get("epochGradeDate") or 0, reverse=True):
        pt, prior = h.get("currentPriceTarget") or None, h.get("priorPriceTarget") or None
        acts.append({"date": iso_date(h.get("epochGradeDate")), "firm": h.get("firm"),
                     "action": (h.get("action") or "").upper(), "from_grade": h.get("fromGrade") or None,
                     "to_grade": h.get("toGrade") or None, "pt_action": h.get("priceTargetAction") or None,
                     "pt": pt, "pt_prior": prior})
    return payload(
        symbol, f"ANR {symbol} · ANALYST RATINGS",
        headline,
        [section("trend", "RECOMMENDATION MIX (ANALYSTS)",
                 [col("period", "PERIOD", "text", 14), col("strong_buy", "STRONG BUY", "int"), col("buy", "BUY", "int"),
                  col("hold", "HOLD", "int"), col("sell", "SELL", "int"), col("strong_sell", "STRONG SELL", "int")], mix),
         section("actions", "RECENT RATING AND TARGET CHANGES",
                 [col("date", "DATE", "date", 10), col("firm", "FIRM", "text", 22), col("action", "ACTION", "text", 8),
                  col("from_grade", "FROM", "text", 14), col("to_grade", "TO", "text", 14),
                  col("pt_action", "TARGET", "text", 8), col("pt", "PT", "price"), col("pt_prior", "PRIOR PT", "price")],
                 acts)],
        ["MEAN RATING: 1 STRONG BUY TO 5 STRONG SELL. TARGETS AND RATINGS FROM YAHOO FINANCE (UNOFFICIAL)"], source)


GOVERNANCE = (("auditRisk", "AUDIT RISK"), ("boardRisk", "BOARD RISK"), ("compensationRisk", "COMPENSATION RISK"),
              ("shareHolderRightsRisk", "SHAREHOLDER RIGHTS RISK"), ("overallRisk", "OVERALL GOVERNANCE RISK"))


def management(symbol: str, result: dict, source: str, proxies: list[dict] | None = None) -> dict:
    """MGMT. Officers and governance scores from Yahoo's company profile; proxy links come from the SEC filings feed."""
    ap = _module(result, "assetProfile")
    officers = [{"name": o.get("name"), "title": o.get("title"), "age": o.get("age"), "born": o.get("yearBorn"),
                 "pay": _raw(o, "totalPay"), "fiscal_year": o.get("fiscalYear")} for o in ap.get("companyOfficers") or []]
    emp = ap.get("fullTimeEmployees")
    headline = [head("EMPLOYEES", f"{emp:,}" if isinstance(emp, int) else None, emp)]
    headline += [head(label, str(ap[k]), ap[k]) for k, label in GOVERNANCE if ap.get(k) is not None]
    proxy_rows = [{"date": p.get("filed"), "form": p.get("form"), "description": p.get("description"),
                   "url": p.get("doc_url") or p.get("url")} for p in proxies or []]
    return payload(
        symbol, f"MGMT {symbol} · MANAGEMENT",
        headline,
        [section("officers", "OFFICERS",
                 [col("name", "NAME", "text", 28), col("title", "TITLE", "text", 36), col("age", "AGE", "int"),
                  col("born", "BORN", "int"), col("pay", "TOTAL PAY", "money"), col("fiscal_year", "FY", "int")], officers),
         section("proxy", "PROXY STATEMENTS (DEF 14A)",
                 [col("date", "FILED", "date", 10), col("form", "FORM", "text", 8), col("description", "DESCRIPTION", "text", 40)],
                 proxy_rows, None if proxy_rows else "NO PROXY STATEMENT IN THE RECENT FILINGS FEED")],
        ["GOVERNANCE RISK 1 (LOW) TO 10 (HIGH), ISS-STYLE SCORES AS PUBLISHED BY YAHOO",
         "BOARD MEMBERS AND THE PAY TABLE ARE IN THE PROXY STATEMENT (DEF 14A); OPEN IT FROM THE ROW, IT IS NOT PARSED HERE"],
        source)
