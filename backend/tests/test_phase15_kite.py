"""Phase 15 steps 6-7: Kite Connect, READ-ONLY (spec: docs/specs/PHASE_15.md "Kite Connect"; roadmap row KITE).

Contract tests written before the code, in fixture mode. Every `kite_*_docshape` fixture is built from the Kite Connect v3 documentation with
invented values and labelled NOT A RECORDING (scripts/record_phase15.py --kite): expected numbers below are read from those files with
independent code, and the label must appear wherever fixture data is shown. Fixture routing (added with the code): `POST api.kite.trade/session/token`
answers the session only when `checksum == sha256(api_key + request_token + api_secret)` for the test's key trio (KEY, SECRET, REQUEST_TOKEN below),
otherwise 403 InputException; setting env `OPENTERM_KITE_EXPIRED=1` makes every authenticated Kite call answer the TokenException fixture.
Was strict xfail until the steps landed: KITE = step 6 (backend), KITEUI = step 7 (history, chains, status in the UI-facing routes); the markers are gone.
"""

import hashlib
import json
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1] / "openterm"
KEY, SECRET, REQUEST_TOKEN = "docshape_api_key", "docshape_secret", "docshape_request_token"
ACCESS = "docshape_access_token"  # what the session fixture returns: it must never appear in any answer


def xf(group: str, step: int):
    return pytest.mark.xfail(strict=True, reason=f"Phase 15 step {step}: {group}")


KITE = lambda f: f  # step 6 landed
KITEUI = lambda f: f  # step 7 landed


def fx(name: str):
    rec = json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))
    return rec["body"] if "body" in rec else rec["text"]


def set_keys(client, secret: str = SECRET):
    r = client.put("/api/keys/kite", json={"fields": {"KITE_API_KEY": KEY, "KITE_API_SECRET": secret}})
    assert r.status_code == 200, r.text


def login(client):
    set_keys(client)
    r = client.get("/api/kite/callback", params={"request_token": REQUEST_TOKEN, "status": "success"})
    assert r.status_code == 200 and "LOGGED IN" in r.text.upper(), r.text[:300]


def status(client) -> dict:
    return client.get("/api/kite/status").json()


# --- always-on guards (pass now, keep passing) ------------------------------------------------------------------------------------------

def test_kite_fixtures_are_labelled_not_a_recording():
    names = sorted(p.stem for p in FIX.glob("kite_*_docshape.json"))
    assert len(names) >= 7
    for n in names:
        rec = json.loads((FIX / f"{n}.json").read_bytes().decode("utf-8"))
        assert "NOT A RECORDING" in rec["_label"].upper(), n


@KITE
def test_kite_has_no_order_surface_anywhere(client):
    """No order, GTT, margin or holdings endpoint exists in any route or in any Kite code (user decision 2026-10-19)."""
    import importlib

    importlib.import_module("openterm.kite")  # xfail until the package exists: a vacuous pass is not a pass
    paths = [getattr(r, "path", "").lower() for r in client.app.routes]
    assert not [p for p in paths if any(w in p for w in ("order", "gtt", "margin", "holdings", "positions/convert"))
                and not p.startswith("/api/portfolios")], paths
    forbidden = ("/orders", "/gtt", "/user/margins", "/portfolio/holdings", "/portfolio/positions", "place_order", "modify_order",
                 "cancel_order", "mf/orders")
    files = [*(ROOT / "kite").rglob("*.py"), *ROOT.glob("providers/kite*.py")]
    assert files
    for f in files:
        text = f.read_text(encoding="utf-8").lower()
        assert not [w for w in forbidden if w in text], (f.name, [w for w in forbidden if w in text])


# --- keys, status, login ------------------------------------------------------------------------------------------------------------------

@KITE
def test_kite_key_row_has_two_inputs_and_no_token_field(client):
    row = next(k for k in client.get("/api/keys").json()["keys"] if k["name"] == "kite")
    assert row["fields"] == ["KITE_API_KEY", "KITE_API_SECRET"] and row["state"] == "MISSING"
    set_keys(client)
    row = next(k for k in client.get("/api/keys").json()["keys"] if k["name"] == "kite")
    assert row["state"] in ("UNTESTED", "OK") and row["present"]
    assert KEY not in client.get("/api/keys").text and SECRET not in client.get("/api/keys").text


@KITE
def test_inert_without_a_key(client):
    st = status(client)
    assert st["state"] == "NO KEY" and "KITE_API_KEY" in st["message"].upper() and st["message"].upper().startswith("KEY REQUIRED")
    r = client.get("/api/kite/login", follow_redirects=False)
    assert r.status_code == 400 and "KEY REQUIRED: SET KITE_API_KEY IN APIKEYS" in r.json()["error"].upper()
    assert client.get("/api/kite/resolve", params={"symbol": "RELIANCE.NS"}).status_code == 400


@KITE
def test_login_redirects_to_kite_and_never_exposes_the_secret(client):
    set_keys(client)
    assert status(client)["state"] == "LOGGED OUT"
    r = client.get("/api/kite/login", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc == f"https://kite.zerodha.com/connect/login?v=3&api_key={KEY}" and SECRET not in loc


@KITE
def test_callback_exchanges_the_request_token_with_the_documented_checksum(client):
    assert hashlib.sha256((KEY + REQUEST_TOKEN + SECRET).encode()).hexdigest()  # the checksum the fixture route recomputes
    login(client)
    st = status(client)
    assert st["state"] == "OK" and st["user"] == "DOC001" and st["logged_in_at"]
    for path in ("/api/keys", "/api/sources", "/api/kite/status", "/api/log", "/api/perf"):
        text = client.get(path).text
        assert ACCESS not in text and SECRET not in text and "docshape_public_token" not in text, path
    row = next(k for k in client.get("/api/keys").json()["keys"] if k["name"] == "kite")
    assert row["state"] == "OK"


@KITE
def test_wrong_secret_fails_and_leaves_you_logged_out(client):
    set_keys(client, secret="not-the-secret")
    r = client.get("/api/kite/callback", params={"request_token": REQUEST_TOKEN, "status": "success"})
    assert r.status_code in (400, 403) and "LOGIN FAILED" in r.text.upper() and ACCESS not in r.text
    assert status(client)["state"] == "LOGGED OUT"
    for params in ({"status": "success"}, {"request_token": "x", "status": "error"}):
        assert client.get("/api/kite/callback", params=params).status_code == 400


@KITE
def test_logout_forgets_the_token(client):
    login(client)
    assert client.post("/api/kite/logout").status_code == 200
    assert status(client)["state"] == "LOGGED OUT"


@KITE
def test_a_token_exception_marks_the_login_expired(client, monkeypatch):
    login(client)
    monkeypatch.setenv("OPENTERM_KITE_EXPIRED", "1")
    r = client.get("/api/kite/instruments")  # any authenticated call
    assert r.status_code in (401, 403) and "KITE LOGIN EXPIRED" in r.json()["error"].upper()
    assert status(client)["state"] == "KITE LOGIN EXPIRED"
    monkeypatch.delenv("OPENTERM_KITE_EXPIRED")
    login(client)
    assert status(client)["state"] == "OK"


@KITE
@pytest.mark.parametrize(("login_ist", "now_ist", "expired"), [
    ("2026-10-18 08:15", "2026-10-19 05:59", False), ("2026-10-18 08:15", "2026-10-19 06:00", True),
    ("2026-10-18 08:15", "2026-10-18 23:59", False), ("2026-10-18 05:00", "2026-10-18 05:59", False),
    ("2026-10-18 05:00", "2026-10-18 06:00", True), ("2026-10-18 06:00", "2026-10-19 05:59", False),
])
def test_session_expires_at_the_next_six_am_ist(login_ist, now_ist, expired):
    from datetime import timedelta, timezone

    from openterm.kite.session import expired as is_expired

    ist = timezone(timedelta(hours=5, minutes=30))
    parse = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ist)
    assert is_expired(parse(login_ist), parse(now_ist)) is expired


# --- symbols and instruments ------------------------------------------------------------------------------------------------------------

@KITE
@pytest.mark.parametrize(("sym", "kite"), [
    ("RELIANCE.NS", "NSE:RELIANCE"), ("TCS.BO", "BSE:TCS"), ("^NSEI", "NSE:NIFTY 50"), ("^NSEBANK", "NSE:NIFTY BANK"),
    ("NIFTY26OCTFUT.NFO", "NFO:NIFTY26OCTFUT"), ("CRUDEOIL26OCTFUT.MCX", "MCX:CRUDEOIL26OCTFUT"),
])
def test_yahoo_style_symbols_map_to_kite(sym, kite):
    from openterm.kite.symbols import to_kite

    assert to_kite(sym) == kite
    assert to_kite("AAPL") is None and to_kite("SYN0001") is None and to_kite("EURUSD=X") is None


@KITEUI
def test_resolve_finds_the_instrument_token_in_the_dump(client):
    login(client)
    d = client.get("/api/kite/resolve", params={"symbol": "RELIANCE.NS"}).json()
    assert d["kite"] == "NSE:RELIANCE" and d["instrument_token"] == 738561 and d["lot_size"] == 1
    n = client.get("/api/kite/resolve", params={"symbol": "^NSEI"}).json()
    assert n["instrument_token"] == 256265
    assert client.get("/api/kite/resolve", params={"symbol": "NOSUCH.NS"}).status_code == 404


# --- bars -----------------------------------------------------------------------------------------------------------------------------

def candle_epochs_and_closes() -> tuple[list[int], list[float]]:
    candles = fx("kite_historical_reliance_day_docshape")["data"]["candles"]
    return ([int(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z").timestamp()) for c in candles], [c[4] for c in candles])


@KITEUI
def test_indian_symbols_get_kite_bars_when_logged_in_and_are_labelled(client):
    before = client.get("/api/history", params={"symbol": "RELIANCE.NS", "range": "1Y", "interval": "1d"}).json()
    assert "KITE" not in before["source"].upper()  # Yahoo while logged out
    login(client)
    r = client.get("/api/history", params={"symbol": "RELIANCE.NS", "range": "1Y", "interval": "1d"}).json()
    t, c = candle_epochs_and_closes()
    assert r["data"]["t"] == t and r["data"]["c"] == c
    assert "KITE" in r["source"].upper() and "NOT A RECORDING" in r["source"].upper()
    a = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "1d"}).json()
    assert "KITE" not in a["source"].upper()  # US symbols never go to Kite


@KITEUI
def test_expired_login_falls_back_to_yahoo_and_says_so(client, monkeypatch):
    login(client)
    monkeypatch.setenv("OPENTERM_KITE_EXPIRED", "1")
    r = client.get("/api/history", params={"symbol": "RELIANCE.NS", "range": "1Y", "interval": "1d"}).json()
    assert "KITE" not in r["source"].upper() and r["fallback_from"] and "kite" in str(r["fallback_from"]).lower()
    assert status(client)["state"] == "KITE LOGIN EXPIRED"


# --- option chains with open interest -----------------------------------------------------------------------------------------------------

def quote_fixture() -> dict:
    return fx("kite_quote_nifty_docshape")["data"]


def chain_rows(d: dict, sid: str) -> dict[float, dict]:
    sec = next(s for s in d["data"]["sections"] if s["id"] == sid)
    return {r["strike"]: r for r in sec["rows"]}


@KITEUI
def test_omon_nfo_chain_shows_open_interest_from_kite_quotes(client):
    login(client)
    r = client.get("/api/deriv/omon", params={"symbol": "NIFTY.NFO", "date": "2026-10-27"})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    q = quote_fixture()
    calls, puts = chain_rows(d, "calls"), chain_rows(d, "puts")
    assert sorted(calls) == [24600.0 + 100 * i for i in range(9)] == sorted(puts)
    for strike, row in calls.items():
        inst = q[next(k for k in q if k.endswith(f"{int(strike)}CE") and "OCT" in k)]
        assert row["oi"] == inst["oi"] and row["volume"] == inst["volume"] and row["last"] == inst["last_price"]
        assert row["bid"] == inst["depth"]["buy"][0]["price"] and row["ask"] == inst["depth"]["sell"][0]["price"]
    assert "KITE" in d["source"].upper() and "NOT A RECORDING" in d["source"].upper()
    head = " ".join(f'{h["label"]} {h["value"]}' for h in d["data"]["headline"]).upper()
    assert "25000" in head.replace(",", "") and "NEEDS R=" in head + " ".join(d["data"]["notes"]).upper()
    assert all(r_["delta"] is None for r_ in calls.values())  # Greeks are computed only from a typed R= (and Q=)


@KITEUI
def test_omon_nfo_greeks_are_computed_here_when_r_and_q_are_typed(client):
    import math

    login(client)
    d = client.get("/api/deriv/omon", params={"symbol": "NIFTY.NFO", "date": "2026-10-27", "R": "6.5", "Q": "1.2"}).json()
    calls, puts = chain_rows(d, "calls"), chain_rows(d, "puts")
    atm_c, atm_p = calls[25000.0], puts[25000.0]
    assert 0.4 < atm_c["delta"] < 0.7 and -0.7 < atm_p["delta"] < -0.3 and atm_c["gamma"] > 0 and atm_c["vega"] > 0
    t = (datetime(2026, 10, 27, 10, 0, tzinfo=UTC) - datetime(2026, 10, 18, tzinfo=UTC)).total_seconds() / (365 * 86400)
    assert 0.02 < t < 0.03 and atm_c["iv"] > 0 and not math.isnan(atm_c["iv"])
    assert "COMPUTED HERE (BLACK-SCHOLES), NOT VENDOR" in (" ".join(d["data"]["notes"]) + str(d["data"]["headline"])).upper()


@KITEUI
def test_omon_nfo_without_a_login_says_so(client):
    set_keys(client)
    d = client.get("/api/deriv/omon", params={"symbol": "NIFTY.NFO"}).json()
    assert d["data"]["status"].upper().startswith("KITE LOGGED OUT") or "KITE LOGIN" in d["data"]["status"].upper()


@KITEUI
def test_nfo_chain_without_any_key_is_key_required(client):
    d = client.get("/api/deriv/omon", params={"symbol": "NIFTY.NFO"}).json()
    assert d["data"]["key_required"] and d["data"]["key_required"][0]["key"] == "KITE_API_KEY"
    assert "KEY REQUIRED: SET KITE_API_KEY IN APIKEYS" in (d["data"]["status"] or "").upper()


@KITEUI
def test_nifty_futures_list_open_interest(client):
    login(client)
    d = client.get("/api/deriv/ct", params={"symbol": "NIFTY.NFO"}).json()
    sec = d["data"]["sections"][0]
    assert {r["contract"] for r in sec["rows"]} >= {"NIFTY26OCTFUT", "NIFTY26NOVFUT"} and all("oi" in r for r in sec["rows"])


# --- ticks (binary packets in the documented layout) ----------------------------------------------------------------------------------

def packets() -> dict:
    return fx("kite_ws_packets_docshape")


def by_name(name: str) -> bytes:
    return bytes.fromhex(next(m for m in packets()["messages"] if m["name"] == name)["hex"])


@KITE
def test_decoder_reads_ltp_quote_full_and_index_packets():
    from openterm.kite.ws import decode

    want = packets()["expected"]
    ltp, quote = decode(by_name("ltp+quote"))
    assert ltp["token"] == want["ltp"]["token"] and ltp["ltp"] == pytest.approx(want["ltp"]["ltp"])
    for k, v in want["quote"].items():
        assert quote[k] == pytest.approx(v), k
    (full,) = decode(by_name("full"))
    for k in ("token", "ltp", "oi", "oi_day_high", "oi_day_low", "ts_last_trade", "ts_exchange"):
        assert full[k] == pytest.approx(want["full"][k]), k
    qty, price, orders = full["depth_buy"][0]
    assert [qty, price, orders] == pytest.approx(want["full"]["depth_buy_0"]) and len(full["depth_buy"]) == 5 == len(full["depth_sell"])
    iq, ifull = decode(by_name("index"))
    for k, v in want["index_quote"].items():
        assert iq[k] == pytest.approx(v), k
    assert ifull["token"] == 256265 and ifull["ts_exchange"] == want["index_full"]["ts_exchange"]
    assert decode(by_name("heartbeat")) == []


@KITE
def test_decoder_scales_currency_prices_and_survives_garbage():
    from openterm.kite.ws import decode

    (p,) = decode(struct.pack(">H", 1) + struct.pack(">H", 8) + struct.pack(">ii", 1, 142550), segment_of=lambda token: "cds")
    assert p["ltp"] == pytest.approx(142550 / 1e7)
    for junk in (b"", b"\x01", b"\x00\x05\x00\x08", struct.pack(">HH", 1, 99) + b"\x00" * 3):
        assert decode(junk) == []  # a short or damaged message is dropped, never raised
