"""Records the keyless Phase 13 fixtures (equity research gaps). No key is used.

Run from backend/:  uv run python ../scripts/record_phase13.py
Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON) or {"status", "text", "content_type"} (text/XML),
like every other recording. Big answers are trimmed the same way the older fixtures were; each trim is listed in
providers/fixtures.py next to the route. SEC calls use SEC_USER_AGENT from the environment when set.
"""

import json
import os
import re
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
SEC_UA = os.environ.get("SEC_USER_AGENT") or "OpenTermResearch research@example.org"
YQ = "https://query1.finance.yahoo.com"
NQ = "https://api.nasdaq.com"
FINRA = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{}.txt"
SHORT_SYMBOLS = {"AAPL", "MSFT", "SPY", "NVDA", "TSLA"}
SHORT_DAYS = ["20261005", "20261006", "20261007", "20261008", "20261009", "20261012", "20261013", "20261014",
              "20261015", "20261016"]
MANAGER = ("BERKSHIRE", 1067983)  # verified against the submissions "name" field below


def save_json(name: str, body) -> None:
    (OUT / f"{name}.json").write_bytes(json.dumps({"status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: json")


def save_text(name: str, text: str, content_type: str) -> None:
    rec = {"status": 200, "text": text, "content_type": content_type}
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: {len(text)} chars")


PEERS = {"aapl": 320193, "msft": 789019, "meta": 1326801}


def record_peer(symbol: str, cik: int) -> int:
    """A relative-valuation peer: SEC facts, Yahoo profile summary, the spark quote (merged into yahoo_spark.json) and its
    row in sec_company_tickers.json. All real answers recorded now; nothing is edited."""
    PEERS[symbol.lower()] = cik
    record_facts([symbol.lower()])
    record_profile(symbol)
    with httpx.Client(headers={"User-Agent": UA}, timeout=30.0, follow_redirects=True) as h:
        spark = h.get(f"{YQ}/v7/finance/spark", params={"symbols": symbol, "range": "1d", "interval": "1d"},
                      headers={"Accept": "application/json"}).json()
        path = OUT / "yahoo_spark.json"
        rec = json.loads(path.read_bytes().decode("utf-8"))
        rows = rec["body"]["spark"]["result"]
        if not any(r["symbol"] == symbol for r in rows):
            rows.extend(spark["spark"]["result"])
            path.write_bytes(json.dumps(rec, indent=1).encode("utf-8"))
        tickers = h.get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": SEC_UA}).json()
        row = next(v for v in tickers.values() if v["ticker"] == symbol)
        path = OUT / "sec_company_tickers.json"
        rec = json.loads(path.read_bytes().decode("utf-8"))
        if not any(v["ticker"] == symbol for v in rec["body"].values()):
            rec["body"][str(len(rec["body"]) + 1)] = row
            path.write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    return 0


def record_facts(only: list[str] | None = None) -> int:
    """Re-records sec_facts_<name> with every tag in sec_parse.TAGS (run after adding FA rows)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from openterm.providers.sec_parse import FORMS, TAGS

    with httpx.Client(headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=60.0) as h:
        for name, cik in ((n, c) for n, c in PEERS.items() if only is None or n in only):
            body = h.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()
            gaap = body["facts"]["us-gaap"]
            kept = {}
            for tag in TAGS:
                if tag not in gaap:
                    continue
                units = {}
                for unit, facts in gaap[tag]["units"].items():
                    rows = [f for f in facts if f.get("form") in FORMS and f.get("end", "") >= "2014-01-01"]
                    if rows:
                        units[unit] = rows
                if units:
                    kept[tag] = {"label": gaap[tag].get("label"), "units": units}
            save_json(f"sec_facts_{name}", {"cik": body["cik"], "entityName": body["entityName"], "facts": {"us-gaap": kept}})
            print(name, "tags:", sorted(kept))
    return 0


def record_profile(symbol: str) -> int:
    """The profile module set DES/RV use, for a peer (yahoo_summary_<symbol>.json)."""
    with httpx.Client(headers={"User-Agent": UA}, timeout=30.0, follow_redirects=True) as h:
        h.get("https://fc.yahoo.com", headers={"Accept": "*/*"})
        crumb = h.get(f"{YQ}/v1/test/getcrumb", headers={"Accept": "*/*"}).text
        r = h.get(f"{YQ}/v10/finance/quoteSummary/{symbol}", headers={"Accept": "application/json"},
                  params={"modules": "assetProfile,summaryDetail,defaultKeyStatistics,price", "crumb": crumb})
        r.raise_for_status()
        save_json(f"yahoo_summary_{symbol.lower()}", r.json())
    return 0


def main() -> int:
    if "--facts" in sys.argv:
        return record_facts()
    if "--peer" in sys.argv:
        i = sys.argv.index("--peer")
        return record_peer(sys.argv[i + 1], int(sys.argv[i + 2]))
    if "--profile" in sys.argv:
        return record_profile(sys.argv[sys.argv.index("--profile") + 1])
    with httpx.Client(headers={"User-Agent": UA}, timeout=30.0, follow_redirects=True) as h:
        h.get("https://fc.yahoo.com", headers={"Accept": "*/*"})
        crumb = h.get(f"{YQ}/v1/test/getcrumb", headers={"Accept": "*/*"}).text
        accept = {"Accept": "application/json"}

        def summary(sym: str, mods: str) -> dict:
            r = h.get(f"{YQ}/v10/finance/quoteSummary/{sym}", params={"modules": mods, "crumb": crumb}, headers=accept)
            r.raise_for_status()
            return r.json()

        save_json("yahoo_summary_aapl_estimates", summary("AAPL", "earningsTrend,earningsHistory"))
        ratings = summary("AAPL", "recommendationTrend,upgradeDowngradeHistory,financialData")
        ratings["quoteSummary"]["result"][0]["upgradeDowngradeHistory"]["history"] = (
            ratings["quoteSummary"]["result"][0]["upgradeDowngradeHistory"]["history"][:40])  # trim: newest 40
        save_json("yahoo_summary_aapl_ratings", ratings)
        save_json("yahoo_summary_aapl_profile", summary("AAPL", "assetProfile"))
        save_json("yahoo_summary_aapl_keystats", summary("AAPL", "defaultKeyStatistics,summaryDetail"))
        save_json("yahoo_summary_spy_fund", summary("SPY", "topHoldings,fundProfile,quoteType"))
        r = h.get(f"{YQ}/v8/finance/chart/AAPL", params={"range": "max", "interval": "1mo", "events": "div,splits"},
                  headers=accept)
        r.raise_for_status()
        save_json("yahoo_chart_aapl_events", r.json())

        nh = {"Accept": "application/json, text/plain, */*"}
        for name, path, params in [
            ("nasdaq_dividends_aapl", "/api/quote/AAPL/dividends", {"assetclass": "stocks"}),
            ("nasdaq_ipo_2026-10", "/api/ipo/calendar", {"date": "2026-10"}),
            ("nasdaq_shortinterest_aapl", "/api/quote/AAPL/short-interest", {"assetClass": "stocks"}),
            ("nasdaq_analyst_aapl", "/api/analyst/AAPL/ratings", {}),
        ]:
            r = h.get(f"{NQ}{path}", params=params, headers=nh)
            r.raise_for_status()
            save_json(name, r.json())

        for day in SHORT_DAYS:  # trimmed to the header and five symbols
            r = h.get(FINRA.format(day))
            if r.status_code != 200:
                print(f"finra {day}: HTTP {r.status_code}, skipped")
                continue
            lines = r.text.splitlines()
            keep = [lines[0]] + [ln for ln in lines[1:] if ln.split("|")[1:2] and ln.split("|")[1] in SHORT_SYMBOLS]
            save_text(f"finra_shvol_{day}", "\n".join(keep) + "\n", "text/plain")

        sh = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}
        mf = h.get("https://www.sec.gov/files/company_tickers_mf.json", headers=sh).json()
        wanted = {"SPY", "QQQ", "DIA", "IWM", "VOO"}
        mf["data"] = [row for row in mf["data"] if row[3] in wanted]  # trim: five ETFs
        save_json("sec_company_tickers_mf", mf)

        def subs(cik: int) -> dict:
            body = h.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=sh).json()
            rec = body["filings"]["recent"]
            for k, v in rec.items():  # trim: first 60 rows, as the older sec_subs fixtures
                rec[k] = v[:60]
            body["filings"]["files"] = []
            return body

        spy = subs(884394)
        save_json("sec_subs_spy_trust", spy)
        rec = spy["filings"]["recent"]
        acc = next(a for a, f in zip(rec["accessionNumber"], rec["form"]) if f == "NPORT-P")
        xml = h.get(f"https://www.sec.gov/Archives/edgar/data/884394/{acc.replace('-', '')}/primary_doc.xml",
                    headers=sh).text
        blocks = re.findall(r"<invstOrSec>.*?</invstOrSec>", xml, flags=re.S)
        head, tail = xml[: xml.index(blocks[0])], xml[xml.rindex("</invstOrSec>") + len("</invstOrSec>"):]
        save_text(f"sec_nport_spy_{acc}", head + "".join(blocks[:60]) + tail, "application/xml")  # trim: 60 holdings
        print("nport holdings in full filing:", len(blocks))

        bk = subs(MANAGER[1])
        print("manager:", bk["name"])
        save_json("sec_subs_berkshire", bk)
        recb = bk["filings"]["recent"]
        accs = [a for a, f in zip(recb["accessionNumber"], recb["form"]) if f == "13F-HR"][:2]
        for a in accs:
            base = f"https://www.sec.gov/Archives/edgar/data/{MANAGER[1]}/{a.replace('-', '')}"
            idx = h.get(f"{base}/index.json", headers=sh).json()
            save_json(f"sec_index_{a}", idx)
            items = [i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith(".xml")]
            print("13F files:", items)
            table = next(n for n in items if n != "primary_doc.xml")
            save_text(f"sec_13f_{a}", h.get(f"{base}/{table}", headers=sh).text, "application/xml")
            save_text(f"sec_13f_primary_{a}", h.get(f"{base}/primary_doc.xml", headers=sh).text, "application/xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
