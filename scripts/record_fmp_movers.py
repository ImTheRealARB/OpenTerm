"""Records the real Financial Modeling Prep "movers" answers (biggest gainers, biggest losers, most actives), trimmed small.

Why: FMP is the keyed last-resort source for MOV after Nasdaq, TradingView and the Yahoo screens (docs/DATA_SOURCES.md
"Nasdaq replacements"). The adapter (`providers/fmp.py`) reads these three /stable endpoints; the fixtures are what its tests and
fixture mode replay.

Run from backend/:  uv run python ../scripts/record_fmp_movers.py
The key is read from the OS keyring (service "openterm", name FMP_API_KEY) and sent only as the `apikey` query parameter. FMP
has no header form, so the key IS in the request URL: this script never prints or saves a URL, a header or the key. It prints
only the HTTP status, the row count and the field NAMES of the first row, and the saved fixtures hold the response body only.
If the key is missing or a call fails, nothing is saved (a fixture is never made up).
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
ROWS = 12  # each answer is cut to its first ROWS rows (the live lists hold about 50)
# MOV tab -> FMP path -> fixture name. The adapter has the same table (`providers/fmp.py` MOVER_PATHS).
ENDPOINTS = {"GAINERS": "biggest-gainers", "LOSERS": "biggest-losers", "ACTIVE": "most-actives"}


def main() -> int:
    key = keyring.get_password("openterm", "FMP_API_KEY")
    if not key:
        print("FMP_API_KEY is not in the keyring: nothing recorded")
        return 1
    note = f"REAL Financial Modeling Prep answer recorded {date.today()} with a free key (scripts/record_fmp_movers.py)"
    bodies: dict[str, list] = {}
    with httpx.Client(timeout=30, headers={"User-Agent": "OpenTerm/0.1", "Accept": "application/json"}) as c:
        for tab, path in ENDPOINTS.items():
            r = c.get(f"{BASE}/{path}", params={"apikey": key})
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
            bodies[tab] = body[:ROWS]
    for tab, body in bodies.items():
        name = f"fmp_real_movers_{tab.lower()}"
        (OUT / f"{name}.json").write_bytes(
            json.dumps({"recorded": note, "status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
        print("saved", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
