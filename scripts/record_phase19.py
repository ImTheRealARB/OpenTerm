"""Records the keyless Phase 19 fixtures, one source group per step. No key is used, nothing secret is stored.

Run from backend/:  uv run python ../scripts/record_phase19.py [step ...]      (default: every step that has a recorder)
Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON) or {"status", "text", "content_type"} (text), like every other
recording. Big answers are trimmed; each trim is noted next to the line that makes it. A source that does not answer stops that step
(nothing is invented): the step's function is then built against a doc-shaped fixture and labelled NOT A RECORDING.
"""

import json
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
JSON_ACCEPT = {"User-Agent": UA, "Accept": "application/json"}


def save_json(name: str, body) -> None:
    (OUT / f"{name}.json").write_bytes(json.dumps({"status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: json")


def save_text(name: str, text: str, content_type: str) -> None:
    rec = {"status": 200, "text": text, "content_type": content_type}
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: {len(text)} chars")


def get(url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    r = httpx.get(url, params=params, headers=headers or JSON_ACCEPT, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r


def step2() -> None:
    """GP event markers: Nasdaq earnings history (last four reported quarters)."""
    save_json("nasdaq_earnings_surprise_aapl", get("https://api.nasdaq.com/api/company/AAPL/earnings-surprise").json())


def step4() -> None:
    """SECF: OpenFIGI v3 mapping (keyless, 25 requests / 6 s). One recording holds the per-identifier job result, keyed by `<idType>:<idValue>`."""
    import time

    jobs = [("ID_ISIN", "US0378331005"), ("ID_ISIN", "US5949181045"), ("ID_CUSIP", "037833100"), ("ID_SEDOL", "2046251"),
            ("ID_BB_GLOBAL", "BBG000B9XRY4"), ("ID_ISIN", "US0000000002")]  # the last one is a valid-looking ISIN nobody holds
    r = httpx.post("https://api.openfigi.com/v3/mapping", json=[{"idType": t, "idValue": v} for t, v in jobs],
                   headers={"User-Agent": UA, "Content-Type": "application/json"}, timeout=30)
    print("status", r.status_code, "ratelimit", {k: v for k, v in r.headers.items() if "limit" in k.lower() or "ratelimit" in k.lower()})
    r.raise_for_status()
    results = r.json()
    assert len(results) == len(jobs)
    table = {f"{t}:{v}": res for (t, v), res in zip(jobs, results)}
    for res in table.values():  # keep the fixture small: the first five listings per identifier
        if "data" in res:
            res["data"] = res["data"][:5]
    save_json("openfigi_mapping", table)
    time.sleep(1)


G20 = "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA"
WECO_INDICATORS = {"gdp_growth": "NY.GDP.MKTP.KD.ZG", "inflation": "FP.CPI.TOTL.ZG", "unemployment": "SL.UEM.TOTL.ZS",
                   "debt_gdp": "GC.DOD.TOTL.GD.ZS", "current_account": "BN.CAB.XOKA.GD.ZS"}


def step5() -> None:
    """ECST / WECO / CENB / holidays: World Bank, DBnomics, Nager.Date, FRED policy-rate CSV, ECB and BoC policy rates."""
    wb = "https://api.worldbank.org/v2"
    save_json("worldbank_usa_gdp_growth", get(f"{wb}/country/USA/indicator/NY.GDP.MKTP.KD.ZG", {"format": "json", "per_page": 80}).json())
    save_json("worldbank_usa_gdppc", get(f"{wb}/country/USA/indicator/NY.GDP.PCAP.CD", {"format": "json", "per_page": 80}).json())
    save_json("worldbank_countries_g20", get(f"{wb}/country/{G20}", {"format": "json", "per_page": 60}).json())
    for key, code in WECO_INDICATORS.items():  # mrnev=1: each country's most recent non-empty value, with its own year
        save_json(f"worldbank_g20_{key}", get(f"{wb}/country/{G20}/indicator/{code}", {"format": "json", "mrnev": 1, "per_page": 60}).json())
    save_json("dbnomics_imf_weo_usa_ngdp_rpch", get("https://api.db.nomics.world/v22/series/IMF/WEO:latest/USA.NGDP_RPCH", {"observations": 1, "format": "json"}).json())
    for cc in ("GB", "JP", "HK"):
        r = httpx.get(f"https://date.nager.at/api/v3/PublicHolidays/2026/{cc}", headers=JSON_ACCEPT, timeout=30)
        print(cc, r.status_code, len(r.content))
        if r.status_code == 200:
            save_json(f"nager_{cc.lower()}_2026", r.json())
    # The Fed's DFEDTARU rate reuses the Phase 7 recording fred_csv_DFEDTARU.
    save_json("ecb_policy_rate_mrr", get("https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.MRR_FR.LEV", {"format": "jsondata", "lastNObservations": 5}).json())
    boe = httpx.get("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
                    params={"csv.x": "yes", "Datefrom": "01/Jan/2025", "Dateto": "31/Dec/2030", "SeriesCodes": "IUDBEDR", "CSVF": "TN", "UsingCodes": "Y"},
                    headers={"User-Agent": UA, "Accept": "text/csv,*/*"}, timeout=30)
    print("boe", boe.status_code, boe.text[:200].replace(chr(10), "|"))
    boe.raise_for_status()
    save_text("boe_bank_rate", boe.text, "text/csv")
    save_json("boc_policy_rate", get("https://www.bankofcanada.ca/valet/observations/V39079/json", {"recent": 5}).json())


STEPS = {2: step2, 4: step4, 5: step5}

if __name__ == "__main__":
    wanted = [int(a) for a in sys.argv[1:]] or sorted(STEPS)
    for n in wanted:
        print(f"== step {n}")
        STEPS[n]()
