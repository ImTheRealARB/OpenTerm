"""Records the keyless Phase 12 (BT) fixtures: Yahoo 10-year daily bars and Binance BTCUSDT klines + funding.

Run from backend/:  uv run python ../scripts/record_phase12.py
Writes backend/tests/fixtures/<name>.json as {"status", "body"} like every other recording. No key is used.
"""

import json
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}"

RECORDINGS = [
    *[(f"yahoo_chart_{name}_10y_1d", YAHOO.format(sym), {"range": "10y", "interval": "1d", "includePrePost": "false"})
      for name, sym in [("aapl", "AAPL"), ("spy", "SPY"), ("reliance", "RELIANCE.NS"), ("nsei", "^NSEI")]],
    ("binance_spot_klines_btcusdt_1d", "https://api.binance.com/api/v3/klines",
     {"symbol": "BTCUSDT", "interval": "1d", "limit": "1000"}),
    ("binance_perp_klines_btcusdt_1d", "https://fapi.binance.com/fapi/v1/klines",
     {"symbol": "BTCUSDT", "interval": "1d", "limit": "1000"}),
    ("binance_perp_funding_btcusdt", "https://fapi.binance.com/fapi/v1/fundingRate",
     {"symbol": "BTCUSDT", "limit": "1000"}),
]


def main() -> int:
    failed = 0
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=20.0) as http:
        for name, url, params in RECORDINGS:
            r = http.get(url, params=params)
            if r.status_code != 200:
                print(f"{name}: HTTP {r.status_code}, not written")
                failed += 1
                continue
            rec = {"status": r.status_code, "body": r.json()}
            (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
            print(f"{name}: {len(r.content)} bytes")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
