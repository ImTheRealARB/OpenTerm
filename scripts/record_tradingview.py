"""Record TradingView scanner fixtures for the screener + movers fallback (backend/tests/fixtures/tv_*.json).

Run from backend/:  uv run python ../scripts/record_tradingview.py

Each file keeps the exact request body next to the answer ("request"), and fixture mode only replays a file when a
request's body equals it, so a changed query is a 404 there instead of silently replaying an old answer.
The screener answer is trimmed like nasdaq_screener_trimmed.json: the 250 largest by market cap plus every 30th of
the rest, kept in the original order. Nothing else is edited.
"""

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from openterm.providers.tradingview import EXCHANGES, MOVER_SCANS, SCREENER_SCAN, URL
from openterm.providers.yahoo import UA

OUT = ROOT / "backend" / "tests" / "fixtures"
PROBE = {"columns": ["name"], "filter": [EXCHANGES], "range": [0, 1]}


def trim(body: dict) -> dict:
    rows = body["data"]
    cap = 6  # index of market_cap_basic in SCREENER_COLS
    sub = 10  # index of subtype: preferreds carry the issuer's cap, so they are not ranked by it (see the parser)

    def size(i: int) -> float:
        d = rows[i]["d"]
        return 0 if d[sub] == "preferred" else d[cap] or 0

    top = set(sorted(range(len(rows)), key=size, reverse=True)[:250])
    rest = [i for i in range(len(rows)) if i not in top]
    keep = top | set(rest[::30])
    return {**body, "data": [r for i, r in enumerate(rows) if i in keep], "totalCount": body["totalCount"]}


def record(name: str, request: dict, transform=None) -> None:
    r = httpx.post(URL, json=request, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if transform:
        body = transform(body)
    rec = {"request": request, "status": r.status_code, "body": body}
    path = OUT / f"{name}.json"
    # write_bytes + explicit UTF-8 keeps LF line endings on Windows (see CLAUDE.md gotchas)
    path.write_bytes((json.dumps(rec, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{path.name}: {len(body.get('data') or [])} rows")


if __name__ == "__main__":
    record("tv_screener_trimmed", SCREENER_SCAN, trim)
    for tab, req in MOVER_SCANS.items():
        record(f"tv_movers_{tab.lower()}", req)
    record("tv_probe", PROBE)
