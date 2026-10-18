"""Pure parsers and payload builders for DVD, SPLT, CACS, IPO, SI and EVTS (spec: docs/specs/PHASE_13.md).

Providers answer small "raw" dicts built by the first group of functions (Nasdaq JSON, Yahoo chart events, Yahoo key
statistics, FINRA files); the second group turns raw dicts into table payloads. No I/O here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..providers.base import ProviderError
from ..providers.sec_parse import ITEMS_8K
from .table import col, head, iso_date, number, payload, section, us_date

# ---------------------------------------------------------------------------------------------- raw: Nasdaq


def nasdaq_dividends(body: dict, source: str) -> dict:
    d = (body or {}).get("data")
    rows = ((d or {}).get("dividends") or {}).get("rows")
    if not d or not rows:
        raise ProviderError("not_found", "no dividends")
    out = []
    for r in rows:
        ex = us_date(r.get("exOrEffDate"))
        if not ex:
            continue
        out.append({"ex_date": ex, "amount": number(r.get("amount")), "type": r.get("type") or None,
                    "declared": us_date(r.get("declarationDate")), "record": us_date(r.get("recordDate")),
                    "pay": us_date(r.get("paymentDate"))})
    yld = number(d.get("yield"))
    return {"rows": out, "annual": number(d.get("annualizedDividend")), "yield": yld / 100 if yld is not None else None,
            "ex_date": us_date(d.get("exDividendDate")), "pay_date": us_date(d.get("dividendPaymentDate")),
            "source": source}


def _events(events: dict, kind: str) -> list[dict]:
    return list((events.get(kind) or {}).values())


def yahoo_dividends(chart: dict, source: str) -> dict:
    rows = [{"ex_date": iso_date(e.get("date")), "amount": e.get("amount"), "type": "Cash", "declared": None,
             "record": None, "pay": None} for e in _events(chart["events"], "dividends") if e.get("date")]
    if not rows:
        raise ProviderError("not_found", "no dividends")
    return {"rows": rows, "annual": None, "yield": None, "ex_date": None, "pay_date": None, "source": source}


def yahoo_splits(chart: dict, source: str) -> dict:
    rows = []
    for e in _events(chart["events"], "splits"):
        num, den = e.get("numerator"), e.get("denominator")
        rows.append({"date": iso_date(e.get("date")), "ratio": e.get("splitRatio") or (f"{num}:{den}" if num else None),
                     "numerator": num, "denominator": den})
    if not rows:
        raise ProviderError("not_found", "no splits")
    return {"rows": rows, "source": source}


def nasdaq_short_interest(body: dict, source: str) -> dict:
    t = (((body or {}).get("data") or {}).get("shortInterestTable") or {}).get("rows")
    if not t:
        raise ProviderError("not_found", "no short interest")
    rows = [{"date": us_date(r.get("settlementDate")), "interest": number(r.get("interest")),
             "avg_volume": number(r.get("avgDailyShareVolume")), "days_to_cover": number(r.get("daysToCover"))}
            for r in t if us_date(r.get("settlementDate"))]
    return {"rows": rows, "source": source}


def keystats_values(summary: dict) -> dict:
    """Short-interest and share-count fields from Yahoo defaultKeyStatistics (all optional)."""
    ks = summary.get("defaultKeyStatistics") or {}
    sd = summary.get("summaryDetail") or {}

    def raw(k: str, src: dict = ks) -> Any:
        v = src.get(k)
        return v.get("raw") if isinstance(v, dict) else v

    return {"shares_short": raw("sharesShort"), "short_ratio": raw("shortRatio"), "short_pct_float": raw("shortPercentOfFloat"),
            "float_shares": raw("floatShares"), "date": iso_date(raw("dateShortInterest")),
            "prior_shares": raw("sharesShortPriorMonth"), "prior_date": iso_date(raw("sharesShortPreviousMonthDate")),
            "beta": raw("beta"), "shares_outstanding": raw("sharesOutstanding"),
            "dividend_yield": raw("trailingAnnualDividendYield", sd)}


def yahoo_short_interest(summary: dict, source: str) -> dict:
    k = keystats_values(summary)
    if k["shares_short"] is None or not k["date"]:
        raise ProviderError("not_found", "no short interest")
    rows = [{"date": k["date"], "interest": k["shares_short"], "avg_volume": None, "days_to_cover": k["short_ratio"]}]
    if k["prior_shares"] is not None and k["prior_date"]:
        rows.append({"date": k["prior_date"], "interest": k["prior_shares"], "avg_volume": None, "days_to_cover": None})
    return {"rows": rows, "source": source}


def parse_short_volume(text: str) -> dict[str, tuple[float, float, float]]:
    """FINRA Reg SHO daily file -> {symbol: (short, short_exempt, total)}. Header and malformed lines are skipped."""
    out: dict[str, tuple[float, float, float]] = {}
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 5 or parts[0] == "Date":
            continue
        try:
            out[parts[1]] = (float(parts[2]), float(parts[3]), float(parts[4]))
        except ValueError:
            continue
    return out


def ipo_tables(body: dict, source: str) -> dict:
    d = (body or {}).get("data")
    if not d:
        raise ProviderError("not_found", "no IPO calendar")
    return {"data": d, "source": source}


# ---------------------------------------------------------------------------------------------- payloads


def _money(text: Any) -> float | None:
    return number(text)


def dvd_payload(symbol: str, raw: dict) -> dict:
    rows = sorted(raw["rows"], key=lambda r: r["ex_date"] or "", reverse=True)
    paid = [r for r in rows if r["amount"] is not None]
    last12 = None
    if paid:
        newest = date.fromisoformat(paid[0]["ex_date"])
        cutoff = (newest - timedelta(days=365)).isoformat()
        last12 = sum(r["amount"] for r in paid if r["ex_date"] > cutoff)
    ex = raw["ex_date"] or (rows[0]["ex_date"] if rows else None)
    headline = [
        head("EX-DIVIDEND", ex), head("PAY DATE", raw["pay_date"] or (rows[0]["pay"] if rows else None)),
        head("YIELD", f"{raw['yield'] * 100:.2f}%" if raw["yield"] is not None else None, raw["yield"]),
        head("ANNUAL DIVIDEND", f"{raw['annual']:.2f}" if raw["annual"] is not None else None, raw["annual"]),
        head("PAID IN THE 12 MONTHS TO LAST EX-DATE", f"{last12:.4f}" if last12 is not None else None, last12),
    ]
    return payload(
        symbol, f"DVD {symbol} · DIVIDENDS", headline,
        [section("dividends", "DIVIDEND HISTORY",
                 [col("ex_date", "EX-DATE", "date", 10), col("amount", "AMOUNT", "price"), col("type", "TYPE", "text", 8),
                  col("declared", "DECLARED", "date", 10), col("record", "RECORD", "date", 10), col("pay", "PAY DATE", "date", 10)],
                 rows)],
        [] if raw["annual"] is not None else ["DECLARATION, RECORD AND PAY DATES NEED THE NASDAQ SOURCE (UNAVAILABLE): EX-DATES AND AMOUNTS ONLY"],
        raw["source"])


def splt_payload(symbol: str, raw: dict) -> dict:
    rows = sorted(raw["rows"], key=lambda r: r["date"] or "", reverse=True)
    return payload(
        symbol, f"SPLT {symbol} · STOCK SPLITS", [head("SPLITS ON RECORD", str(len(rows)), len(rows))],
        [section("splits", "SPLIT HISTORY",
                 [col("date", "DATE", "date", 10), col("ratio", "RATIO", "text", 8), col("numerator", "NEW SHARES", "int"),
                  col("denominator", "OLD SHARES", "int")], rows)],
        ["RATIO = NEW SHARES : OLD SHARES (4:1 FOUR SHARES FOR EACH ONE HELD); A REVERSE SPLIT SHOWS 1:N"], raw["source"])


def cacs_payload(symbol: str, dvd: dict | None, splt: dict | None, missing: list[str], source: str) -> dict:
    rows = []
    for r in (dvd or {}).get("rows", []):
        amt = f"${r['amount']:.4f}".rstrip("0").rstrip(".") if r["amount"] is not None else "-"
        rows.append({"date": r["ex_date"], "kind": "DIVIDEND", "detail": f"{amt} {str(r['type'] or '').upper()}".strip(),
                     "pay": r["pay"]})
    for r in (splt or {}).get("rows", []):
        rows.append({"date": r["date"], "kind": "SPLIT", "detail": r["ratio"], "pay": None})
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    notes = ["MERGED BY OPENTERM FROM THE DVD AND SPLT SOURCES; SPIN-OFFS, MERGERS AND TICKER CHANGES ARE NOT IN THIS FEED: SEE EVTS (8-K ITEMS)"]
    notes += [f"{m} UNAVAILABLE: ROWS FOR IT ARE MISSING" for m in missing]
    return payload(
        symbol, f"CACS {symbol} · CORPORATE ACTIONS", [head("ACTIONS", str(len(rows)), len(rows))],
        [section("actions", "DIVIDENDS AND SPLITS BY DATE",
                 [col("date", "DATE", "date", 10), col("kind", "ACTION", "text", 9), col("detail", "DETAIL", "text", 24),
                  col("pay", "PAY DATE", "date", 10)], rows)],
        notes, source)


def valid_month(text: str | None, today: date | None = None) -> str:
    """YYYY-MM, default the current month. Raises ValueError with the usage text on anything else."""
    if not text:
        t = today or datetime.now(UTC).date()
        return f"{t.year:04d}-{t.month:02d}"
    s = text.strip()
    try:
        y, m = (int(x) for x in s.split("-"))
    except ValueError:
        raise ValueError("MONTH: YYYY-MM") from None
    if len(s) != 7 or not (1990 <= y <= 2100) or not (1 <= m <= 12):
        raise ValueError("MONTH: YYYY-MM")
    return s


def ipo_payload(month: str, raw: dict) -> dict:
    d = raw["data"]

    def rows(key: str, date_key: str) -> list[dict]:
        t = d.get(key) or {}
        r = t.get("rows") if "rows" in t else (t.get("upcomingTable") or {}).get("rows")
        out = []
        for x in r or []:
            out.append({"symbol": x.get("proposedTickerSymbol"), "company": x.get("companyName"),
                        "exchange": x.get("proposedExchange"), "price": _money(x.get("proposedSharePrice")),
                        "range": x.get("proposedSharePrice"), "shares": number(x.get("sharesOffered")),
                        "date": us_date(x.get(date_key)), "filed": us_date(x.get("filedDate")),
                        "amount": _money(x.get("dollarValueOfSharesOffered"))})
        out.sort(key=lambda r: r["date"] or "", reverse=True)
        return out

    up, priced = rows("upcoming", "expectedPriceDate"), rows("priced", "pricedDate")
    filed, wd = rows("filed", "filedDate"), rows("withdrawn", "withdrawDate")
    base = [col("symbol", "SYMBOL", "text", 8), col("company", "COMPANY", "text", 34), col("exchange", "EXCHANGE", "text", 20)]
    sections = [
        section("upcoming", "UPCOMING", [*base, col("range", "PRICE", "text", 12), col("shares", "SHARES", "int"),
                                         col("date", "EXPECTED", "date", 10), col("amount", "OFFER", "money")], up,
                "NONE SCHEDULED IN THIS MONTH" if not up else None),
        section("priced", "PRICED", [*base, col("price", "PRICE", "price"), col("shares", "SHARES", "int"),
                                     col("date", "DATE", "date", 10), col("amount", "OFFER", "money")], priced),
        section("filed", "FILED", [col("symbol", "SYMBOL", "text", 8), col("company", "COMPANY", "text", 34),
                                   col("date", "FILED", "date", 10), col("amount", "OFFER", "money")], filed),
        section("withdrawn", "WITHDRAWN", [*base, col("filed", "FILED", "date", 10), col("date", "WITHDRAWN", "date", 10),
                                           col("amount", "OFFER", "money")], wd),
    ]
    heads = [head("MONTH", month), head("UPCOMING", str(len(up)), len(up)), head("PRICED", str(len(priced)), len(priced)),
             head("FILED", str(len(filed)), len(filed)), head("WITHDRAWN", str(len(wd)), len(wd))]
    return payload(None, f"IPO · {month}", heads, sections, ["NASDAQ.COM IPO CALENDAR (EDGAR-DERIVED); A FILED DEAL HAS NO SYMBOL UNTIL IT PRICES"], raw["source"])


def si_payload(symbol: str, interest: dict, volume: dict | None, volume_note: str | None, keystats: dict | None) -> dict:
    rows = sorted(interest["rows"], key=lambda r: r["date"] or "", reverse=True)
    for i, r in enumerate(rows):
        older = rows[i + 1] if i + 1 < len(rows) else None
        r["change"] = r["interest"] / older["interest"] - 1 if older and older["interest"] and r["interest"] is not None else None
    vol_rows = []
    for r in (volume or {}).get("rows", []):
        vol_rows.append({**r, "short_pct": r["short_volume"] / r["total_volume"] if r["total_volume"] else None})
    headline: list[dict] = []
    if keystats:
        k = keystats
        if k["short_pct_float"] is not None:
            headline.append(head("SHORT % OF FLOAT", f"{k['short_pct_float'] * 100:.2f}%", k["short_pct_float"]))
        if k["shares_short"] is not None:
            headline.append(head("SHARES SHORT", f"{k['shares_short']:,.0f}", k["shares_short"]))
        if k["float_shares"] is not None:
            headline.append(head("FLOAT", f"{k['float_shares']:,.0f}", k["float_shares"]))
    if rows and rows[0]["days_to_cover"] is not None:
        headline.append(head("DAYS TO COVER", f"{rows[0]['days_to_cover']:.2f}", rows[0]["days_to_cover"]))
    if vol_rows:
        sv, tv = sum(r["short_volume"] for r in vol_rows), sum(r["total_volume"] for r in vol_rows)
        avg = sv / tv if tv else None
        headline.append(head(f"SHORT % OF VOLUME ({len(vol_rows)} DAYS, COMPUTED)", f"{avg * 100:.1f}%" if avg is not None else None, avg))
    notes = ["SHORT INTEREST: FINRA, TWICE A MONTH, PUBLISHED ABOUT A WEEK AFTER THE SETTLEMENT DATE. SHORT VOLUME IS NOT SHORT INTEREST: IT COUNTS SHORT SALES DURING THE DAY, MARKET-MAKER HEDGING INCLUDED"]
    if volume_note:
        notes.append(volume_note)
    if not keystats:
        notes.append("YAHOO KEY STATISTICS UNAVAILABLE: FLOAT-BASED RATIOS NOT SHOWN")
    return payload(
        symbol, f"SI {symbol} · SHORT INTEREST", headline,
        [section("interest", "SHORT INTEREST BY SETTLEMENT DATE",
                 [col("date", "SETTLED", "date", 10), col("interest", "SHORT INTEREST", "int"), col("change", "CHANGE", "pct"),
                  col("avg_volume", "AVG DAILY VOL", "int"), col("days_to_cover", "DAYS TO COVER", "num")], rows),
         section("volume", "FINRA DAILY SHORT SALE VOLUME (REG SHO)",
                 [col("date", "DATE", "date", 10), col("short_volume", "SHORT VOLUME", "int"),
                  col("short_exempt", "SHORT EXEMPT", "int"), col("total_volume", "TOTAL VOLUME", "int"),
                  col("short_pct", "SHORT %", "pct")], vol_rows,
                 None if vol_rows else "NO FINRA DAILY FILE FOUND IN THE LOOK-BACK WINDOW")],
        notes, interest["source"])


def decode_items(items: str | None) -> str:
    if not items:
        return ""
    return "; ".join(f"{i} {ITEMS_8K[i].upper()}" if i in ITEMS_8K else i for i in items.split(",") if i)


def evts_payload(symbol: str, filings: list[dict], total: int, source: str) -> dict:
    rows = [{"date": f["filed"], "form": f["form"], "items": decode_items(f["items"]) or "NO ITEMS LISTED",
             "url": f["url"]} for f in filings]
    return payload(
        symbol, f"EVTS {symbol} · COMPANY EVENTS (8-K)", [head("8-K FILINGS", str(total), total)],
        [section("events", "8-K FILINGS BY ITEM",
                 [col("date", "FILED", "date", 10), col("form", "FORM", "text", 6), col("items", "ITEMS", "text", 60)], rows)],
        ["ITEM NAMES ARE SHORT LABELS; ENTER OPENS THE FILING ON SEC.GOV. THIS IS THE SEC FEED: NEWS WITH A SENTIMENT SCORE IS CN"],
        source)


def nasdaq_earnings_history(body: dict, source: str) -> dict:
    """Nasdaq `company/<SYM>/earnings-surprise`: the last four reported quarters with the date each was announced."""
    rows = (((body or {}).get("data") or {}).get("earningsSurpriseTable") or {}).get("rows") or []
    out = []
    for r in rows:
        day = us_date(r.get("dateReported"))
        if not day:
            continue
        out.append({"date": day, "fiscal": r.get("fiscalQtrEnd"), "eps": number(r.get("eps")),
                    "estimate": number(r.get("consensusForecast")), "surprise_pct": number(r.get("percentageSurprise"))})
    if not out:
        raise ProviderError("not_found", "no earnings history")
    return {"rows": out, "source": source}


def chart_events(symbol: str, dvd: dict | None, splt: dict | None, earn: dict | None, missing: list[str]) -> dict:
    """GP event markers: E (earnings announced), D (ex-dividend), S (split), oldest first. Detail text is what the marker's readout says."""
    events: list[dict] = []
    for r in (dvd or {}).get("rows", []):
        if r.get("ex_date"):
            amt = f" ${r['amount']:.4f}".rstrip("0").rstrip(".") if r.get("amount") is not None else ""
            events.append({"date": r["ex_date"], "kind": "D", "detail": f"DIV{amt}"})
    for r in (splt or {}).get("rows", []):
        if r.get("date"):
            events.append({"date": r["date"], "kind": "S", "detail": f"SPLIT {r['ratio']}".strip()})
    for r in (earn or {}).get("rows", []):
        parts = [f"EPS {r['eps']:g}"] if r.get("eps") is not None else ["EPS n/a"]
        if r.get("estimate") is not None:
            parts.append(f"VS {r['estimate']:g}")
        if r.get("surprise_pct") is not None:
            parts.append(f"({r['surprise_pct']:+g}%)")
        events.append({"date": r["date"], "kind": "E", "detail": " ".join(parts)})
    events.sort(key=lambda e: (e["date"], e["kind"]))
    notes = [f"{m} UNAVAILABLE: THOSE MARKERS ARE MISSING" for m in missing]
    if earn:
        notes.append("EARNINGS MARKERS: LAST FOUR REPORTED QUARTERS ONLY (NASDAQ)")
    sources = [x["source"] for x in (dvd, splt, earn) if x and x.get("source")]
    return {"symbol": symbol, "events": events, "missing": missing, "notes": notes, "source": " + ".join(dict.fromkeys(sources))}
