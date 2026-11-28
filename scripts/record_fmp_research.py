"""Records the real Financial Modeling Prep company profile and dividend history for AAPL, trimmed small.

Why: FMP is the keyed last-resort source for DES (`profile`) and DVD / CACS / EVT (`dividends`) behind Nasdaq and Yahoo
(docs/DATA_SOURCES.md "Nasdaq replacements"). The adapter (`providers/fmp.py`) reads these two /stable endpoints; the fixtures are
what its tests and fixture mode replay.

Run from backend/:  uv run python ../scripts/record_fmp_research.py
The key is read from the OS keyring (service "openterm", name FMP_API_KEY) and sent only as the `apikey` query parameter. FMP
has no header form, so the key IS in the request URL: this script never prints or saves a URL, a header or the key. It prints
only the HTTP status, the row count and the field NAMES of the first row, and the saved fixtures hold the response body only.
Before saving it scans every fixture for the key and refuses to write if it finds it.
If the key is missing or a call fails (a paid endpoint answers 402), nothing is saved (a fixture is never made up).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx
import keyring

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
BASE = "https://financialmodelingprep.com/stable"
SYMBOL = "AAPL"
ROWS = 24  # the dividend history is cut to its newest ROWS rows (the live list holds the whole history, newest first)
# fixture name -> FMP path. The adapter reads the same two paths (`providers/fmp.py`).
ENDPOINTS = {"fmp_real_profile_AAPL": "profile", "fmp_real_dividends_AAPL": "dividends"}


def main() -> int:
    key = keyring.get_password("openterm", "FMP_API_KEY")
    if not key:
        print("FMP_API_KEY is not in the keyring: nothing recorded")
        return 1
    note = f"REAL Financial Modeling Prep answer recorded {date.today()} with a free key (scripts/record_fmp_research.py)"
    bodies: dict[str, list] = {}
    with httpx.Client(timeout=30, headers={"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}) as c:
        for name, path in ENDPOINTS.items():
            r = c.get(f"{BASE}/{path}", params={"symbol": SYMBOL, "apikey": key})
            try:
                body = r.json()
            except ValueError:
                body = None
            ok = r.status_code == 200 and isinstance(body, list) and body and isinstance(body[0], dict)
            print(path, r.status_code, len(body) if isinstance(body, list) else None,
                  sorted(body[0]) if ok else "NO ROWS")  # field names only, never values from a failed call
            if not ok:
                print("a call failed: nothing recorded")
                return 1
            bodies[name] = body[:ROWS]
    saved = {name: json.dumps({"recorded": note, "status": 200, "body": body}, separators=(",", ":")) for name, body in bodies.items()}
    if any(key in text for text in saved.values()):
        print("the key appears in a fixture: nothing recorded")
        return 1
    for name, text in saved.items():
        (OUT / f"{name}.json").write_bytes(text.encode("utf-8"))
        print("saved", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
