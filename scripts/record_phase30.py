"""Records the Phase 30 fixtures (MMR, NOWC, ECFC, FOMC, TSYS, AGRI, WPE, WCRS, and the FRED series behind WB, CRPR, RE, BTMM, ECFC SEP).
No key is used and nothing secret is stored. EIA and NASS need keys: their fixtures are DOC-SHAPED (written from the API docs, labelled
NOT A RECORDING in the file and on screen).

Run from backend/:  uv run python ../scripts/record_phase30.py [group ...]
Groups: mmr nowc spf imf oecd fomc tsy wasde wpe wcrs fred docshape        (default: all)

Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON), {"status", "text", "content_type"} (text) or {"status", "b64",
"content_type"} (binary), and merges each request into tests/fixtures/phase30_manifest.json (canonical request -> fixture name; see
providers/macrod_fixtures.py). Big answers are trimmed and each trim is noted where it is made. A source that does not answer stops that
recording (nothing is invented). FRED ids that answer 404 are printed so boards.py can drop them.
"""

import base64
import json
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from openterm.derivs import fut_parse
from openterm.macrod import boards as B
from openterm.macrod import parse as P
from openterm.macrod import xlsx
from openterm.providers import etf as E
from openterm.providers import macrod as M
from openterm.providers.macrod_fixtures import canonical

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
MAN = OUT / "phase30_manifest.json"
UA = {"User-Agent": M.UA}
client = httpx.Client(headers=UA, timeout=90, follow_redirects=True)
manifest: dict[str, str] = json.loads(MAN.read_text(encoding="utf-8")) if MAN.exists() else {}


def _write(name: str, rec: dict) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


def get(url: str, params: dict | None = None) -> httpx.Response:
    r = client.get(url, params=params)
    r.raise_for_status()
    time.sleep(0.4)
    return r


def rec_json(name: str, url: str, params: dict | None = None, body=None) -> object:
    if body is None:
        body = get(url, params).json()
    _write(name, {"status": 200, "body": body})
    manifest[canonical(url, params)] = name
    return body


def rec_text(name: str, url: str, params: dict | None = None, text: str | None = None, ctype: str = "text/plain") -> str:
    if text is None:
        r = get(url, params)
        text, ctype = r.content.decode("utf-8-sig", "replace"), r.headers.get("content-type", ctype)
    _write(name, {"status": 200, "text": text, "content_type": ctype})
    manifest[canonical(url, params)] = name
    return text


def rec_bin(name: str, url: str, data: bytes, ctype: str) -> None:
    _write(name, {"status": 200, "b64": base64.b64encode(data).decode("ascii"), "content_type": ctype})
    manifest[canonical(url)] = name


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def mmr() -> None:
    for g, k in M.NYFED_TYPES:
        rec_json(f"nyfed_{k}", M.nyfed_url(g, k))
    rec_text("ecb_estr", M.ESTR_URL, {"format": "csvdata", "lastNObservations": str(M.RATE_DAYS)})
    rec_text("boe_sonia", M.BOE_URL, M.boe_params("IUDSOIA"))


def nowc() -> None:
    data = get(M.GDPNOW_URL).content
    # TRIM: the 11 MB workbook keeps only the two sheets NOWC reads (the shared-string table stays whole so indices do not move)
    small = xlsx.trim_workbook(data, ["CurrentQtrEvolution", "TrackingArchives"])
    P.gdpnow(small)  # must still parse
    rec_bin("atlfed_gdpnow_trimmed", M.GDPNOW_URL, small, XLSX)


def spf() -> None:
    for k, (fname, *_rest) in P.SPF_FILES.items():
        data = get(M.SPF_BASE + fname).content
        P.spf(data)
        rec_bin(f"philfed_spf_{k.lower()}", M.SPF_BASE + fname, data, XLSX)


def imf() -> None:
    countries = tuple(c for c, _ in B.ECFC_COUNTRIES)
    for ind, _ in B.IMF_INDICATORS:
        url = M.imf_url(ind, countries)
        body = get(url).json()
        # TRIM: DataMapper answers every country regardless of the path; keep the board's countries and 2015 onward
        vals = body["values"][ind]
        body["values"][ind] = {c: {y: v for y, v in vals[c].items() if int(y) >= 2015} for c in countries if c in vals}
        rec_json(f"imf_dm_{ind.lower()}", url, body=body)


def oecd() -> None:
    url = M.oecd_url(tuple(c for c, _ in B.ECFC_COUNTRIES), tuple(m for m, _ in B.OECD_MEASURES))
    text = rec_text("oecd_eo", url, {"startPeriod": str(date.today().year - 2), "format": "csvfile"})
    print("  OECD pairs:", len(P.oecd_csv(text)))


def fomc() -> None:
    page = get(fut_parse_url := "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm").text
    del fut_parse_url
    today = date.today().isoformat()
    past = [d for d in fut_parse.parse_fomc(page) if d <= today][-2:]
    for d in past:
        url = M.FED_PR.format(d=d.replace("-", ""))
        html = get(url).content.decode("utf-8-sig", "replace")
        # TRIM: the page cut to its article body (from the 8-column div to the implementation-note link)
        i = html.find('<div class="col-xs-12 col-sm-8 col-md-8">')
        j = html.find("Implementation Note", i)
        cut = html[i:html.find("</p>", j) + 4] if i >= 0 and j > i else html
        P.fomc_statement(cut)
        rec_text(f"fed_statement_{d.replace('-', '')}", url, text=cut, ctype="text/html")


def tsy() -> None:
    days = 90
    body = get(f"{M.TD_BASE}/auctioned", {"format": "json", "days": str(days)}).json()
    rec_json("td_securities_auctioned", f"{M.TD_BASE}/auctioned", {"format": "json", "days": str(days)}, body=body)
    # NOT recorded here: `upcoming?format=json` is the same request RATES AUCT makes; its Phase 14 recording answers both


def wasde() -> None:
    page = rec_text("wasde_page", M.WASDE_PAGE, {"locale": "en"})
    links = P.wasde_links(page)
    url = next(r["xml"] for r in links if "xml" in r)
    xml = get(url).content.decode("utf-8-sig", "replace")
    # TRIM: keep only the three US sub-reports AGRI reads (sr11 wheat, sr12 corn, sr15 soybeans), verbatim
    parts = [m.group(0) for sr in ("sr11", "sr12", "sr15") for m in [re.search(rf"<{sr}>.*?</{sr}>", xml, re.S)] if m]
    head = xml[:xml.find(">", xml.find("<Report")) + 1]
    small = head + "".join(parts) + "</Report>"
    P.wasde(small)
    rec_text("wasde_xml_trimmed", url, text=small, ctype="text/xml")


def wpe() -> None:
    # Yahoo needs its cookie and a crumb (getcrumb answers 406 to Accept: application/json)
    s = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30, follow_redirects=True)
    s.get("https://fc.yahoo.com")
    crumb = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb").text
    out = {}
    for _, sym in B.WPE_ETFS:
        r = s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}", params={"modules": E.VALUATION_MODULES, "crumb": crumb})
        if r.status_code != 200:
            print("  WPE skip", sym, r.status_code)
            continue
        body = r.json()
        res = body["quoteSummary"]["result"][0]
        # TRIM: topHoldings keeps only equityHoldings (the holdings list and sector weights are not used)
        th = res.get("topHoldings") or {}
        res["topHoldings"] = {"equityHoldings": th.get("equityHoldings", {})}
        out[sym] = body
        print("  WPE", sym, P.etf_valuation(body))
        time.sleep(0.6)
    _write("yahoo_etfval_wpe", {"status": 200, "body": out})


def wcrs() -> None:
    start = (date.today() - timedelta(days=370)).isoformat()
    params = {"from": start, "base": "USD", "quotes": ",".join(B.WCRS_CCYS), "providers": "ecb"}
    body = get("https://api.frankfurter.dev/v2/rates", params).json()
    rec_json("frankfurter_usd_wcrs", "https://api.frankfurter.dev/v2/rates", params, body=body)


def fred() -> None:
    start = (date.today() - timedelta(days=11 * 365)).isoformat()
    missing = []
    for sid in B.ALL_FRED:
        if (OUT / f"fred_csv_{sid}.json").exists():
            continue
        r = client.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid, "cosd": start})
        time.sleep(0.5)
        if r.status_code != 200 or not r.text.startswith("observation_date"):
            missing.append(f"{sid} ({r.status_code})")
            continue
        # TRIM: daily series keep their last ~11 years (the boards read at most 10 years)
        _write(f"fred_csv_{sid}", {"status": 200, "content_type": "application/csv", "text": r.text})
    print("FRED NOT FOUND:", missing or "none")


def docshape() -> None:
    note = "DOC-SHAPED, NOT A RECORDING: written from the API documentation on 2026-11-24; the values are invented. Record a real answer with the first key."
    for sid, label, unit in B.NRGF:
        base = {"PET.WCESTUS1.W": 421000, "PET.W_EPC0_SAX_YCUOK_MBBL.W": 23000, "PET.WCSSTUS1.W": 404000, "PET.WGTSTUS1.W": 210000,
                "PET.WDISTUS1.W": 115000, "PET.WPULEUS3.W": 89.5, "PET.WCRFPUS2.W": 13400, "NG.NW2_EPG0_SWO_R48_BCF.W": 3900}[sid]
        day = date(2026, 11, 13)
        data = [{"period": (day - timedelta(weeks=i)).isoformat(), "series-description": label.title(), "value": round(base * (1 + 0.003 * ((i * 7) % 11 - 5)), 1),
                 "units": unit} for i in range(104)]
        url = M.EIA_SERIES.format(sid=sid)
        _write(f"eia_docshape_{sid.replace('.', '_').lower()}", {"status": 200, "note": note,
               "body": {"response": {"total": 104, "frequency": "weekly", "data": data}, "request": {"command": f"/v2/seriesid/{sid}"}}})
        manifest[canonical(url, {"length": "104"})] = f"eia_docshape_{sid.replace('.', '_').lower()}"
    for crop in B.AGRI_CROPS:
        rows = []
        for w in range(6):
            we = (date(2026, 9, 27) - timedelta(weeks=w)).isoformat()
            for cond, pct in (("EXCELLENT", 18), ("GOOD", 47), ("FAIR", 23), ("POOR", 8), ("VERY POOR", 4)):
                rows.append({"commodity_desc": crop, "short_desc": f"{crop} - CONDITION, MEASURED IN PCT {cond}", "unit_desc": f"PCT {cond}",
                             "week_ending": we, "year": 2026, "Value": str(pct + (w % 3) - 1 if cond in ("GOOD", "FAIR") else pct)})
        params = {"source_desc": "SURVEY", "sector_desc": "CROPS", "commodity_desc": crop, "statisticcat_desc": "CONDITION",
                  "agg_level_desc": "NATIONAL", "year": "2026", "format": "JSON"}
        name = f"nass_docshape_condition_{crop.lower()}_2026"
        _write(name, {"status": 200, "note": note, "body": {"data": rows}})
        manifest[canonical(M.NASS_URL, params)] = name


GROUPS = {"mmr": mmr, "nowc": nowc, "spf": spf, "imf": imf, "oecd": oecd, "fomc": fomc, "tsy": tsy, "wasde": wasde, "wpe": wpe,
          "wcrs": wcrs, "fred": fred, "docshape": docshape}

if __name__ == "__main__":
    for g in sys.argv[1:] or list(GROUPS):
        print("==", g, datetime.now(UTC).strftime("%H:%M:%S"))
        try:
            GROUPS[g]()
        except Exception as e:  # one source down must not lose the others' recordings
            print(f"  FAILED {g}: {type(e).__name__} {str(e)[:200]}")
        MAN.write_text(json.dumps(dict(sorted(manifest.items())), indent=1) + "\n", encoding="utf-8")
