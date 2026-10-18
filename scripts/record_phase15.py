"""Records the Phase 15 fixtures. No key is used.

Run from backend/:
    uv run python ../scripts/record_phase15.py            # Yahoo charts (stress windows, sector ETFs) + Ken French factor files
    uv run python ../scripts/record_phase15.py --kite     # writes the DOC-SHAPED Kite Connect fixtures (no network, no key)

Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON), {"status", "text", "content_type"} (text) or
{"status", "b64", "content_type"} (a binary answer, here the Ken French zips). Big answers are trimmed; each trim is noted next to the
line that makes it. A source that does not answer stops the run (nothing is invented) EXCEPT the Kite files: Kite needs a paid developer
app and a daily login, so those are built from the Kite Connect v3 documentation with invented values and say so in a `_label` field
(`DOC-SHAPED, NOT A RECORDING`). Replace them with real answers once a key and a login exist.
"""

import base64
import io
import json
import struct
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
PLAIN = {"User-Agent": "OpenTerm/1.0 (personal research)"}
YQ = "https://query1.finance.yahoo.com"
JSON_ACCEPT = {"Accept": "application/json"}
FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FRENCH_FILES = {"kenfrench_ff5_daily": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
                "kenfrench_mom_daily": "F-F_Momentum_Factor_daily_CSV.zip"}
FRENCH_KEEP_ROWS = 1100  # about 4.3 years of trading days; the file starts in 1963 (trimmed: the last rows only)
SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]


def save_json(name: str, body, label: str | None = None) -> None:
    rec = {"status": 200, "body": body}
    if label:
        rec["_label"] = label
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: json")


def save_text(name: str, text: str, content_type: str, label: str | None = None) -> None:
    rec = {"status": 200, "text": text, "content_type": content_type}
    if label:
        rec["_label"] = label
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: {len(text)} chars")


def save_b64(name: str, data: bytes, content_type: str) -> None:
    rec = {"status": 200, "b64": base64.b64encode(data).decode("ascii"), "content_type": content_type}
    (OUT / f"{name}.json").write_bytes(json.dumps(rec, separators=(",", ":")).encode("utf-8"))
    print(f"{name}: {len(data)} bytes")


def record_charts(h: httpx.Client) -> None:
    for sym in ("SPY", "AAPL"):
        # range=max is downsampled by Yahoo (monthly or quarterly bars); range=20y keeps daily bars (from 2006-10), which covers 2008.
        r = h.get(f"{YQ}/v8/finance/chart/{sym}", params={"range": "20y", "interval": "1d"}, headers=JSON_ACCEPT)
        r.raise_for_status()
        save_json(f"yahoo_chart_{sym.lower()}_20y_1d", r.json())
        time.sleep(0.5)
    for sym in SECTOR_ETFS:
        r = h.get(f"{YQ}/v8/finance/chart/{sym}", params={"range": "3y", "interval": "1d"}, headers=JSON_ACCEPT)
        r.raise_for_status()
        save_json(f"yahoo_chart_{sym.lower()}_3y_1d", r.json())
        time.sleep(0.5)


def record_french(h: httpx.Client) -> None:
    for name, fname in FRENCH_FILES.items():
        r = h.get(f"{FRENCH}/{fname}", headers=PLAIN, timeout=60)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        member = z.namelist()[0]
        lines = z.read(member).decode("latin-1").splitlines()
        rows = [i for i, ln in enumerate(lines) if ln[:8].isdigit() and ln[8:9] == ","]
        head, body, tail = lines[: rows[0]], lines[rows[0]: rows[-1] + 1], lines[rows[-1] + 1:]
        text = "\r\n".join(head + body[-FRENCH_KEEP_ROWS:] + tail) + "\r\n"  # trim: the last rows only, the file's own header and footer
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
            out.writestr(member, text.encode("latin-1"))
        save_b64(name, buf.getvalue(), "application/zip")


# --- Kite Connect v3, built from the documentation (https://kite.trade/docs/connect/v3/) ----------------------------------------------
LABEL = "DOC-SHAPED, NOT A RECORDING: invented values in the layout the Kite Connect v3 documentation describes"
NOTE = "kite_*_docshape files carry an invented session; replace with real answers once a key and a login exist (record_phase15.py --kite)"


def kite_instruments() -> str:
    head = "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange"
    rows = ["738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE",
            "408065,1594,INFY,INFOSYS,0,,0,0.05,1,EQ,NSE,NSE",
            "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,1,EQ,INDICES,NSE",
            "260105,1016,NIFTY BANK,NIFTY BANK,0,,0,0,1,EQ,INDICES,NSE",
            "9000001,35156,NIFTY26OCTFUT,NIFTY,0,2026-10-27,0,0.1,75,FUT,NFO-FUT,NFO",
            "9000002,35157,NIFTY26NOVFUT,NIFTY,0,2026-11-24,0,0.1,75,FUT,NFO-FUT,NFO",
            "9100001,35200,CRUDEOIL26OCTFUT,CRUDEOIL,0,2026-10-19,0,1,100,FUT,MCX-FUT,MCX"]
    token = 9200000
    for expiry, tag in (("2026-10-20", "26O20"), ("2026-10-27", "26OCT")):
        for strike in range(24600, 25500, 100):
            for kind in ("CE", "PE"):
                token += 1
                rows.append(f"{token},{token // 256},NIFTY{tag}{strike}{kind},NIFTY,0,{expiry},{strike}.0,0.05,75,{kind},NFO-OPT,NFO")
    return "\n".join([head, *rows]) + "\n"


def depth(last: float, sgn: int) -> list[dict]:
    return [{"price": round(last + sgn * 0.05 * (i + 1), 2), "quantity": 150 * (i + 1), "orders": i + 1} for i in range(5)]


def kite_quote(instruments: str) -> dict:
    data = {}
    spot = 25000.0
    for line in instruments.splitlines()[1:]:
        c = line.split(",")
        if c[10] != "NFO-OPT" or c[5] != "2026-10-27":
            continue
        strike, kind = float(c[6]), c[9]
        intrinsic = max(0.0, spot - strike) if kind == "CE" else max(0.0, strike - spot)
        last = round(intrinsic + 180 * 2.718 ** (-abs(strike - spot) / 250), 2)  # invented, smooth, positive
        data[f"NFO:{c[2]}"] = {
            "instrument_token": int(c[0]), "timestamp": "2026-10-16 15:29:59", "last_trade_time": "2026-10-16 15:29:58", "last_price": last,
            "last_quantity": 75, "buy_quantity": 15000, "sell_quantity": 14000, "volume": int(40000 * 2.718 ** (-abs(strike - spot) / 400)),
            "average_price": last, "oi": int(900000 * 2.718 ** (-abs(strike - spot) / 500)), "oi_day_high": 1000000, "oi_day_low": 100000,
            "net_change": 0, "lower_circuit_limit": 0.05, "upper_circuit_limit": 4000.0,
            "ohlc": {"open": last, "high": last, "low": last, "close": last}, "depth": {"buy": depth(last, -1), "sell": depth(last, 1)}}
    data["NSE:NIFTY 50"] = {"instrument_token": 256265, "timestamp": "2026-10-16 15:30:00", "last_price": spot, "net_change": 0,
                            "ohlc": {"open": spot, "high": spot, "low": spot, "close": spot}}
    return {"status": "success", "data": data}


def kite_candles(days: int = 40, oi: bool = False) -> dict:
    out, px = [], 1400.0
    for i in range(days):
        day = datetime.fromtimestamp(datetime(2026, 8, 24, tzinfo=UTC).timestamp() + i * 86400, UTC)
        if day.weekday() >= 5:
            continue
        o = px
        px = round(px * (1 + 0.004 * ((i * 7) % 5 - 2)), 2)
        row = [day.strftime("%Y-%m-%dT00:00:00+0530"), o, max(o, px) + 3, min(o, px) - 3, px, 1_000_000 + 10_000 * i]
        out.append(row + [0] if oi else row)
    return {"status": "success", "data": {"candles": out}}


def ws_packets() -> dict:
    """Binary messages in the documented layout: 2-byte packet count, then per packet a 2-byte length and the packet."""
    def bundle(*packets: bytes) -> str:
        return (struct.pack(">H", len(packets)) + b"".join(struct.pack(">H", len(p)) + p for p in packets)).hex()

    ltp = struct.pack(">ii", 738561, 142550)  # 1425.50 (paise / 100)
    quote = struct.pack(">11i", 408065, 151025, 25, 150900, 5_000_000, 90_000, 85_000, 150000, 152000, 149500, 150500)
    depth = b"".join(struct.pack(">iih2x", 100 * (i + 1), 18_000 + 5 * i, i + 1) for i in range(10))  # 5 buy then 5 sell
    full = struct.pack(">11i", 9200010, 18105, 75, 18000, 40_000, 15_000, 14_000, 17000, 19000, 16500, 17500) + struct.pack(
        ">5i", 1_792_000_000, 640_000, 700_000, 100_000, 1_792_000_100) + depth
    index_quote = struct.pack(">7i", 256265, 2_500_000, 2_510_000, 2_480_000, 2_490_000, 2_495_000, 5_000)  # 25000.00
    index_full = index_quote + struct.pack(">i", 1_792_000_100)
    assert (len(ltp), len(quote), len(full), len(index_quote), len(index_full)) == (8, 44, 184, 28, 32)
    return {"messages": [{"name": "ltp+quote", "hex": bundle(ltp, quote)}, {"name": "full", "hex": bundle(full)},
                         {"name": "index", "hex": bundle(index_quote, index_full)}, {"name": "heartbeat", "hex": "00"}],
            "expected": {"ltp": {"token": 738561, "ltp": 1425.50},
                         "quote": {"token": 408065, "ltp": 1510.25, "last_qty": 25, "avg": 1509.00, "volume": 5_000_000, "buy_qty": 90_000,
                                   "sell_qty": 85_000, "open": 1500.00, "high": 1520.00, "low": 1495.00, "close": 1505.00},
                         "full": {"token": 9200010, "ltp": 181.05, "oi": 640_000, "oi_day_high": 700_000, "oi_day_low": 100_000, "depth_buy_0": [100, 180.00, 1],
                                  "ts_last_trade": 1_792_000_000, "ts_exchange": 1_792_000_100},
                         "index_quote": {"token": 256265, "ltp": 25000.00, "high": 25100.00, "low": 24800.00, "open": 24900.00, "close": 24950.00,
                                         "change": 50.00},
                         "index_full": {"token": 256265, "ts_exchange": 1_792_000_100}}}


def record_kite() -> None:
    inst = kite_instruments()
    save_text("kite_instruments_docshape", inst, "text/csv", LABEL)
    save_json("kite_session_token_docshape", {"status": "success", "data": {
        "user_type": "individual", "email": "docshape@example.invalid", "user_name": "Doc Shape", "user_shortname": "Doc", "broker": "ZERODHA",
        "exchanges": ["NSE", "NFO", "BFO", "CDS", "BSE", "MCX", "BCD", "MF"], "products": ["CNC", "NRML", "MIS", "BO", "CO"],
        "order_types": ["MARKET", "LIMIT", "SL", "SL-M"], "avatar_url": None, "user_id": "DOC001", "api_key": "docshape_api_key",
        "access_token": "docshape_access_token", "public_token": "docshape_public_token", "enctoken": "docshape_enctoken", "refresh_token": "",
        "silent_login": False, "login_time": "2026-10-18 08:15:14", "meta": {"demat_consent": "physical"}}}, LABEL)
    save_json("kite_quote_nifty_docshape", kite_quote(inst), LABEL)
    save_json("kite_historical_reliance_day_docshape", kite_candles(), LABEL)
    save_json("kite_historical_nifty_fut_day_oi_docshape", kite_candles(oi=True), LABEL)
    save_json("kite_error_token_docshape", {"status": "error", "message": "Incorrect `api_key` or `access_token`.", "data": None,
                                            "error_type": "TokenException"}, LABEL)
    save_json("kite_ws_packets_docshape", ws_packets(), LABEL)
    print(NOTE)


def main() -> None:
    if "--kite" in sys.argv:
        record_kite()
        return
    with httpx.Client(timeout=40, headers={"User-Agent": UA}, follow_redirects=True) as h:
        record_charts(h)
        record_french(h)


if __name__ == "__main__":
    main()
