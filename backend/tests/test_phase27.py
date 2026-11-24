"""Phase 27 (scanners and smart alerts), minimal test bar: pure parsers and maths, plus one SCAN and one indicator alert
through the API in fixture mode."""

import time

import pytest

from openterm import smart_alerts as sa
from openterm.scanner import universe as U
from openterm.scanner.routes import movers


def test_universe_words():
    assert U.parse("SP500") == ("memb", "SPX")
    assert U.parse("memb:qqq") == ("memb", "QQQ")
    assert U.parse("WL:TECH") == ("wl", "TECH")
    assert U.parse("LIST:AAPL,MSFT") == ("list", "AAPL,MSFT")
    assert U.parse("NIFTY50") == ("nifty", "NIFTY50")
    with pytest.raises(U.UniverseError):
        U.parse("MOON")
    assert U.clean(["aapl", "AAPL", " msft "]) == ["AAPL", "MSFT"]


def test_nifty_csv_and_memb_payload():
    csv = "Company Name,Industry,Symbol,Series,ISIN Code\nExample Ltd.,Energy,EXAMPLE,EQ,INE000000000\nOther Ltd.,IT,OTHER,EQ,INE1\n"
    assert U.nifty_members(csv) == ["EXAMPLE.NS", "OTHER.NS"]
    payload = {"sections": [{"rows": [{"symbol": "AAPL", "weight": 0.07}, {"symbol": None, "weight": 0.01}]}]}
    assert U.memb_members(payload) == [("AAPL", 0.07)]


def test_movers_return_and_contribution():
    day = 86_400
    data = {"A": {"t": [i * day for i in range(30)], "c": [100.0] * 29 + [110.0]},
            "B": {"t": [i * day for i in range(30)], "c": [50.0] * 29 + [45.0]}}
    rows = {r["symbol"]: r for r in movers(data, {"A": 0.5, "B": 0.25}, "1D")}
    assert rows["A"]["return"] == pytest.approx(0.10) and rows["A"]["contrib"] == pytest.approx(0.05)
    assert rows["B"]["contrib"] == pytest.approx(-0.025)


def test_drop_forming_bar():
    # A US daily bar dated today (local) is still forming at 15:00 New York, complete at 17:00.
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    today = datetime(2026, 11, 24, 9, 30, tzinfo=ny).timestamp()
    bars = {"t": [today - 86_400, today], "c": [1.0, 2.0], "tz": "America/New_York"}
    assert sa.drop_forming(bars, datetime(2026, 11, 24, 15, 0, tzinfo=ny).timestamp())["c"] == [1.0]
    assert sa.drop_forming(bars, datetime(2026, 11, 24, 17, 0, tzinfo=ny).timestamp())["c"] == [1.0, 2.0]


def test_drawing_alert_geometry():
    trend = {"kind": "TREND", "pts": [{"t": 0, "p": 100.0}, {"t": 100, "p": 110.0}]}
    assert sa.line_value(trend["pts"], 200) == pytest.approx(120.0)  # extended to the right
    trend["side"] = sa.where(trend, 115.0, 100)  # above the line at creation
    assert not sa.fired(trend, 125.0, 200) and sa.fired(trend, 119.0, 200)
    chan = {"kind": "PCHAN", "pts": [{"t": 0, "p": 100.0}, {"t": 100, "p": 100.0}, {"t": 50, "p": 110.0}]}
    assert sa.channel(chan["pts"], 10) == pytest.approx((100.0, 110.0))
    assert not sa.fired(chan, 105.0, 10) and sa.fired(chan, 111.0, 10)


def test_atr_in_the_rule_grammar():
    import pandas as pd

    from openterm.bt import rules

    df = pd.DataFrame({"open": [10.0] * 30, "high": [11.0] * 30, "low": [9.0] * 30, "close": [10.0] * 30, "volume": [1.0] * 30},
                      index=pd.date_range("2026-01-01", periods=30))
    s = rules._series(rules.parse("ATR14>1").left, df, {})
    assert s.iloc[-1] == pytest.approx(2.0)  # a constant 2-point range
    assert rules.signals(rules.parse("ATR14>1"), {"X": df})["X"].iloc[-1] == 1.0


def _wait_task(client, path, timeout=120.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        t = client.get(path).json()
        if t["state"] in ("done", "error"):
            return t
        time.sleep(0.1)
    raise AssertionError(f"task {path} still {t['state']}")


def test_api_scan_list(client):
    r = client.post("/api/scan", json={"universe": "LIST:AAPL,SYN0001", "rule": "CLOSE>SMA20 OR CLOSE<=SMA20"})
    assert r.status_code == 200, r.text
    t = _wait_task(client, f"/api/scan/task/{r.json()['id']}")
    assert t["state"] == "done", t
    assert t["result"]["checked"] == 2 and t["result"]["matched"] == 2  # the rule is always true where SMA20 exists
    assert set(t["result"]["terms"]) == {"CLOSE", "SMA20"}
    bad = client.post("/api/scan", json={"universe": "MOON", "rule": "RSI14<30"})
    assert bad.status_code == 400


def test_indicator_columns_parse_and_maths():
    import pandas as pd

    from openterm.bt import rules
    from openterm.scanner import cols as C
    from openterm.scanner.job import _col_series

    spec = C.parse("rsi14<30, PCT_SMA5, REL_VOL, CLOSE")
    assert [c.label for c in spec] == ["RSI14", "PCT_SMA5", "REL_VOL20", "CLOSE"]
    assert spec[0].op == "<" and spec[0].num == 30 and C.max_period(spec) == 21
    for bad in ("", "FOO_BAR", "SMA", "PCT_SMA", "RSI14,RSI14", "A,B,C,D,E,F,G"):
        with pytest.raises(rules.RuleError):
            C.parse(bad)
    n = 30
    df = pd.DataFrame({"open": [10.0] * n, "high": [11.0] * n, "low": [9.0] * n, "close": [10.0] * (n - 1) + [11.0],
                       "volume": [100.0] * (n - 1) + [300.0]}, index=pd.date_range("2026-01-01", periods=n))
    by = {c.label: _col_series(c, df, {}).iloc[-1] for c in spec}
    assert by["REL_VOL20"] == pytest.approx(3.0)  # 300 over the 100 average of the 20 bars before it
    assert by["PCT_SMA5"] == pytest.approx((11 / 10.2 - 1) * 100)  # SMA5 of 10,10,10,10,11 = 10.2


def test_api_indicator_columns(client):
    r = client.post("/api/scan/cols", json={"symbols": ["AAPL", "SYN0001", "AAPL/MSFT"], "cols": "SMA20,REL_VOL"})
    assert r.status_code == 200, r.text
    t = _wait_task(client, f"/api/scan/task/{r.json()['id']}")
    assert t["state"] == "done", t
    rows = t["result"]["rows"]
    assert rows["AAPL"]["values"]["SMA20"] is not None and "REL_VOL20" in rows["SYN0001"]["values"]
    assert "NOT A PLAIN SYMBOL" in rows["AAPL/MSFT"]["note"]  # a formula row gets a note, not a failed request
    assert client.post("/api/scan/cols", json={"symbols": ["AAPL"], "cols": "MOON9"}).status_code == 400


def test_api_indicator_alert_never_fires_in_fixture_mode(client):
    r = client.post("/api/smartalerts/indicator", json={"symbol": "AAPL", "rule": "CLOSE>0"})
    assert r.status_code == 200, r.text
    job_id, aid = r.json()["job"]["id"], r.json()["alert"]["id"]
    end = time.monotonic() + 120
    while client.get(f"/api/jobs/{job_id}").json()["state"] not in ("done", "error") and time.monotonic() < end:
        time.sleep(0.1)
    a = next(x for x in client.get("/api/smartalerts").json()["indicator"] if x["id"] == aid)
    assert a["status"] == "active" and "FIXTURE MODE: NOT FIRED" in a["note"]
