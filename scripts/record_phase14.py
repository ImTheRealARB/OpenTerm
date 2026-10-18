"""Records the keyless Phase 14 fixtures (options, rates, futures). No key is used.

Run from backend/:  uv run python ../scripts/record_phase14.py
Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON) or {"status", "text", "content_type"} (text/CSV/HTML), like every
other recording. Big answers are trimmed; each trim is noted next to the line that makes it. A source that does not answer stops the run
(nothing is invented). FRED must be called with a plain User-Agent (a browser User-Agent hangs).
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
PLAIN = {"User-Agent": "OpenTerm/1.0 (personal research)"}
YQ = "https://query1.finance.yahoo.com"
JSON_ACCEPT = {"Accept": "application/json"}

CT_ROOTS = {  # root -> contract symbols recorded (Yahoo: <root><month code><yy>.<exchange>)
    "CL": [f"CL{m}{y}.NYM" for y, ms in (("26", "XZ"), ("27", "FGHJKMNQUVXZ"), ("28", "F")) for m in ms],
    "ZQ": [f"ZQ{m}{y}.CBT" for y, ms in (("26", "VXZ"), ("27", "FGHJKMNQUVXZ")) for m in ms],
    "ES": ["ESZ26.CME", "ESH27.CME", "ESM27.CME", "ESU27.CME"],
    "ZN": ["ZNZ26.CBT", "ZNH27.CBT", "ZNM27.CBT"],
}
CFTC_CODES = {"13874A": "es", "067651": "cl", "088691": "gc", "043602": "zn"}  # E-mini S&P 500, WTI, gold, 10-year note
CFTC_FIELDS = ",".join([
    "report_date_as_yyyy_mm_dd", "market_and_exchange_names", "cftc_contract_market_code", "contract_units", "open_interest_all",
    "noncomm_positions_long_all", "noncomm_positions_short_all", "noncomm_postions_spread_all", "comm_positions_long_all",
    "comm_positions_short_all", "nonrept_positions_long_all", "nonrept_positions_short_all", "change_in_open_interest_all",
    "change_in_noncomm_long_all", "change_in_noncomm_short_all", "change_in_comm_long_all", "change_in_comm_short_all",
    "change_in_nonrept_long_all", "change_in_nonrept_short_all", "traders_tot_all"])
TD_FIELDS = ["cusip", "securityType", "securityTerm", "securityDescription", "announcementDate", "competitiveAuctionCloseDate", "issueDate",
             "maturityDate", "offeringAmount", "bidToCoverRatio", "highRate", "lowRate", "medianRate", "highYield", "highDiscountRate",
             "investmentRate", "highPrice", "reopening", "inflationProtected", "floatingRate", "cashManagementBill", "updatedTimestamp",
             "grandTotalParAwarded", "primaryDealersCompetitiveParAwarded", "directBiddersCompetitiveParAwarded",
             "indirectBiddersCompetitiveParAwarded", "treasuryAuctionResultsPressReleaseFileName"]
FRED_OAS = ["BAMLC0A0CM", "BAMLH0A0HYM2", "BAMLC0A4CBBB", "BAMLH0A1HYBB", "BAMLH0A3HYC"]
FRED_POLICY = ["DFF", "DFEDTARU", "DFEDTARL"]


def save_json(name: str, body) -> None:
    (OUT / f"{name}.json").write_bytes(json.dumps({"status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: json")


def save_text(name: str, text: str, content_type: str) -> None:
    rec = {"status": 200, "text": text, "content_type": content_type}
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: {len(text)} chars")


def ok(r: httpx.Response) -> httpx.Response:
    r.raise_for_status()
    return r


def pick_expiries(dates: list[int]) -> list[int]:
    """The 8 expiries every options function uses (mirrors openterm.options.surface.pick_expiries, locked by a test):
    the nearest, then the one closest to +7, +30, +60, +90, +180, +270 and +365 days after it, each used once."""
    first, picked = dates[0], [dates[0]]
    for days in (7, 30, 60, 90, 180, 270, 365):
        rest = [d for d in dates if d not in picked]
        if rest:
            picked.append(min(rest, key=lambda d: abs(d - (first + days * 86400))))
    return sorted(picked)


def record_options(h: httpx.Client) -> None:
    h.get("https://fc.yahoo.com", headers={"Accept": "*/*"})
    crumb = h.get(f"{YQ}/v1/test/getcrumb", headers={"Accept": "*/*"}).text
    first = ok(h.get(f"{YQ}/v7/finance/options/AAPL", params={"crumb": crumb}, headers=JSON_ACCEPT)).json()
    res = first["optionChain"]["result"][0]
    dates = res["expirationDates"]
    spot = res["quote"]["regularMarketPrice"]
    pick = pick_expiries(dates)
    print("AAPL spot", spot, "expiries", pick)
    for epoch in pick:
        body = first if epoch == dates[0] else ok(h.get(f"{YQ}/v7/finance/options/AAPL", params={"date": epoch, "crumb": crumb},
                                                       headers=JSON_ACCEPT)).json()
        opt = body["optionChain"]["result"][0]["options"][0]
        for side in ("calls", "puts"):  # trim: strikes within 35 percent of spot
            opt[side] = [c for c in opt[side] if 0.65 * spot <= c["strike"] <= 1.35 * spot]
        body["optionChain"]["result"][0]["strikes"] = [k for k in body["optionChain"]["result"][0]["strikes"]
                                                       if 0.65 * spot <= k <= 1.35 * spot]
        save_json(f"yahoo_options_aapl_{epoch}", body)
        time.sleep(0.5)


def record_futures(h: httpx.Client) -> None:
    for root, symbols in CT_ROOTS.items():
        for s in symbols:
            r = h.get(f"{YQ}/v8/finance/chart/{s}", params={"range": "5d", "interval": "1d"}, headers=JSON_ACCEPT)
            if r.status_code != 200:
                print(f"{s}: HTTP {r.status_code}, skipped")
                continue
            save_json(f"yahoo_chart_fut_{s.replace('.', '_')}", r.json())
            time.sleep(0.2)


def record_deribit(h: httpx.Client) -> None:
    r = ok(h.get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency", params={"currency": "BTC", "kind": "option"})).json()
    rows = r["result"]
    expiries = sorted({x["instrument_name"].split("-")[1] for x in rows},
                      key=lambda e: time.strptime(e, "%d%b%y"))
    keep = {expiries[0], expiries[len(expiries) // 3], expiries[len(expiries) // 2], expiries[-1]}
    print("deribit expiries kept", sorted(keep, key=lambda e: time.strptime(e, "%d%b%y")), "of", len(expiries))
    r["result"] = [x for x in rows if x["instrument_name"].split("-")[1] in keep]  # trim: four expiries
    save_json("deribit_book_btc", r)
    save_json("deribit_index_btc", ok(h.get("https://www.deribit.com/api/v2/public/get_index_price", params={"index_name": "btc_usd"})).json())


def record_cftc(h: httpx.Client) -> None:
    base = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
    for code, tag in CFTC_CODES.items():
        rows = ok(h.get(base, params={"$select": CFTC_FIELDS, "$where": f"cftc_contract_market_code='{code}'",
                                       "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "160"})).json()  # trim: the fields COT reads
        print(f"cftc {tag}: {len(rows)} rows, newest {rows[0]['report_date_as_yyyy_mm_dd'][:10]}, {rows[0]['market_and_exchange_names']}")
        save_json(f"cftc_legacy_{tag}", rows)
    names = ok(h.get(base, params={"$select": "market_and_exchange_names,cftc_contract_market_code",
                                   "$group": "market_and_exchange_names,cftc_contract_market_code",
                                   "$where": "report_date_as_yyyy_mm_dd > '2026-08-15'", "$limit": "2000"})).json()
    keep_words = ("E-MINI S&P 500", "CRUDE OIL", "GOLD", "10-YEAR", "EURO FX", "NASDAQ", "NATURAL GAS", "SILVER", "COPPER", "BITCOIN",
                  "VIX", "WHEAT", "CORN", "SOYBEANS", "JAPANESE YEN")
    save_json("cftc_markets", [x for x in names if any(w in x["market_and_exchange_names"] for w in keep_words)])  # trim: popular markets


def record_rates(h: httpx.Client) -> None:
    tenors = ["3M", "6M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y"]
    # one SDMX dimension with alternatives joined by +
    key = "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_" + "+SR_".join(tenors)
    r = ok(h.get(f"https://data-api.ecb.europa.eu/service/data/YC/{key}", params={"lastNObservations": "10", "format": "jsondata"}))
    save_json("ecb_yc_spot", r.json())
    save_json("boc_yields", ok(h.get("https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json",
                                      params={"recent": "10"})).json())
    mof = ok(h.get("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv")).content.decode("utf-8-sig")
    lines = mof.splitlines()
    save_text("mof_jgb", "\n".join(lines[:2] + lines[-40:]) + "\n", "text/csv")  # trim: header and the last 40 days
    boe = ok(h.get("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
                   params={"csv.x": "yes", "Datefrom": "01/Sep/2026", "Dateto": "16/Oct/2026",
                           "SeriesCodes": "IUDSNPY,IUDMNPY,IUDLNPY", "CSVF": "TN", "UsingCodes": "Y"}))
    save_text("boe_par_yields", boe.text, "text/csv")
    for sid in FRED_OAS + FRED_POLICY:
        r = ok(h.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers=PLAIN))
        lines = r.text.splitlines()
        keep = 120 if sid in FRED_POLICY else 800
        save_text(f"fred_csv_{sid}", "\n".join(lines[:1] + lines[-keep:]) + "\n", "text/csv")  # trim: newest rows only
    auctioned = ok(h.get("https://www.treasurydirect.gov/TA_WS/securities/auctioned", params={"format": "json", "days": "30"})).json()
    upcoming = ok(h.get("https://www.treasurydirect.gov/TA_WS/securities/upcoming", params={"format": "json"})).json()

    def slim(rows):  # trim: the fields RATES AUCT reads, empty strings dropped
        return [{k: v for k, v in x.items() if k in TD_FIELDS and v != ""} for x in rows]

    save_json("treasurydirect_auctioned", slim(auctioned[:40]))  # trim: newest 40
    save_json("treasurydirect_upcoming", slim(upcoming))


def record_fomc(h: httpx.Client) -> None:
    html = ok(h.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")).text
    start = html.index("fomc-meeting__month")  # first meeting row of the first year panel
    start = html.rindex("<div", 0, start)
    years = [m.start() for m in re.finditer(r"panel-heading[^>]*>\s*<h4>\s*<a[^>]*>\s*(\d{4}) FOMC Meetings", html)]
    print("fomc year panels at", years)
    # trim: the 2026 panel (first) and the 2027 panel (last)
    save_text("fomc_calendar", html[years[0] - 200: years[1] - 200] + html[years[-1] - 200: years[-1] + 6000], "text/html")


def main() -> int:
    with httpx.Client(headers={"User-Agent": UA}, timeout=40.0, follow_redirects=True) as h:
        steps = {"options": record_options, "futures": record_futures, "deribit": record_deribit, "cftc": record_cftc,
                 "rates": record_rates, "fomc": record_fomc}
        only = [a for a in sys.argv[1:] if a in steps]
        for name, fn in steps.items():
            if not only or name in only:
                print("==", name)
                fn(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
