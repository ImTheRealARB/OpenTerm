"""JRNL: parsers, FIFO round trips, stats, diagnostics, routes, Shadow Account job and the read-only AI tool.

Every sample file below is DOC-SHAPED (written from each broker's published column names): NOT A RECORDING of a real export.
Nothing here touches the network; the Shadow Account runs on the app's fixture bars.
"""

import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from openterm.ai import tools as toolbox
from openterm.journal import diagnostics, roundtrips
from openterm.journal.parsers import JournalError, inspect, parse

ZERODHA = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
INFY,INE009A01021,2024-03-04,NSE,EQ,EQ,buy,false,10,1500.50,T1,O1,2024-03-04T09:20:00
INFY,INE009A01021,2024-03-05,NSE,EQ,EQ,sell,false,10,1530.00,T2,O2,2024-03-05T10:05:00
NIFTY24MARFUT,,2024-03-05,NFO,FO,,buy,false,50,22000,T3,O3,2024-03-05T10:06:00
"""
IBKR = """"ClientAccountID","CurrencyPrimary","Symbol","DateTime","Buy/Sell","Quantity","TradePrice","IBCommission","TradeID","IBOrderID","Multiplier","ListingExchange"
"U1","USD","AAPL","20240304;093100","BUY","10","170.5","-1.0","11","21","1","NASDAQ"
"U1","EUR","SAP","20240304;101500","BUY","5","170","-2.5","12","22","1","IBIS"
"U1","USD","AAPL","20240305;101500","SELL","-10","172","-1.0","13","23","1","NASDAQ"
"""
ALPACA = """id,activity_type,transaction_time,type,price,qty,side,symbol,leaves_qty,order_id,cum_qty,order_status
a1,FILL,2024-03-04T14:31:00Z,fill,170.5,10,buy,AAPL,0,o1,10,filled
a2,FILL,2024-03-04T15:31:00.5Z,partial_fill,172.0,4,sell,AAPL,6,o2,4,partially_filled
a3,DIV,2024-03-05T00:00:00Z,,0.24,,,AAPL,,,,
a4,FILL,2024-03-04T16:00:00Z,fill,60000,0.5,buy,BTC/USD,0,o3,0.5,filled
"""
GENERIC = """When;Ticker;Action;Shares;Fill;Commission
04/03/2024 09:30;ABC;B;100;10.00;1.00
05/03/2024 09:30;ABC;S;100;11.00;1.00
"""


def test_zerodha_parser_suffixes_and_ids():
    kind, trades, ign = parse(ZERODHA)
    assert kind == "zerodha" and ign == 0 and len(trades) == 3
    assert trades[0].symbol == "INFY.NS" and trades[0].currency == "INR" and trades[0].time == "2024-03-04T09:20:00"
    assert trades[2].symbol == "NIFTY24MARFUT"  # a derivative has no daily-bar suffix
    assert len({t.dkey for t in trades}) == 3


def test_ibkr_parser_currencies_fees_and_exchange_suffix():
    kind, trades, _ = parse(IBKR)
    assert kind == "ibkr"
    assert {t.currency for t in trades} == {"USD", "EUR"}
    assert trades[0].fee == 1.0 and trades[0].qty == 10 and trades[2].side == "sell" and trades[2].qty == 10
    assert trades[0].time == "2024-03-04T09:31:00"


def test_alpaca_parser_ignores_non_fills_and_shows_new_york_time():
    kind, trades, ign = parse(ALPACA)
    assert kind == "alpaca" and ign == 1 and len(trades) == 3
    assert trades[0].time == "2024-03-04T09:31:00"  # 14:31Z in New York
    assert trades[2].symbol == "BTC-USD" and trades[2].qty == 0.5


def test_generic_needs_a_date_order_and_a_mapping():
    with pytest.raises(JournalError) as e:
        parse(GENERIC, "generic", {"symbol": "Ticker"}, None, "USD")
    assert "MAP THESE COLUMNS" in str(e.value)
    info = inspect(GENERIC)
    with pytest.raises(JournalError) as e:
        parse(GENERIC, "generic", info["mapping"], None, "USD")
    assert "CHOOSE DMY OR MDY" in e.value.detail
    assert info["broker"] is None and info["mapping"]["symbol"] == "Ticker" and info["mapping"]["time"] == "When"
    _, trades, _ = parse(GENERIC, "generic", info["mapping"], "DMY", "EUR")
    assert [t.time[:10] for t in trades] == ["2024-03-04", "2024-03-05"]
    assert trades[0].currency == "EUR" and trades[0].fee == 1.0
    _, mdy, _ = parse(GENERIC, "generic", info["mapping"], "MDY", "EUR")
    assert mdy[0].time[:10] == "2024-04-03"


@pytest.mark.parametrize("text,msg", [
    ("", "EMPTY FILE"),
    ("nocolumnshere\n1\n", "NO COLUMNS"),
    ("a,b\n1,2\n", "FORMAT NOT RECOGNISED"),
])
def test_unusable_files_say_why(text, msg):
    with pytest.raises(JournalError) as e:
        parse(text)
    assert msg in str(e.value)


def test_malformed_rows_stop_the_import_and_name_the_line():
    bad = ZERODHA + "INFY,,2024-03-06,NSE,EQ,EQ,hold,false,abc,-3,T9,O9,2024-03-06T09:00:00\n"
    with pytest.raises(JournalError) as e:
        parse(bad)
    assert "NOTHING WAS STORED" in str(e.value) and "LINE 5" in e.value.detail


def test_identical_fills_in_one_file_stay_two_and_a_reimport_is_stable():
    text = "time,symbol,side,qty,price\n2024-03-04 09:30,X,buy,1,10\n2024-03-04 09:30,X,buy,1,10\n"
    _, a, _ = parse(text, "generic", {"time": "time", "symbol": "symbol", "side": "side", "qty": "qty", "price": "price"})
    _, b, _ = parse(text, "generic", {"time": "time", "symbol": "symbol", "side": "side", "qty": "qty", "price": "price"})
    assert a[0].dkey != a[1].dkey and [t.dkey for t in a] == [t.dkey for t in b]


# ------------------------------------------------------------------------------------------------ FIFO
def fill(i, time_, sym, side, qty, price, fee=0.0, ccy="USD", mult=1.0):
    ts = datetime.fromisoformat(time_).timestamp()
    return {"id": i, "ts": ts, "time": time_, "symbol": sym, "side": side, "qty": qty, "price": price, "fee": fee, "currency": ccy, "mult": mult}


def test_fifo_partial_close_splits_the_lot_and_counts_fees_once():
    fills = [fill(1, "2024-03-04T10:00:00", "A", "buy", 10, 100, fee=2),
             fill(2, "2024-03-05T10:00:00", "A", "sell", 4, 110, fee=1),
             fill(3, "2024-03-06T10:00:00", "A", "sell", 6, 90, fee=3)]
    trips, pos = roundtrips.match(fills)
    assert pos == []
    assert [t["qty"] for t in trips] == [4, 6]
    assert trips[0]["pnl_gross"] == pytest.approx(40) and trips[0]["fees"] == pytest.approx(0.8 + 1)
    assert trips[1]["pnl_gross"] == pytest.approx(-60) and trips[1]["fees"] == pytest.approx(1.2 + 3)
    assert sum(t["fees"] for t in trips) == pytest.approx(6.0)


def test_fifo_oldest_lot_first_and_one_trip_per_closing_fill():
    fills = [fill(1, "2024-03-04T10:00:00", "A", "buy", 5, 100), fill(2, "2024-03-04T11:00:00", "A", "buy", 5, 120),
             fill(3, "2024-03-05T10:00:00", "A", "sell", 7, 130)]
    trips, pos = roundtrips.match(fills)
    assert len(trips) == 1 and trips[0]["qty"] == 7
    assert trips[0]["pnl_gross"] == pytest.approx(5 * 30 + 2 * 10)
    assert pos == [{"symbol": "A", "currency": "USD", "side": "long", "qty": 3, "avg_price": 120.0, "since": "2024-03-04T11:00:00"}]


def test_shorts_open_on_a_sell_and_cover_on_a_buy():
    fills = [fill(1, "2024-03-04T10:00:00", "S", "sell", 10, 50), fill(2, "2024-03-05T10:00:00", "S", "buy", 10, 45)]
    trips, pos = roundtrips.match(fills)
    assert pos == [] and trips[0]["side"] == "short" and trips[0]["pnl"] == pytest.approx(50)


def test_a_flip_closes_then_opens_the_other_way():
    fills = [fill(1, "2024-03-04T10:00:00", "F", "buy", 5, 10), fill(2, "2024-03-05T10:00:00", "F", "sell", 8, 12)]
    trips, pos = roundtrips.match(fills)
    assert trips[0]["qty"] == 5 and trips[0]["pnl"] == pytest.approx(10)
    assert pos[0]["side"] == "short" and pos[0]["qty"] == 3


def test_currencies_never_cross_match_and_multiplier_applies():
    fills = [fill(1, "2024-03-04T10:00:00", "A", "buy", 1, 100, ccy="USD"), fill(2, "2024-03-05T10:00:00", "A", "sell", 1, 120, ccy="EUR"),
             fill(3, "2024-03-04T10:00:00", "M", "buy", 2, 10, mult=50), fill(4, "2024-03-05T10:00:00", "M", "sell", 2, 11, mult=50)]
    trips, pos = roundtrips.match(fills)
    assert [t["symbol"] for t in trips] == ["M"] and trips[0]["pnl"] == pytest.approx(100)
    assert {(p["symbol"], p["currency"], p["side"]) for p in pos} == {("A", "USD", "long"), ("A", "EUR", "short")}


def trip(i, entry, hold_h, pnl, notional=1000.0):
    e = datetime.fromisoformat(entry)
    x = e + timedelta(hours=hold_h)
    return {"id": f"T:{i}", "symbol": "T", "currency": "USD", "side": "long", "qty": 1, "entry_time": entry, "exit_time": x.isoformat(timespec="seconds"),
            "entry_ts": e.timestamp(), "exit_ts": x.timestamp(), "entry_price": 1, "exit_price": 1, "fees": 0.0, "pnl_gross": pnl, "pnl": pnl,
            "pnl_pct": pnl / notional, "hold_s": hold_h * 3600.0, "notional": notional, "open_ids": [i * 2], "close_id": i * 2 + 1, "mult": 1.0}


def test_stats_by_hand_and_empty_input():
    assert roundtrips.stats([]) == {"n": 0}
    trips = [trip(1, "2024-03-04T10:00:00", 1, 100), trip(2, "2024-03-05T10:00:00", 1, -50), trip(3, "2024-03-06T10:00:00", 3, -50),
             trip(4, "2024-03-07T10:00:00", 1, 200)]
    s = roundtrips.stats(trips)
    assert s["n"] == 4 and s["wins"] == 2 and s["losses"] == 2 and s["win_rate"] == 0.5
    assert s["avg_win"] == 150 and s["avg_loss"] == -50 and s["payoff"] == 3 and s["expectancy"] == 50
    assert s["profit_factor"] == 3 and s["total_pnl"] == 200 and s["max_consec_losses"] == 2
    assert s["max_drawdown"] == 100 and s["avg_hold_loss_s"] == 2 * 3600 and s["avg_hold_win_s"] == 3600
    assert s["by_weekday"][0]["key"] == "MON"
    only_wins = roundtrips.stats([trip(1, "2024-03-04T10:00:00", 1, 10)])
    assert only_wins["profit_factor"] is None and only_wins["avg_loss"] is None  # no invented numbers


# ------------------------------------------------------------------------------------------------ diagnostics
def seq(specs):
    return [trip(i, *s) for i, s in enumerate(specs, 1)]


def by_id(findings):
    return {f["id"]: f for f in findings}


def test_every_rule_says_insufficient_on_short_history():
    f = by_id(diagnostics.diagnose(seq([("2024-03-04T10:00:00", 1, 10)] * 3), "USD"))
    assert {x["status"] for x in f.values()} == {"insufficient"} and len(f) == 5


def test_revenge_trading_flags_a_bigger_trade_soon_after_a_loss():
    specs = [(f"2024-03-{d:02d}T10:00:00", 1, 10) for d in range(4, 14)]  # ten quiet winners
    specs += [("2024-04-01T10:00:00", 1, -100, 1000.0), ("2024-04-01T11:10:00", 1, -300, 2000.0)]  # loss, then 2x size 10 min after the exit
    f = by_id(diagnostics.diagnose(seq(specs), "USD"))["revenge"]
    assert f["status"] == "flagged" and f["evidence"]["events"] == 1 and "rule" in f and len(f["trip_ids"]) == 2
    assert f["evidence"]["pnl_of_reentries"] == -300


def test_revenge_is_clear_when_the_next_trade_is_late_or_small():
    specs = [(f"2024-03-{d:02d}T10:00:00", 1, 10) for d in range(4, 14)]
    specs += [("2024-04-01T10:00:00", 1, -100, 1000.0), ("2024-04-01T14:00:00", 1, -300, 2000.0), ("2024-04-02T10:00:00", 1, -1, 100.0)]
    assert by_id(diagnostics.diagnose(seq(specs), "USD"))["revenge"]["status"] == "clear"


def test_overtrading_day_with_worse_results():
    specs = [(f"2024-03-{d:02d}T10:00:00", 1, 20) for d in range(4, 16)]  # 12 days, one trade each
    specs += [(f"2024-03-18T{9 + i:02d}:00:00", 0.5, -30) for i in range(7)]  # one day with 7 entries, all losing
    f = by_id(diagnostics.diagnose(seq(specs), "USD"))["overtrading"]
    assert f["status"] == "flagged" and f["severity"] == "high" and f["evidence"]["days"][0]["entries"] == 7


def test_holding_losers_longer_than_winners():
    specs = []
    for i in range(6):
        specs.append((f"2024-03-{4 + i:02d}T10:00:00", 2, 100))
        specs.append((f"2024-03-{4 + i:02d}T13:00:00", 10, -150))
    f = by_id(diagnostics.diagnose(seq(specs), "USD"))["disposition"]
    assert f["status"] == "flagged" and f["evidence"]["ratio"] == pytest.approx(5) and f["severity"] == "high"
    even = [(f"2024-03-{4 + i:02d}T10:00:00", 2, 100 if i % 2 else -100) for i in range(12)]
    assert by_id(diagnostics.diagnose(seq(even), "USD"))["disposition"]["status"] == "clear"


def test_size_creep_after_two_wins():
    specs = [(f"2024-03-{d:02d}T10:00:00", 1, 10, 1000.0) for d in range(4, 13)]  # nine winners at size 1000
    specs += [(f"2024-03-{d:02d}T12:00:00", 1, 50, 3000.0) for d in range(13, 17)]  # four 3x winners, each entered after a win streak
    f = by_id(diagnostics.diagnose(seq(specs), "USD"))["creep"]
    assert f["status"] == "flagged" and f["evidence"]["events"] == 4 and f["severity"] == "watch"  # they won: a pattern to watch, not "high"


def test_off_hours_entries():
    specs = [(f"2024-03-{4 + i % 20:02d}T{10 + i % 3:02d}:00:00", 0.5, 5) for i in range(100)]
    specs += [(f"2024-04-{1 + i:02d}T03:00:00", 0.5, -40) for i in range(4)]
    f = by_id(diagnostics.diagnose(seq(specs), "USD"))["hours"]
    assert f["status"] == "flagged" and f["evidence"]["entries_outside"] == 4 and f["evidence"]["window"] == "10:00-12:59"


def test_findings_carry_rule_text_and_are_labelled_pattern_not_advice():
    for f in diagnostics.diagnose(seq([("2024-03-04T10:00:00", 1, 10)] * 12), "USD"):
        assert f["rule"] and f["title"] and f["status"] in ("insufficient", "clear", "flagged")


# ------------------------------------------------------------------------------------------------ routes
def j(client, path, **kw):
    return client.post("/api/journal/" + path, **kw)


def test_import_dedupes_and_summarises(client):
    r = j(client, "import", json={"text": ZERODHA, "name": "tb.csv"})
    assert r.status_code == 200 and r.json()["added"] == 3 and r.json()["broker"] == "zerodha"
    again = j(client, "import", json={"text": ZERODHA}).json()
    assert again["added"] == 0 and again["duplicates"] == 3
    s = client.get("/api/journal/summary").json()
    assert s["fills"] == 3 and s["groups"][0]["currency"] == "INR" and len(s["imports"]) == 2
    t = client.get("/api/journal/trades", params={"symbol": "infy.ns"}).json()
    assert t["total"] == 2


def test_import_errors_are_400_and_store_nothing(client):
    r = j(client, "import", json={"text": ZERODHA + "X,,2024-03-06,NSE,EQ,EQ,hold,false,1,1,T9,O9,2024-03-06T09:00:00\n"})
    assert r.status_code == 400 and "NOTHING WAS STORED" in r.json()["error"]
    assert client.get("/api/journal/summary").json()["fills"] == 0
    assert j(client, "import", json={}).status_code == 400
    assert j(client, "import", json={"text": GENERIC, "broker": "generic"}).status_code == 400  # slash dates need DMY / MDY


def test_preview_then_generic_import(client):
    p = j(client, "preview", json={"text": GENERIC}).json()
    assert p["broker"] is None and p["rows"] == 2
    r = j(client, "import", json={"text": GENERIC, "broker": "generic", "mapping": p["mapping"], "date_order": "DMY", "currency": "EUR"})
    assert r.status_code == 200 and r.json()["added"] == 2


def test_analysis_per_currency_with_no_conversion(client):
    j(client, "import", json={"text": IBKR})
    a = client.get("/api/journal/analysis").json()
    assert a["currency"] == "USD" and a["stats"]["n"] == 1 and a["stats"]["total_pnl"] == pytest.approx(10 * 1.5 - 2.0)
    assert [c["currency"] for c in a["currencies"]] == ["USD", "EUR"]
    eur = client.get("/api/journal/analysis", params={"currency": "EUR"}).json()
    assert eur["stats"] == {"n": 0} and eur["open_positions"][0]["symbol"] == "SAP"
    assert "NO CURRENCY IS CONVERTED" in a["labels"]["note"] and len(a["diagnostics"]) == 5
    assert client.get("/api/journal/analysis", params={"currency": "JPY"}).status_code == 400


def test_empty_analysis(client):
    assert client.get("/api/journal/analysis").json()["empty"] is True


def test_delete_by_broker_and_all(client):
    j(client, "import", json={"text": ZERODHA})
    j(client, "import", json={"text": ALPACA})
    assert client.delete("/api/journal/trades", params={"broker": "alpaca"}).json()["deleted"] == 3
    assert client.get("/api/journal/summary").json()["fills"] == 3
    assert client.delete("/api/journal/trades").json()["deleted"] == 3
    assert client.get("/api/journal/summary").json()["imports"] == []


def test_non_loopback_cannot_import_or_delete(client):
    j(client, "import", json={"text": ZERODHA})
    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.post("/api/journal/import", json={"text": ZERODHA}).status_code == 403
    assert other.delete("/api/journal/trades").status_code == 403
    assert client.get("/api/journal/summary").json()["fills"] == 3


# ------------------------------------------------------------------------------------------------ shadow account
def aapl_file(n=8):
    rows = ["time,symbol,side,qty,price,fee"]
    d = datetime(2024, 3, 4)
    for i in range(n):
        a, b = d + timedelta(days=7 * i), d + timedelta(days=7 * i + 3)
        rows.append(f"{a:%Y-%m-%d} 10:00,AAPL,buy,10,{170 + i},0")
        rows.append(f"{b:%Y-%m-%d} 11:00,AAPL,sell,10,{171 + i},0")
    return "\n".join(rows) + "\n"


def wait(client, job_id):
    end = time.monotonic() + 60
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_shadow_needs_enough_round_trips(client):
    j(client, "import", json={"text": aapl_file(2), "broker": "generic"})
    r = j(client, "shadow", json={})
    assert r.status_code == 400 and "NOT RUNNABLE" in r.json()["error"]


def test_shadow_account_runs_as_a_job_with_labels(client):
    j(client, "import", json={"text": aapl_file(), "broker": "generic"})
    r = j(client, "shadow", json={"rule": "hold", "hold_days": 5})
    assert r.status_code == 200, r.text
    job = wait(client, r.json()["id"])
    assert job["kind"] == "journal.shadow" and job["state"] == "done", job
    res = job["result"]
    assert res["labels"]["headline"] == "HISTORICAL SIMULATION, NOT A FORECAST" and res["labels"]["fixtures"] is True
    assert res["labels"]["sources"][0]["name"] and res["rule"]["hold_days"] == 5 and res["replayed"] == 8
    assert res["you"]["equity"] and res["alt"]["equity"] and any("EQUAL-WEIGHT" in n for n in res["labels"]["notes"])
    stop = wait(client, j(client, "shadow", json={"rule": "stop_target", "stop_pct": 1, "target_pct": 2}).json()["id"])
    assert stop["state"] == "done" and stop["result"]["rule"]["kind"] == "stop_target"


def test_shadow_bad_inputs_are_400(client):
    j(client, "import", json={"text": aapl_file(), "broker": "generic"})
    assert j(client, "shadow", json={"rule": "martingale"}).status_code == 400
    assert j(client, "shadow", json={"hold_days": 0}).status_code == 400


def test_the_internal_job_kind_is_not_submittable_directly(client):
    r = client.post("/api/jobs", json={"kind": "journal.shadow", "params": {}})
    assert r.status_code in (400, 403, 404, 422)


# ------------------------------------------------------------------------------------------------ AI tool
def test_journal_tool_is_read_only_and_cleanly_named():
    t = toolbox.REGISTRY["journal"]
    text = (t.name + " " + t.description).lower()
    for banned in ("order", "gtt", "margin", "holding", "kite"):
        assert banned not in text
    assert t.desk_only and t.path == "/api/journal/analysis" and set(t.parameters["properties"]) == {"currency"}
    assert "journal" not in {x["function"]["name"] for x in toolbox.openai_tools()}  # not in plain chat
    from openterm.mcp import server

    assert "journal" not in {x["name"] for x in server.tool_list()}  # private: never offered to outside clients


def test_journal_tool_shape_hides_trades():
    shaped = toolbox.shape_journal({"empty": True}, {})
    assert shaped["empty"] is True
    resp = {"currency": "USD", "currencies": [{"currency": "USD"}], "stats": {"n": 3, "win_rate": 0.5, "secret": 1},
            "round_trips": [{"id": "x"}], "diagnostics": [{"id": "revenge", "status": "clear", "severity": "none", "plain": "p", "trips": [1]}]}
    out = toolbox.shape_journal(resp, {})
    assert "round_trips" not in out and "secret" not in out["stats"] and out["findings"][0]["id"] == "revenge" and "trips" not in out["findings"][0]
