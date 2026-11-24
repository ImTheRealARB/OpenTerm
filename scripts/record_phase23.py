"""Records the keyless Phase 23 fixtures. No key is used, nothing secret is stored.

Run from backend/:  uv run python ../scripts/record_phase23.py
Writes backend/tests/fixtures/<name>.json as {"status", "body"}, like every other recording.

binance_aggtrades_btcusdt: the newest 1000 aggregated trades of BTCUSDT on Binance spot (`/api/v3/aggTrades?limit=1000`), kept exactly
as Binance sent them (fields a = id, p = price, q = quantity, f / l = first / last trade id, T = time ms, m = buyer is maker, M = ignore).
`m == true` means the AGGRESSOR SOLD. The fixture route in `providers/fixtures.py` (`_route_aggtrades`) replays this one recording
for BTCUSDT only and applies Binance's own `fromId` / `limit` rules to it, so paging works offline without inventing a trade.
"""

import json
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "OpenTerm"


def save_json(name: str, body) -> None:
    (OUT / f"{name}.json").write_bytes(json.dumps({"status": 200, "body": body}, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: json, {len(body)} rows")


def main() -> None:
    r = httpx.get("https://api.binance.com/api/v3/aggTrades", params={"symbol": "BTCUSDT", "limit": 1000},
                  headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)
    r.raise_for_status()  # a 451 here means Binance blocks this country: nothing is invented, the step just stops
    body = r.json()
    assert isinstance(body, list) and len(body) > 100, "unexpected aggTrades answer"
    save_json("binance_aggtrades_btcusdt", body)


if __name__ == "__main__":
    main()
