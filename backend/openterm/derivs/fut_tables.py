"""Table payloads for CT, WIRP and COT (spec decisions L, M). Pure: the service passes in quotes, dates and reports."""

from __future__ import annotations

import calendar
from itertools import pairwise

from ..research.table import col, head, payload, section
from . import fut_parse as fp

# --- CT ---------------------------------------------------------------------------------------------------------------


def shape_of(prices: list[float]) -> str:
    diffs = [b - a for a, b in pairwise(prices)]
    if not diffs:
        return "SINGLE CONTRACT"
    if all(d >= 0 for d in diffs):
        return "CONTANGO"
    if all(d <= 0 for d in diffs):
        return "BACKWARDATION"
    return "MIXED"


def ct_payload(root: str, planned: int, got: list[dict], skipped: list[str], source: str) -> dict:
    """`got`: contracts in date order, each {symbol, year, month, quote}."""
    name = fp.ROOTS[root][4]
    rows, prev = [], None
    base_month = got[0]["year"] * 12 + got[0]["month"] if got else 0
    for c in got:
        q, mi = c["quote"], c["year"] * 12 + c["month"]
        roll = None
        if prev is not None and q["price"]:
            gap = mi - prev["mi"]
            roll = (prev["price"] - q["price"]) / q["price"] * 12.0 / gap
        rows.append({"symbol": c["symbol"], "contract": fp.label(c["year"], c["month"]), "price": q["price"], "change": q["change"],
                     "volume": q["volume"], "spread": q["price"] - got[0]["quote"]["price"], "roll_yield": roll})
        prev = {"price": q["price"], "mi": mi}
    prices = [c["quote"]["price"] for c in got]
    sec = section("contracts", f"{root} CONTRACTS", [
        col("symbol", "SYMBOL"), col("contract", "CONTRACT"), col("price", "PRICE", "price"), col("change", "CHG", "num"),
        col("volume", "VOLUME", "int"), col("spread", "SPREAD TO FRONT", "num"), col("roll_yield", "ROLL YIELD (ANN.)", "pct")],
        rows, "ROLL YIELD = (PREVIOUS CONTRACT - THIS CONTRACT) / THIS CONTRACT, ANNUALISED BY THE MONTHS BETWEEN THE TWO")
    shape = shape_of(prices) if prices else "-"
    headline = [head("ROOT", f"{root} {name}"), head("SHAPE", shape),
                head("FRONT", f"{prices[0]:,.4f}" if prices else None, prices[0] if prices else None),
                head("CONTRACTS", f"{len(got)} OF {planned}", len(got))]
    notes = ["ROLL YIELD IS ANNUALISED BY CONTRACT MONTH SPACING, NOT EXPIRY DATES (YAHOO RETURNS NO EXPIRY DATE)",
             "CONTRACTS YAHOO DOES NOT LIST ARE SKIPPED, NEVER INVENTED" + (": " + " ".join(skipped) if skipped else ""),
             "PRICES ARE DELAYED; SHAPE IS CALLED ONLY FROM THE LISTED CONTRACTS"]
    chart = {"id": "curve", "title": f"{root} FUTURES CURVE", "xlabel": "MONTHS FROM FRONT", "ylabel": "PRICE",
             "series": [{"name": root, "points": [[c["year"] * 12 + c["month"] - base_month, c["quote"]["price"]] for c in got]}]}
    return payload(root, f"CT {root}", headline, [sec], notes, source, charts=[chart])


# --- WIRP -------------------------------------------------------------------------------------------------------------

LATE_MONTH = 0.25   # a meeting with less than this share of its month left reads the next month's contract instead


def wirp_path(effr: float, meetings: list[str], implied: dict[tuple[int, int], float]) -> list[dict]:
    """Chain the monthly implied average rates (percent) across the FOMC decision dates. The rate changes on the day after a
    decision, so month M with the decision on day d averages `d` days at the old rate and `N - d` days at the new one."""
    meeting_months = {(int(m[:4]), int(m[5:7])) for m in meetings}
    rows, before, cum = [], effr, 0.0
    for d in meetings:
        y, m, day = int(d[:4]), int(d[5:7]), int(d[8:])
        n = calendar.monthrange(y, m)[1]
        nxt = (y + (m == 12), m % 12 + 1)
        late = (n - day) / n < LATE_MONTH
        if late and nxt not in meeting_months and nxt in implied:
            after, used, how = implied[nxt], nxt, "NEXT MONTH AVERAGE (DECISION LATE IN ITS MONTH)"
        elif (y, m) in implied and n - day > 0:
            after, used = (implied[(y, m)] * n - day * before) / (n - day), (y, m)
            how = "MONTH AVERAGE SPLIT AT THE DECISION DAY" + ("; LATE IN MONTH, NOISY" if late else "")
        else:
            break
        cum += (after - before) * 100.0
        rows.append({"meeting": d, "contract": f"ZQ{fp.CODE_OF_MONTH[used[1]]}{used[0] % 100:02d}", "how": how, "rate_before": before,
                     "rate_after": after, "change_bp": (after - before) * 100.0, "move_share": abs(after - before) * 100.0 / 25.0,
                     "cum_bp": cum})
        before = after
    return rows


def wirp_payload(effr: dict, band: tuple[float | None, float | None], meetings_all: list[str], path: list[dict],
                 months: list[dict], skipped: list[str], source: str) -> dict:
    path_sec = section("path", "IMPLIED POLICY PATH", [
        col("meeting", "DECISION", "date"), col("contract", "CONTRACT"), col("rate_before", "RATE BEFORE", "num4"),
        col("rate_after", "RATE AFTER", "num4"), col("change_bp", "CHANGE BP", "bp"), col("move_share", "25BP MOVE SHARE", "pct"),
        col("cum_bp", "CUM BP", "bp"), col("how", "BASIS")], path,
        "RATES IN PERCENT. THE MOVE SHARE IS |CHANGE| / 25 BP: ILLUSTRATIVE, NOT A PROBABILITY")
    month_sec = section("months", "FED FUNDS FUTURES (ZQ)", [
        col("contract", "CONTRACT"), col("month", "MONTH"), col("price", "PRICE", "price"), col("implied", "IMPLIED RATE", "num4"),
        col("vs_effr", "VS EFFR BP", "bp")], months)
    lo, hi = band
    headline = [head("EFFR", f"{effr['value']:.2f}% {effr['date']}", effr["value"]),
                head("TARGET RANGE", f"{lo:.2f}-{hi:.2f}%" if lo is not None and hi is not None else None),
                head("MEETINGS", f"{len(path)} OF {len([m for m in meetings_all])} LISTED", len(path))]
    notes = ["IMPLIED BY FUTURES PRICES, NOT A PROBABILITY FORECAST: AVERAGE RATE = 100 - PRICE; A TERM PREMIUM AND THE DAY-COUNT SPLIT ARE IGNORED",
             "THE DECISION TAKES EFFECT THE NEXT DAY; A LATE-MONTH DECISION READS THE NEXT MONTH'S CONTRACT (NOT SPLIT)",
             "FOMC DATES: federalreserve.gov CALENDAR (REFRESHED DAILY). EFFR AND TARGET RANGE: FRED DFF, DFEDTARL, DFEDTARU"]
    if skipped:
        notes.append("CONTRACTS YAHOO DID NOT LIST, SKIPPED: " + " ".join(skipped))
    return payload("WIRP", "WIRP FED FUNDS IMPLIED PATH", headline, [path_sec, month_sec], notes, source)


# --- COT --------------------------------------------------------------------------------------------------------------

GROUPS = (("NON-COMMERCIAL", "nc"), ("COMMERCIAL", "c"), ("NON-REPORTABLE", "nr"))


def percentile(values: list[int], x: int) -> float:
    return sum(v <= x for v in values) / len(values)


def cot_payload(rows: list[dict], matches: list[str], source: str) -> dict:
    """`rows`: cot_row() dicts, newest first."""
    top = rows[0]
    nets = [r["nc_net"] for r in rows]
    pct = percentile(nets, nets[0])
    pos = [{"group": g, "long": top[f"{t}_long"], "short": top[f"{t}_short"], "net": top[f"{t}_net"],
            "chg_long": top[f"{t}_chg_long"], "chg_short": top[f"{t}_chg_short"], "chg_net": top[f"{t}_chg_net"],
            "share": (top[f"{t}_long"] + top[f"{t}_short"]) / (2.0 * top["oi"]) if top["oi"] else None} for g, t in GROUPS]
    pos_sec = section("positions", "POSITIONS (LEGACY, FUTURES ONLY)", [
        col("group", "GROUP"), col("long", "LONG", "int"), col("short", "SHORT", "int"), col("net", "NET", "int"),
        col("chg_long", "CHG LONG", "int"), col("chg_short", "CHG SHORT", "int"), col("chg_net", "CHG NET", "int"),
        col("share", "SHARE OF OI", "pct")], pos, "SHARE OF OI = (LONG + SHORT) / (2 x OPEN INTEREST)")
    hist = [{"date": r["date"], "noncomm_net": r["nc_net"], "comm_net": r["c_net"], "nonrept_net": r["nr_net"], "oi": r["oi"]}
            for r in rows]
    hist_sec = section("history", f"NET POSITIONS, LAST {len(rows)} WEEKS", [
        col("date", "REPORT DATE", "date"), col("noncomm_net", "NON-COMM NET", "int"), col("comm_net", "COMM NET", "int"),
        col("nonrept_net", "NON-REPT NET", "int"), col("oi", "OPEN INTEREST", "int")], hist)
    headline = [head("MARKET", top["market"]), head("REPORT DATE", top["date"]),
                head("OPEN INTEREST", f"{top['oi']:,}", top["oi"]), head("NON-COMM NET", f"{top['nc_net']:,}", top["nc_net"]),
                head("NON-COMM NET PERCENTILE", f"{pct * 100:.0f}%", pct)]
    notes = [f"PERCENTILE (COMPUTED HERE): SHARE OF THE {len(rows)} WEEKS SHOWN WHOSE NON-COMMERCIAL NET WAS AT OR BELOW THE LATEST",
             "AS OF TUESDAY, RELEASED FRIDAY 15:30 ET. LEGACY REPORT, FUTURES ONLY (NO OPTIONS)"]
    if matches:
        notes.append("OTHER MATCHES: " + " | ".join(matches))
    chart = {"id": "net", "title": f"NON-COMMERCIAL NET, {len(rows)} WEEKS", "xlabel": "WEEKS AGO (0 = LATEST)", "ylabel": "NET CONTRACTS",
             "series": [{"name": "NON-COMM NET", "points": [[-i, r["nc_net"]] for i, r in reversed(list(enumerate(rows)))]},
                        {"name": "COMM NET", "points": [[-i, r["c_net"]] for i, r in reversed(list(enumerate(rows)))], "dash": True}]}
    return payload(top["code"], f"COT {top['market']}", headline, [pos_sec, hist_sec], notes, source, charts=[chart])
