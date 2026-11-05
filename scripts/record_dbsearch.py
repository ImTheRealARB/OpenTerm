"""Record the DBnomics answers behind DBSRCH into backend/tests/fixtures (real answers, keyless; run once, commit the files).

    python scripts/record_dbsearch.py

Each file is `{"status": 200, "body": <the API's JSON, unchanged>}`. The request parameters here must match what
`providers/worldstats.py` sends (same page sizes, `observations=0`, `metadata=0`), because `providers/fixtures.py` routes on host, path and `q`.
The API resets connections now and then, so every call is retried a few times with a pause.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.db.nomics.world/v22"
FIXTURES = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"
DATASET_PAGE = 20  # keep equal to worldstats.DBN_DATASET_PAGE
SERIES_PAGE = 30  # keep equal to worldstats.DBN_SERIES_PAGE


def fetch(url: str) -> tuple[int, object]:
    last: Exception | None = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OpenTerm", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as f:
                return f.status, json.loads(f.read())
        except Exception as e:  # noqa: BLE001  (a recorder: any failure means wait and retry)
            last = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"gave up on {url}: {last}")


def save(name: str, url: str) -> None:
    status, body = fetch(url)
    (FIXTURES / f"{name}.json").write_text(json.dumps({"status": status, "body": body}, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(name, status, len(json.dumps(body)), "bytes")


def datasets(q: str) -> str:
    return f"{BASE}/search?" + urllib.parse.urlencode({"q": q, "limit": DATASET_PAGE, "offset": 0})


def series(provider: str, dataset: str, q: str) -> str:
    return f"{BASE}/series/{provider}/{dataset}?" + urllib.parse.urlencode({"q": q, "limit": SERIES_PAGE, "offset": 0, "observations": 0, "metadata": 0})


if __name__ == "__main__":
    save("dbnomics_search_france_inflation", datasets("france inflation"))
    save("dbnomics_search_oecd_unemployment", datasets("OECD unemployment"))
    save("dbnomics_search_nomatch", datasets("zzqxjw"))
    save("dbnomics_series_bdf_icp_france_inflation", series("BDF", "ICP", "france inflation"))
    save("dbnomics_series_oecd_nrr_oecd_unemployment", series("OECD", "DSD_TAXBEN_NRR@DF_NRR", "OECD unemployment"))
