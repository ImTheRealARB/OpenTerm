"""Record REAL answers from the keyless US government APIs (USASpending, Federal Register) and the real "bad key" answers of api.data.gov.

Run once from the repo root:  cd backend; uv run python ../scripts/record_usgov.py
Writes backend/tests/fixtures/usasp_real_*.json, fedreg_real_*.json and keytest_datagov_*.json. Nothing here needs a key: the api.data.gov
answers are what the gateway says to NO key and to a deliberately made-up key. FEC and Congress.gov success answers are NOT recorded (no key):
those fixtures are doc-shaped and say so inside the file.
"""

from __future__ import annotations

import json
import pathlib
import time

import httpx

OUT = pathlib.Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"
UA = {"User-Agent": "OpenTerm/0 (open-source terminal; research use)", "Accept": "application/json"}
WINDOW = [{"start_date": "2023-10-01", "end_date": "2026-11-05"}]  # the last three US fiscal years up to today
CONTRACTS = ["A", "B", "C", "D"]


def save(name: str, r: httpx.Response, trim=None) -> None:
    body = r.json()
    if trim:
        body = trim(body)
    rec = {"status": r.status_code, "recorded": f"{time.strftime('%Y-%m-%d')}, real answer", "body": body}
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(name, r.status_code, len(json.dumps(body)))


def main() -> None:
    with httpx.Client(headers=UA, timeout=90) as c:
        base = "https://api.usaspending.gov/api/v2/search"
        for tag, words in (("lockheed", ["lockheed martin"]), ("none", ["zzqxqx nonexistent"])):
            f = {"keywords": words, "time_period": WINDOW, "award_type_codes": CONTRACTS}
            save(f"usasp_real_recipient_{tag}", c.post(f"{base}/spending_by_category/recipient/", json={"filters": f, "limit": 10, "page": 1}))
            fields = ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency", "Start Date", "End Date", "Description", "generated_internal_id"]
            save(f"usasp_real_awards_{tag}", c.post(f"{base}/spending_by_award/", json={
                "filters": f, "fields": fields, "sort": "Award Amount", "order": "desc", "limit": 15, "page": 1}))
        save("usasp_real_agency", c.post(f"{base}/spending_by_category/awarding_agency/", json={
            "filters": {"time_period": WINDOW}, "limit": 15, "page": 1}))
        f = {"time_period": WINDOW, "award_type_codes": CONTRACTS, "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}]}
        save("usasp_real_agency_recipients", c.post(f"{base}/spending_by_category/recipient/", json={"filters": f, "limit": 10, "page": 1}))
        fr = "https://www.federalregister.gov/api/v1/documents.json"
        fields = [("fields[]", x) for x in ("title", "type", "agency_names", "publication_date", "abstract", "document_number", "html_url")]
        save("fedreg_real_semiconductor", c.get(fr, params=[("conditions[term]", "semiconductor"), ("order", "newest"), ("per_page", "15"), *fields]))
        save("fedreg_real_latest", c.get(fr, params=[("order", "newest"), ("per_page", "15"), *fields]))
        save("fedreg_real_none", c.get(fr, params=[("conditions[term]", "zzqxqx nonexistent"), ("order", "newest"), ("per_page", "15"), *fields]))
        save("fedreg_real_rules_only", c.get(fr, params=[("conditions[term]", "semiconductor"), ("conditions[type][]", "RULE"), ("order", "newest"), ("per_page", "15"), *fields]))
        # api.data.gov gateway answers: no key, and a made-up key sent in the X-Api-Key header (how OpenTerm sends keys: never in the URL)
        for host, path in (("api.open.fec.gov", "/v1/candidates/search/"), ("api.congress.gov", "/v3/bill")):
            tag = "fec" if "fec" in host else "congress"
            save(f"keytest_datagov_{tag}_missing", c.get(f"https://{host}{path}"))
            save(f"keytest_datagov_{tag}_invalid", c.get(f"https://{host}{path}", headers={"X-Api-Key": "invalid-key-for-test"}))


if __name__ == "__main__":
    main()
