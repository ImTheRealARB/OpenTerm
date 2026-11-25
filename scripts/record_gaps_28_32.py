"""Records the keyless fixtures for the Phase 28-32 gap closures (2026-11-25). No key is used, nothing secret is stored.

Run from backend/:  uv run python ../scripts/record_gaps_28_32.py [step ...]      (default: every step)
Steps: sic bio ets

Writes backend/tests/fixtures/<name>.json as {"status", "text", "content_type"} (XML / HTML) or {"status", "body"} (JSON), like every other
recording. Big answers are TRIMMED to the few companies the other fixtures already hold (Apple, Microsoft, Berkshire, Meta) and each trim is
noted next to the line that makes it; a trimmed file says so in its `note` field. The SEC asks for a User-Agent with a contact: this script
reads SEC_USER_AGENT from the environment (never printed, never written to a file) and keeps under 10 requests a second.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = {"User-Agent": os.environ.get("SEC_USER_AGENT") or "OpenTerm-dev noreply@example.com", "Accept-Encoding": "gzip, deflate"}

# The four filers every SEC fixture of Phase 29 holds, with their SIC code at the SEC (checked 2026-11-25).
SIC_FILERS = {320193: 3571, 789019: 7372, 1067983: 6331, 1326801: 7370}


def save_text(name: str, text: str, content_type: str, note: str | None = None) -> None:
    rec = {"status": 200, "text": text, "content_type": content_type}
    if note:
        rec["note"] = note
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


def get(url: str, params: dict | None = None) -> httpx.Response:
    r = httpx.get(url, params=params, headers=UA, timeout=60, follow_redirects=True)
    r.raise_for_status()
    time.sleep(0.4)
    return r


def rec_sic() -> None:
    """SIC code list page (TRIM: only the table rows of the four codes) and one EDGAR company-browser page per code (TRIM: only the four filers' entries)."""
    page = get("https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list").text
    head = page[: page.index("<table")]
    table = page[page.index("<table"): page.index("</table>") + 8]
    rows = re.findall(r"<tr>.*?</tr>", table, re.S)
    keep = [rows[0]] + [r for r in rows[1:] if int(re.search(r"<td>\s*(\d+)\s*</td>", r).group(1)) in set(SIC_FILERS.values())]
    assert len(keep) == 1 + len(set(SIC_FILERS.values())), "a code is missing from the SEC list"
    # The page head is menus: keep only a minimal real wrapper so the parser meets the table the way it does live.
    save_text("sec_sic_list", "<html><body>" + table[: table.index("<tbody>") + 7] + "".join(keep) + "</tbody></table></body></html>",
              "text/html; charset=utf-8", "TRIMMED RECORDING: the SEC SIC list page cut to the table rows of SIC 3571 6331 7370 7372")
    del head
    for cik, code in SIC_FILERS.items():
        found = None
        for start in range(0, 3000, 100):
            r = get("https://www.sec.gov/cgi-bin/browse-edgar", {"action": "getcompany", "SIC": str(code), "type": "10-K", "owner": "exclude",
                                                               "output": "atom", "count": "100", "start": str(start)})
            entries = re.findall(r"<entry>.*?</entry>", r.text, re.S)
            hit = [e for e in entries if f"<cik>{cik:010d}</cik>" in e]
            if hit:
                found = (r.text[: r.text.index("<entry>")], hit[0], r.text[r.text.rindex("</entry>") + 8:])
                break
            if len(entries) < 100:
                break
        assert found, f"CIK {cik} not listed under SIC {code}"
        save_text(f"sec_sic_{code}", found[0] + found[1] + found[2], "application/atom+xml",
                  f"TRIMMED RECORDING: the EDGAR company-browser Atom page for SIC {code}, cut to the one entry of CIK {cik}")


ETS_HOLDER = "alcoa"  # same company as the ESG (EPA) fixture, so the two emissions panels can be compared in fixture mode
ETS_YEAR = 2024


def rec_ets() -> None:
    """EU ETS: the Union Registry's public download list, the Operators Daily extract (TRIM: header + the installations whose account holder
    contains "alcoa") and the Verified Emissions workbook of one year (TRIM: one sheet, only the rows of those installations)."""
    import base64
    import csv
    import gzip
    import io
    import re as _re
    import zipfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from openterm.macrod import xlsx

    plain = {"User-Agent": "OpenTerm-dev (research tool)", "Accept": "application/json"}
    lst = httpx.get("https://union-registry-data.ec.europa.eu/api/data-download", headers=plain, timeout=60).raise_for_status().json()
    by_name = {x["name"]: x["url"] for x in lst}
    keep_names = ("Operators Daily", f"Verified Emissions for {ETS_YEAR}")
    (OUT / "eu_ets_data_download.json").write_text(json.dumps(
        {"status": 200, "body": [x for x in lst if x["name"] in keep_names], "note": "TRIMMED RECORDING: the list cut to the two extracts the app reads"},
        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    ops_raw = httpx.get(by_name["Operators Daily"], headers=plain, timeout=120).raise_for_status().content
    rows = list(csv.reader(io.StringIO(gzip.decompress(ops_raw).decode("utf-8"))))
    head = rows[0]
    hi, ri, ii = head.index("ACCOUNT_HOLDER_NAME"), head.index("REGISTRY_CODE"), head.index("INSTALLATION_IDENTIFIER")
    mine = [r for r in rows[1:] if ETS_HOLDER in (r[hi] or "").lower()]
    assert mine, "no installation matched"
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([head, *mine])
    (OUT / "eu_ets_operators_daily.json").write_text(json.dumps({"status": 200, "content_type": "application/octet-stream", "b64": base64.b64encode(
        gzip.compress(buf.getvalue().encode("utf-8"))).decode("ascii"), "note": f"TRIMMED RECORDING: Operators Daily cut to account holders containing {ETS_HOLDER!r}"},
        indent=1) + "\n", encoding="utf-8")
    want = {(r[ri], r[ii]) for r in mine}
    time.sleep(0.5)
    wb = httpx.get(by_name[f"Verified Emissions for {ETS_YEAR}"], headers=plain, timeout=180, follow_redirects=True).raise_for_status().content
    grid = xlsx.read_sheet(wb, "data")
    hdr = next(i for i, r in enumerate(grid) if r and r[0] == "REGISTRY_CODE")
    c_reg, c_inst = grid[hdr].index("REGISTRY_CODE"), grid[hdr].index("INSTALLATION_IDENTIFIER")
    keep_rows = {hdr + 1} | {i + 1 for i in range(hdr + 1, len(grid)) if len(grid[i]) > c_inst and (str(grid[i][c_reg]), str(int(grid[i][c_inst])
                              if isinstance(grid[i][c_inst], float) else grid[i][c_inst])) in want}
    small = xlsx.trim_workbook(wb, ["data"])
    z = zipfile.ZipFile(io.BytesIO(small))
    path = xlsx._sheet_path(z, "data")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for info in z.infolist():
            data = z.read(info.filename)
            if info.filename == path:
                xml = data.decode("utf-8")
                xml = _re.sub(r"<row [^>]*?r=\"(\d+)\"[^>]*?(?:/>|>.*?</row>)", lambda m: m.group(0) if int(m.group(1)) in keep_rows or int(m.group(1)) <= 20 else "", xml, flags=_re.DOTALL)
                data = xml.encode("utf-8")
            w.writestr(info, data)
    small = out.getvalue()
    check = xlsx.read_sheet(small, "data")
    assert any(r and r[0] == "REGISTRY_CODE" for r in check) and len(check) > 21, "trimmed workbook lost its rows"
    (OUT / f"eu_ets_verified_{ETS_YEAR}.json").write_text(json.dumps({"status": 200, "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "b64": base64.b64encode(small).decode("ascii"), "note": f"TRIMMED RECORDING: Verified Emissions {ETS_YEAR} cut to the data sheet and the rows of the installations in eu_ets_operators_daily"},
        indent=1) + "\n", encoding="utf-8")
    print("wrote eu_ets_*", len(mine), "installations,", len(small) // 1024, "KB workbook")


def rec_bio() -> None:
    """BIO boards: the SEC full-text search for the phrase "Timothy Cook" in DEF 14A proxies, 2023-2025 (TRIM: first 25 hits, no filter counts)."""
    for attempt in range(4):  # the SEC search answers an odd HTTP 500; the same request works a moment later
        r = httpx.get("https://efts.sec.gov/LATEST/search-index", params={"q": '"Timothy Cook"', "forms": "DEF 14A", "dateRange": "custom",
                                                                          "startdt": "2023-01-01", "enddt": "2025-12-31"}, headers=UA, timeout=40)
        if r.status_code < 500:
            break
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()
    body = r.json()
    body["hits"]["hits"] = body["hits"]["hits"][:25]  # TRIM
    body.pop("aggregations", None)  # TRIM
    (OUT / "fts_bio_proxy_timothy_cook.json").write_text(json.dumps({"status": 200, "body": body}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote fts_bio_proxy_timothy_cook")


STEPS = {"sic": rec_sic, "bio": rec_bio, "ets": rec_ets}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STEPS):
        STEPS[name]()
