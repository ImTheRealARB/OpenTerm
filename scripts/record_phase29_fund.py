"""Records the Phase 29 fundamentals fixtures from SEC (real answers, no key).

Run from backend/:  uv run python ../scripts/record_phase29_fund.py
1. Adds the sec_parse.EXTRA_TAGS concepts (SCORE / DDIS inputs) to sec_facts_<name>.json. Only the NEW tags are added; the
   tags already recorded stay byte-for-byte as they were, so FA's recorded numbers (and the tests on them) do not move.
2. Records XBRL frames (fund/frames.py CONCEPTS) for CY2021-CY2025 as sec_frame_<tag>_<period>.json, trimmed to the filers in
   sec_company_tickers.json (the only ones fixture mode can match to a ticker) and to the fields OpenTerm reads.
SEC_USER_AGENT from the environment is used when set (never written anywhere).
"""

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "backend"))
SEC_UA = os.environ.get("SEC_USER_AGENT") or "OpenTerm-dev noreply@example.com"
FACTS = {"aapl": 320193, "msft": 789019, "meta": 1326801}
YEARS = range(2021, 2026)


def load(name: str) -> dict:
    return json.loads((OUT / f"{name}.json").read_bytes().decode("utf-8"))


def save(name: str, body) -> None:
    (OUT / f"{name}.json").write_bytes(json.dumps({"status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))


def main() -> int:
    from openterm.fund.frames import CONCEPTS, frame_period
    from openterm.providers.sec_parse import EXTRA_TAGS, FORMS

    with httpx.Client(headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=60.0) as h:
        for name, cik in FACTS.items():
            rec = load(f"sec_facts_{name}")
            gaap = rec["body"]["facts"]["us-gaap"]
            live = h.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()["facts"]["us-gaap"]
            added = []
            for tag in EXTRA_TAGS:
                if tag in gaap or tag not in live:
                    continue
                units = {}
                for unit, facts in live[tag]["units"].items():
                    rows = [f for f in facts if f.get("form") in FORMS and f.get("end", "") >= "2014-01-01"]
                    if rows:
                        units[unit] = rows
                if units:
                    gaap[tag] = {"label": live[tag].get("label"), "units": units}
                    added.append(tag)
            save(f"sec_facts_{name}", rec["body"])
            print(name, "added:", added)

        ciks = {int(v["cik_str"]) for v in load("sec_company_tickers")["body"].values()}
        for tags in CONCEPTS.values():
            for tag, unit, inst in tags:
                for y in YEARS:
                    period = frame_period(y, inst)
                    r = h.get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/{unit}/{period}.json")
                    if r.status_code != 200:
                        print(tag, period, r.status_code)
                        continue
                    body = r.json()
                    keep = [{k: d[k] for k in ("accn", "cik", "entityName", "end", "val") if k in d}
                            for d in body.get("data", []) if int(d.get("cik", 0)) in ciks]
                    save(f"sec_frame_{tag}_{period}", {**{k: body[k] for k in ("taxonomy", "tag", "ccp", "uom", "label") if k in body},
                                                        "pts": len(keep), "data": keep})
                    print(tag, period, len(body.get("data", [])), "->", len(keep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
