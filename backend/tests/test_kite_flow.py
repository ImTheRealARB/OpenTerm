"""Kite depth (DOM) and tick-rule tape (TAS) for Indian symbols: read-only, built from the REAL recorded ticker frames
(`kite_ws_packets_real`: RELIANCE / NIFTY in quote mode, a NIFTY future, a GOLD future and a NIFTY option in full mode).
Nothing here touches the network; the socket is the fake of test_kite_wrapup.
"""

from __future__ import annotations

import asyncio

import pytest
from test_kite_wrapup import WS, Client, FakeConnect, FakeSocket, Session

from openterm.errors import DataError
from openterm.kite.instruments import Instruments
from openterm.kite.ws import KiteTicker
from openterm.world import kiteflow

TOKENS = {738561: "RELIANCE.NS", 256265: "^NSEI", 15736578: "NIFTY26NOVFUT.NFO", 126774535: "GOLD26DECFUT.MCX", 10239746: "NIFTY26N0924400CE.NFO"}


def make_ticker() -> KiteTicker:
    t = KiteTicker(lambda tick: None, Session(), Instruments(Client(), None), lambda s: None)  # type: ignore[arg-type]
    t._wanted = dict(TOKENS)
    return t


def feed(t: KiteTicker) -> None:
    for f in WS["frames"]:
        if f["kind"] == "binary":
            t.on_message(bytes.fromhex(f["data"]))


def test_real_full_packets_give_a_book_per_symbol():
    t = make_ticker()
    feed(t)
    assert {"NIFTY26NOVFUT.NFO", "GOLD26DECFUT.MCX", "NIFTY26N0924400CE.NFO"} <= set(t.books)
    assert "RELIANCE.NS" not in t.books  # quote mode carries no depth
    for sym, book in t.books.items():
        assert len(book["buy"]) == 5 and len(book["sell"]) == 5, sym


def test_depth_payload_is_the_dom_shape_and_drops_empty_levels():
    t = make_ticker()
    feed(t)
    sym = "NIFTY26NOVFUT.NFO"
    d = kiteflow.depth_payload(sym, t.books[sym])
    assert d["venue"].startswith("KITE") and d["quote"] == "INR" and d["usd"] is False
    assert d["best_bid"] < d["best_ask"] and d["spread"] > 0
    prices = [r[0] for r in d["bids"]]
    assert prices == sorted(prices, reverse=True) and [r[0] for r in d["asks"]] == sorted(r[0] for r in d["asks"])
    assert d["bids"][-1][2] == d["bid_qty"] and len(d["bids"]) <= 5  # cumulative quantity
    thin = {"t": 1, "buy": [(10, 100.0, 1)] + [(0, 0.0, 0)] * 4, "sell": [(5, 100.5, 1)] + [(0, 0.0, 0)] * 4}
    assert kiteflow.depth_payload("X.NS", thin)["levels"] == [1, 1]
    with pytest.raises(DataError, match="EMPTY BOOK"):
        kiteflow.depth_payload("X.NS", {"t": 1, "buy": [(0, 0.0, 0)] * 5, "sell": thin["sell"]})


def test_the_tape_holds_volume_gained_with_a_reference_print_first():
    t = make_ticker()
    feed(t)
    prints = list(t.tape["RELIANCE.NS"])
    assert prints[0][3] == 0  # the first packet is only a starting point
    gained = [p[3] for p in prints[1:]]
    assert gained[:2] == [675, 394]  # 5,029,319 -> 5,029,994 -> 5,030,388 in the recording
    assert [p[2] for p in prints[:3]] == [1307.0, 1306.9, 1306.8]
    assert all(p[3] >= 0 for p in prints)


def test_tick_rule_sides_and_the_estimated_label():
    t = make_ticker()
    feed(t)
    p = kiteflow.tas_payload("RELIANCE.NS", list(t.tape["RELIANCE.NS"]), 50)
    assert p["basis"] == "ESTIMATED (TICK RULE)" and p["venue"].startswith("KITE")
    assert all(r["q"] > 0 for r in p["rows"])  # no quantity-0 reference row is ever drawn
    first = p["rows"][::-1][:2]  # oldest first: 1307.0 -> 1306.9 -> 1306.8 are both falls
    assert [r["side"] for r in first] == ["SELL", "SELL"]
    assert p["rows"][0]["t"] >= p["rows"][-1]["t"]  # newest first
    rising = [(1, 1000, 10.0, 0), (2, 2000, 10.5, 7), (3, 3000, 10.5, 3), (4, 4000, 10.4, 2)]
    rows = kiteflow.tas_payload("X.NS", rising, 10)["rows"]
    assert [(r["p"], r["side"]) for r in rows[::-1]] == [(10.5, "BUY"), (10.5, "BUY"), (10.4, "SELL")]  # same price keeps the side
    flat = kiteflow.tas_payload("X.NS", [(1, 1, 10.0, 0), (2, 2, 10.0, 5), (3, 3, 10.2, 5)], 10)
    assert flat["unsided"] == 1 and [r["side"] for r in flat["rows"]] == ["BUY"]  # the print before the first move has no side


def test_a_new_day_resets_the_baseline_and_a_symbol_not_asked_for_feeds_no_chart():
    t = make_ticker()
    emitted = []
    t.emit = emitted.append
    t.symbols = {"^NSEI"}
    t.pin("RELIANCE.NS")  # pinned only for a tape: the hub must not get its ticks
    feed(t)
    assert "RELIANCE.NS" not in {x.symbol for x in emitted} and "^NSEI" in {x.symbol for x in emitted}
    t._vol["RELIANCE.NS"] = 10**9  # yesterday's bigger number
    n = len(t.tape["RELIANCE.NS"])
    t.on_message(bytes.fromhex(WS["frames"][0]["data"]))
    assert len(t.tape["RELIANCE.NS"]) >= n and t.tape["RELIANCE.NS"][-1][3] == 0


def test_pin_refuses_a_symbol_kite_does_not_serve():
    t = make_ticker()
    with pytest.raises(ValueError, match="DOES NOT SERVE"):
        t.pin("AAPL")
    with pytest.raises(ValueError):
        t.hold("BTCUSDT")


def test_the_flow_functions_say_why_they_cannot_answer():
    with pytest.raises(DataError, match="FIXTURE MODE"):
        kiteflow.depth(None, "RELIANCE.NS")
    t = make_ticker()
    t.session = type("S", (), {"logged_in": False, "state": "KITE LOGIN EXPIRED", "message": staticmethod(lambda: "KITE LOGIN EXPIRED: run KITE LOGIN")})()
    with pytest.raises(DataError) as e:
        kiteflow.tas(t, "RELIANCE.NS", 10)
    assert e.value.kind == "login_expired"
    t.session = Session()
    with pytest.raises(DataError, match="WAITING FOR KITE'S FIRST DEPTH"):
        kiteflow.depth(t, "RELIANCE.NS")
    with pytest.raises(DataError, match="NO KITE PRINTS"):
        kiteflow.tas(t, "NIFTY26NOVFUT.NFO", 10)
    with pytest.raises(DataError, match="DOES NOT SERVE"):
        kiteflow.tas(t, "AAPL", 10)
    feed(t)
    assert kiteflow.tas(t, "RELIANCE.NS", 10)["data"]["rows"]
    env = kiteflow.depth(t, "NIFTY26NOVFUT.NFO")
    assert env["source"] == "kite" and env["data"]["bids"]


def test_routes_dispatch_indian_symbols_to_the_ticker(client):
    r = client.get("/api/world/cdep", params={"pair": "RELIANCE.NS"})
    assert r.status_code >= 400 and "FIXTURE MODE" in r.text  # fixture mode has no ticker: said plainly, never a fake book
    t = make_ticker()
    feed(t)
    client.app.state.hub.kite = t
    try:
        d = client.get("/api/world/cdep", params={"pair": "NIFTY26NOVFUT.NFO"})
        assert d.status_code == 200, d.text
        assert d.json()["data"]["venue"].startswith("KITE")
        s = client.get("/api/world/flow/trades", params={"sym": "RELIANCE.NS", "limit": 5})
        assert s.status_code == 200, s.text
        assert s.json()["data"]["basis"] == "ESTIMATED (TICK RULE)" and len(s.json()["data"]["rows"]) <= 5
        crypto = client.get("/api/world/flow/trades", params={"sym": "AAPL"})
        assert crypto.status_code == 400  # not Kite, not crypto: the old message
    finally:
        client.app.state.hub.kite = None


# --- modes on the socket: quote for everything, full only where a panel or a recording needs the book -------------------------------------

async def test_depth_pins_switch_one_instrument_to_full_mode_and_back(monkeypatch):
    import websockets

    sock = FakeSocket([], drop_after=False)
    monkeypatch.setattr(websockets, "connect", FakeConnect([sock]))
    t = KiteTicker(lambda tick: None, Session(), Instruments(Client(), None), lambda s: None)  # type: ignore[arg-type]
    await t.set_symbols({"RELIANCE.NS", "^NSEI"})
    t.start()

    async def until(cond):
        async with asyncio.timeout(5):
            while not cond():
                await asyncio.sleep(0.01)

    try:
        await until(lambda: t.status == "OK")
        modes = [m["v"] for m in sock.sent if m["a"] == "mode"]
        assert [m[0] for m in modes] == ["quote"]  # nothing wants depth yet
        t.pin("RELIANCE.NS", depth=True)
        await until(lambda: any(m["a"] == "mode" and m["v"][0] == "full" for m in sock.sent))
        full = next(m for m in sock.sent if m["a"] == "mode" and m["v"][0] == "full")
        assert len(full["v"][1]) == 1  # one instrument only
        t._pins.clear()  # the pin ran out
        t._wake.set()
        await until(lambda: [m["v"][0] for m in sock.sent if m["a"] == "mode"][-1] == "quote")
    finally:
        await t.stop()
