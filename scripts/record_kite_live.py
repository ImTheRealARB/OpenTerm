"""Records REAL Kite Connect answers into backend/tests/fixtures (no token, key, secret or user id is ever written or printed).

    cd backend; uv run --no-dev python ../scripts/record_kite_live.py [quotes] [candles] [instruments] [error] [ticks]

Needs a Kite key in the OS keyring (APIKEYS) and a login made today (KITE LOGIN in the app). The WebSocket part wants the market open
(NSE 09:15-15:30 IST, MCX to 23:30, CDS to 17:00); it records the first frames for a handful of instruments and the instrument rows they
belong to. The picked contracts are looked up in today's dump (current-month future, an option near the money), so rerun it on another
day and the files change; the tests read them back through the file, not through hard-coded numbers.
Files written (all labelled REAL with the recording date):
  kite_quote_derivs_real.json  GET /quote for NFO/BFO/MCX/CDS futures, an option and BSE:RELIANCE (depth removed)
  kite_historical_*_real.json  daily bars with open interest (oi=1) for RELIANCE, a NIFTY future, a GOLD future, a USDINR future
  kite_instruments_real_subset.csv-in-json  the dump rows of the instruments above plus a few neighbours
  kite_error_token_real.json   the real TokenException answer to a deliberately wrong token
  kite_ws_packets_real.json    real binary WebSocket frames (hex) with the instrument each token belongs to
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import orjson
import websockets

from openterm.config import Settings
from openterm.keys import from_settings
from openterm.kite import KITE_API, KITE_WS
from openterm.kite.client import KiteClient
from openterm.kite.instruments import parse
from openterm.kite.session import IST, KiteSession

FIX = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
TODAY = date.today().isoformat()


def save(name: str, rec: dict) -> None:
    (FIX / f"{name}.json").write_bytes(json.dumps(rec, indent=1, ensure_ascii=False).encode("utf-8") + b"\n")
    print("wrote", name)


def strip_depth(d: dict) -> dict:
    """Order-book depth is not needed by anything and is the bulkiest part."""
    return {k: v for k, v in d.items() if k != "depth"}


def pick(dump_text: str) -> dict[str, dict]:
    """The instruments to record: today's current-month futures and an option near the money (the money level comes from the live quote)."""
    d = parse(dump_text, 0.0)
    today = TODAY

    def front(exchange: str, name: str, kind: str = "FUT") -> dict:
        rows = [r for r in d.chain_rows(exchange, name, (kind,)) if r["expiry"] and r["expiry"] >= today]
        return min(rows, key=lambda r: r["expiry"])

    return {"nifty_fut": front("NFO", "NIFTY"), "sensex_fut": front("BFO", "SENSEX"), "gold_fut": front("MCX", "GOLD"),
            "crude_fut": front("MCX", "CRUDEOIL"), "usdinr_fut": front("CDS", "USDINR"), "reliance": d.by_key["NSE:RELIANCE"],
            "reliance_bse": d.by_key["BSE:RELIANCE"], "nifty_index": d.by_key["NSE:NIFTY 50"]}


async def main(parts: set[str]) -> None:
    store = from_settings(Settings())
    session = KiteSession(store)
    if session.state != "OK":
        sys.exit(f"Kite is not usable: {session.message()}")
    async with httpx.AsyncClient(http2=True) as http:
        client = KiteClient(session, http)
        text = await client.get_text("/instruments")
        chosen = pick(text)
        spot = (await client.quote(["NSE:NIFTY 50"]))["NSE:NIFTY 50"]["last_price"]
        d = parse(text, 0.0)
        # the weekly option closest to the money: first live expiry, strike nearest the spot
        opts = [r for r in d.chain_rows("NFO", "NIFTY", ("CE",)) if r["expiry"] and r["expiry"] >= TODAY]
        first = min(r["expiry"] for r in opts)
        chosen["nifty_ce"] = min((r for r in opts if r["expiry"] == first), key=lambda r: abs(r["strike"] - spot))
        keys = {name: f"{r['exchange']}:{r['tradingsymbol']}" for name, r in chosen.items()}
        label = f"REAL Kite Connect answer recorded {TODAY}. No token, key or user id inside."

        if "quotes" in parts:
            data = await client.quote(list(keys.values()))
            save("kite_quote_derivs_real", {"status": 200, "_label": label + " Order-book depth removed.", "keys": keys,
                                            "body": {"status": "success", "data": {k: strip_depth(v) for k, v in data.items()}}})
        if "candles" in parts:
            end = datetime.now(IST)
            for name, days in (("reliance", 60), ("nifty_fut", 30), ("gold_fut", 30), ("usdinr_fut", 30)):
                r = chosen[name]
                candles = await client.candles(r["instrument_token"], "day", end - timedelta(days=days), end)
                save(f"kite_historical_{name}_day_real", {"status": 200, "_label": label.replace("answer", "daily candles with open interest"),
                                                          "instrument": keys[name], "token": r["instrument_token"],
                                                          "body": {"status": "success", "data": {"candles": candles}}})
        if "instruments" in parts:
            rows = list(csv.DictReader(io.StringIO(text)))
            want = {int(r["instrument_token"]) for r in chosen.values()}
            # neighbours: the other NIFTY / GOLD / USDINR futures, so a lookup of a missing contract has company
            for r in rows:
                if r["name"] in ("NIFTY", "GOLD", "USDINR") and r["instrument_type"] == "FUT" and r["exchange"] in ("NFO", "MCX", "CDS"):
                    want.add(int(r["instrument_token"]))
            keep = [r for r in rows if int(r["instrument_token"]) in want]
            out = io.StringIO()
            w = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(keep)
            save("kite_instruments_real_subset", {"status": 200, "_label": label.replace("answer", "instrument dump rows"), "keys": keys,
                                                  "text": out.getvalue()})
        if "error" in parts:
            key, _ = session.auth()
            r = await http.get(f"{KITE_API}/quote", params={"i": "NSE:RELIANCE"},
                               headers={"X-Kite-Version": "3", "Authorization": f"token {key}:wrong_token_on_purpose"})
            body = r.json()
            assert body.get("error_type") == "TokenException", body
            save("kite_error_token_real", {"status": r.status_code, "_label": label.replace("answer", "TokenException answer to a wrong token"),
                                           "body": body})
        if "ticks" in parts:
            key, token = session.auth()
            want_tokens = [chosen[n]["instrument_token"] for n in ("reliance", "nifty_index", "nifty_fut", "gold_fut", "usdinr_fut", "nifty_ce")]
            frames: list[dict] = []
            async with websockets.connect(f"{KITE_WS}?api_key={key}&access_token={token}", open_timeout=10) as ws:
                await ws.send(orjson.dumps({"a": "subscribe", "v": want_tokens}).decode())
                await ws.send(orjson.dumps({"a": "mode", "v": ["quote", want_tokens[:2] + want_tokens[4:5]]}).decode())
                await ws.send(orjson.dumps({"a": "mode", "v": ["full", [want_tokens[2], want_tokens[3], want_tokens[5]]]}).decode())
                loop = asyncio.get_running_loop()
                end = loop.time() + 8
                while loop.time() < end and len(frames) < 12:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 3)
                    except TimeoutError:
                        continue
                    frames.append({"kind": "binary" if isinstance(raw, bytes) else "text",
                                   "data": raw.hex() if isinstance(raw, bytes) else raw})
            binary = [f for f in frames if f["kind"] == "binary" and len(f["data"]) > 2]
            print("frames:", [(f["kind"], len(f["data"]) // 2) for f in frames])
            save("kite_ws_packets_real", {"status": 200, "_label": label.replace("answer", "WebSocket frames (hex)"),
                                          "tokens": {str(chosen[n]["instrument_token"]): {"key": keys[n], "exchange": chosen[n]["exchange"],
                                                                                          "mode": "full" if n in ("nifty_fut", "gold_fut", "nifty_ce") else "quote"}
                                                     for n in ("reliance", "nifty_index", "nifty_fut", "gold_fut", "usdinr_fut", "nifty_ce")},
                                          "frames": binary})


if __name__ == "__main__":
    asyncio.run(main(set(sys.argv[1:]) or {"quotes", "candles", "instruments", "error", "ticks"}))
