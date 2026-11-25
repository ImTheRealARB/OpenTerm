"""Records the keyless fixtures for the Phase 28-32 gap closures (2026-11-25). No key is used, nothing secret is stored.

Run from backend/:  uv run python ../scripts/record_gaps_28_32.py [step ...]      (default: every step)
Steps: sic

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


STEPS = {"sic": rec_sic}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(STEPS):
        STEPS[name]()
