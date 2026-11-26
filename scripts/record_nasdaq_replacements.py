"""Records the real answers the Nasdaq replacement sources give (2026-11-26), trimmed small, into backend/tests/fixtures.

Why: api.nasdaq.com blocks OpenTerm's client (see docs/DATA_LIMITS.md "Nasdaq blocks OpenTerm"), so these sources stand in:
  - Yahoo screener (keyless, session crumb): the US universe for EQS, one query per Yahoo industry.
  - Yahoo predefined screens (keyless): MOV gainers / losers / most active.
  - Finnhub (FINNHUB_API_KEY): earnings calendar (ERN, BRIEF) and IPO calendar (IPO).
  - Financial Modeling Prep (FMP_API_KEY): earnings announcement dates for GP's earnings markers.

Run from backend/:  uv run python ../scripts/record_nasdaq_replacements.py
Keys are read from the OS keyring (service "openterm") and sent only in request headers / params. Nothing printed or saved
contains a key: only status codes and row counts are printed, and fixtures hold response bodies only.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import httpx
import keyring

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
YH = "https://query2.finance.yahoo.com"
# The industries kept in the trimmed fixtures (each answer is cut to its first ROWS rows, `total` rewritten to match).
INDUSTRIES = ("Consumer Electronics", "Software\u2014Infrastructure", "Semiconductors")  # Yahoo writes an em dash (U+2014)
ROWS = 12
EARNINGS_DAY = "2026-11-24"  # a day with US reports (Thanksgiving week)
IPO_MONTH = ("2026-11-01", "2026-11-30")


def save(name: str, body, note: str) -> None:
    # `recorded` says what the file is (the repo's label for real recordings; `_load` ignores it).
    (OUT / f"{name}.json").write_bytes(json.dumps({"recorded": note, "status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
    print("saved", name)


def yahoo(c: httpx.Client) -> None:
    c.get("https://fc.yahoo.com", headers={"Accept": "*/*"})
    crumb = c.get(f"{YH}/v1/test/getcrumb", headers={"Accept": "*/*"}).text.strip()
    note = f"REAL Yahoo answer recorded {date.today()}, TRIMMED (scripts/record_nasdaq_replacements.py)"

    r = c.get(f"{YH}/v1/finance/screener/instrument/equity/fields",
              params={"lang": "en-US", "region": "US", "category": "sector_industry", "crumb": crumb})
    print("fields", r.status_code)
    body = r.json()
    fields = body["finance"]["result"][0]["fields"]
    labels = fields["industry"]["labels"]
    fields["industry"]["labels"] = [lab for lab in labels if lab["displayName"] in INDUSTRIES]
    save("yahoo_screener_fields", body, note + f": industry labels cut from {len(labels)} to {len(INDUSTRIES)}")

    # The same query the adapter sends (providers/yahoo_screens.py `industry_query`).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from openterm.providers.yahoo_screens import PAGE, industry_query

    for ind in INDUSTRIES:
        r = c.post(f"{YH}/v1/finance/screener", params={"crumb": crumb, "formatted": "false", "lang": "en-US", "region": "US"},
                   json=industry_query(ind, 0))
        res = r.json()["finance"]["result"][0]
        full = res.get("total")
        res["quotes"] = res["quotes"][:ROWS]
        res["total"] = res["count"] = len(res["quotes"])
        print("industry", ind, r.status_code, full, "->", len(res["quotes"]), "page size", PAGE)
        save("yahoo_screener_" + ind.lower().replace("—", "_").replace(" ", "_"), r.json() | {"finance": {"result": [res], "error": None}},
             note + f": first {ROWS} of {full} rows, total rewritten")

    for scr in ("day_gainers", "day_losers", "most_actives"):
        r = c.get(f"{YH}/v1/finance/screener/predefined/saved", params={"scrIds": scr, "count": 100, "formatted": "false"})
        body = r.json()
        res = body["finance"]["result"][0]
        full = len(res.get("quotes") or [])
        res["quotes"] = res["quotes"][:ROWS]
        print(scr, r.status_code, full, "->", len(res["quotes"]))
        save(f"yahoo_predefined_{scr}", body, note + f": first {ROWS} of {full} rows")


def finnhub(c: httpx.Client, key: str) -> None:
    h = {"X-Finnhub-Token": key}
    note = f"REAL Finnhub answer recorded {date.today()} (scripts/record_nasdaq_replacements.py)"
    r = c.get("https://finnhub.io/api/v1/calendar/earnings", params={"from": EARNINGS_DAY, "to": EARNINGS_DAY}, headers=h)
    body = r.json()
    print("finnhub earnings", r.status_code, len(body.get("earningsCalendar") or []))
    save(f"finnhub_earnings_calendar_{EARNINGS_DAY}", body, note)
    r = c.get("https://finnhub.io/api/v1/calendar/ipo", params={"from": IPO_MONTH[0], "to": IPO_MONTH[1]}, headers=h)
    body = r.json()
    print("finnhub ipo", r.status_code, len(body.get("ipoCalendar") or []))
    save(f"finnhub_ipo_calendar_{IPO_MONTH[0][:7]}", body, note)


def fmp(c: httpx.Client, key: str) -> None:
    r = c.get("https://financialmodelingprep.com/stable/earnings", params={"symbol": "AAPL", "apikey": key})
    body = r.json()
    print("fmp earnings AAPL", r.status_code, len(body) if isinstance(body, list) else None)
    save("fmp_real_earnings_aapl", body, f"REAL Financial Modeling Prep answer recorded {date.today()} with a free key "
         "(scripts/record_nasdaq_replacements.py)")


def main() -> None:
    with httpx.Client(timeout=30, headers={"User-Agent": UA, "Accept": "application/json"}, follow_redirects=True) as c:
        yahoo(c)
        fh, fm = keyring.get_password("openterm", "FINNHUB_API_KEY"), keyring.get_password("openterm", "FMP_API_KEY")
        if fh:
            finnhub(c, fh)
        else:
            print("FINNHUB_API_KEY not in the keyring: Finnhub not recorded")
        if fm:
            fmp(c, fm)
        else:
            print("FMP_API_KEY not in the keyring: FMP not recorded")


if __name__ == "__main__":
    main()
