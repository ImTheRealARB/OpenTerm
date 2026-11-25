"""Phase 23 order flow: aggTrades parser, footprint binning and delta, imbalance, big-trade filter, tick rule, and the
`/api/world/flow/*` routes on the REAL recorded BTCUSDT trades (fixture mode, no network)."""

import json
from pathlib import Path

import pytest

from openterm.providers.base import ProviderError
from openterm.world import orderflow as of
from openterm.world.orderflow import Trade

FIX = Path(__file__).parent / "fixtures" / "binance_aggtrades_btcusdt.json"


def T(i, t, p, q, buy):
    return Trade(i, t, p, q, buy)


# --- parser ----------------------------------------------------------------------------------------------------------------------------------------
def test_buyer_is_maker_flag_means_the_aggressor_sold():
    rows = [{"a": 2, "T": 2000, "p": "100.5", "q": "0.2", "m": False}, {"a": 1, "T": 1000, "p": "100.4", "q": "0.1", "m": True}]
    got = of.parse_agg_trades(rows)
    assert [t.id for t in got] == [1, 2]  # sorted oldest first
    assert got[0].buy is False and got[1].buy is True  # m=true -> SELL, m=false -> BUY
    assert got[0].p == 100.4 and got[1].q == 0.2


def test_parser_fails_loudly_on_a_bad_answer():
    with pytest.raises(ProviderError):
        of.parse_agg_trades({"code": -1121})
    with pytest.raises(ProviderError):
        of.parse_agg_trades([{"a": 1}])


def test_recorded_trades_parse_and_split_into_both_sides():
    trades = of.parse_agg_trades(json.loads(FIX.read_text(encoding="utf-8"))["body"])
    assert len(trades) == 1000 and trades[0].id < trades[-1].id
    sells = sum(1 for t in trades if not t.buy)
    assert 0 < sells < 1000  # a real minute of BTCUSDT has both aggressors


def test_merge_pages_drops_repeated_ids():
    a = [T(1, 1, 1, 1, True), T(2, 2, 1, 1, True)]
    b = [T(2, 2, 1, 1, True), T(3, 3, 1, 1, False)]
    assert [t.id for t in of.merge_pages([a, b])] == [1, 2, 3]


# --- footprint -------------------------------------------------------------------------------------------------------------------------------------
def test_nice_step_rounds_up_to_1_2_5():
    assert of.nice_step(0.7) == 1 and of.nice_step(1.3) == 2 and of.nice_step(3.0) == 5 and of.nice_step(7.0) == 10
    assert of.nice_step(0.03) == 0.05
    with pytest.raises(ValueError):
        of.nice_step(0)


MIN = 60_000
HAND = [
    T(1, 0, 100.2, 1.0, False),  # level 100: sold into the bid
    T(2, 1000, 100.7, 2.0, True),  # level 100: bought at the ask
    T(3, 2000, 101.1, 3.0, True),  # level 101: bought
    T(4, 3000, 101.5, 0.5, False),  # level 101: sold
    T(5, MIN, 102.0, 1.0, True),  # next bar, level 102
]


def test_footprint_bins_bid_and_ask_volume_per_level_and_bar():
    fp = of.footprint(HAND, MIN, bars=10, step=1.0)
    assert fp["levels"] == [100.0, 101.0, 102.0] and fp["step"] == 1.0
    b1, b2 = fp["bars"]
    assert b1["t"] == 0 and b2["t"] == MIN
    cells = {c[0]: c for c in b1["cells"]}  # level index -> [level, bid, ask, flag]
    assert cells[0][1:3] == [1.0, 2.0] and cells[1][1:3] == [0.5, 3.0]
    assert (b1["bid"], b1["ask"], b1["vol"]) == (1.5, 5.0, 6.5)
    assert (b1["o"], b1["h"], b1["l"], b1["c"]) == (100.2, 101.5, 100.2, 101.5)
    assert b1["poc"] == 101.0  # 3.5 coins at 101 vs 3.0 at 100


def test_delta_and_cumulative_delta():
    fp = of.footprint(HAND, MIN, bars=10, step=1.0)
    b1, b2 = fp["bars"]
    assert b1["delta"] == 3.5 and b2["delta"] == 1.0  # ask - bid
    assert fp["cum_delta"] == [3.5, 4.5] and b2["cum_delta"] == 4.5


def test_imbalance_is_diagonal_three_to_one():
    fp = of.footprint(HAND, MIN, bars=10, step=1.0)
    cells = {c[0]: c for c in fp["bars"][0]["cells"]}
    # Level 101 asks 3.0; the bid one level BELOW (level 100) is 1.0 -> exactly 3:1 -> buyers' imbalance.
    assert cells[1][3] & of.FLAG_ASK
    # Level 100 bids 1.0; the ask one level ABOVE (level 101) is 3.0 -> not a sellers' imbalance.
    assert not cells[0][3] & of.FLAG_BID
    # Level 100 asks 2.0 with NO bid below it: counts (2.0 is over 2% of the bar) -- the empty-side rule.
    assert cells[0][3] & of.FLAG_ASK


def test_imbalance_ignores_dust_next_to_an_empty_side():
    trades = [T(1, 0, 100.5, 100.0, True), T(2, 1, 105.5, 0.01, True)]  # 0.01 is far below 2% of the bar's volume
    fp = of.footprint(trades, MIN, bars=1, step=1.0)
    flags = {c[0]: c[3] for c in fp["bars"][0]["cells"]}
    assert flags[0] & of.FLAG_ASK and flags[5] == 0


def test_footprint_keeps_only_the_newest_bars_and_marks_a_truncated_first_bar():
    trades = [T(1, 0, 100.0, 1, True), T(2, MIN, 100.0, 1, True), T(3, 2 * MIN, 100.0, 1, False)]
    fp = of.footprint(trades, MIN, bars=2, step=1.0)
    assert [b["t"] for b in fp["bars"]] == [MIN, 2 * MIN]
    assert not fp["bars"][0]["partial"]
    assert of.footprint(trades, MIN, bars=2, step=1.0, truncated=True)["bars"][0]["partial"]


def test_automatic_step_and_empty_input():
    trades = of.parse_agg_trades(json.loads(FIX.read_text(encoding="utf-8"))["body"])
    fp = of.footprint(trades, MIN, bars=5)
    assert 3 <= len(fp["levels"]) <= 90 and fp["step"] > 0
    assert sum(b["vol"] for b in fp["bars"]) == pytest.approx(sum(t.q for t in trades))
    assert of.footprint([], MIN, bars=5)["bars"] == []
    with pytest.raises(ValueError):
        of.footprint(HAND, MIN, bars=5, step=-1)


# --- big trades ------------------------------------------------------------------------------------------------------------------------------------
def test_big_trade_filter_by_coins_and_by_value():
    trades = [T(1, 1, 100.0, 0.5, True), T(2, 2, 100.0, 5.0, False), T(3, 3, 10.0, 6.0, True)]
    assert [t.id for t in of.big_trades(trades, min_qty=5)] == [3, 2]  # newest first
    assert [t.id for t in of.big_trades(trades, min_value=500)] == [2]  # 100 x 5 = 500; 10 x 6 = 60
    assert of.big_trades(trades, min_qty=5, min_value=500)[0].id == 2
    with pytest.raises(ValueError):
        of.big_trades(trades)


# --- tick rule -------------------------------------------------------------------------------------------------------------------------------------
def test_tick_rule_up_down_unchanged_and_first():
    assert of.tick_rule([10, 11, 11, 10, 10, 10, 12]) == [None, "B", "B", "S", "S", "S", "B"]
    assert of.tick_rule([]) == []
    # Continuing a stream: the caller hands over the previous price and side.
    assert of.tick_rule([10, 9], prev_price=10, prev_side="B") == ["B", "S"]


# --- routes (fixture mode) -------------------------------------------------------------------------------------------------------------------------
def test_tas_route_newest_first_with_exact_label(client):
    r = client.get("/api/world/flow/trades", params={"sym": "BTC-USDT", "limit": 5}).json()
    d = r["data"]
    assert r["source"] == "binance_deriv" and d["basis"] == "EXACT (EXCHANGE TRADES)" and d["pair"] == "BTC/USDT"
    ids = [x["id"] for x in d["rows"]]
    assert len(ids) == 5 and ids == sorted(ids, reverse=True)
    assert d["rows"][0]["side"] in ("BUY", "SELL") and d["rows"][0]["value"] == pytest.approx(d["rows"][0]["p"] * d["rows"][0]["q"])


def test_bigtrades_route_filters_and_echoes_the_filter(client):
    d = client.get("/api/world/flow/bigtrades", params={"sym": "BTCUSDT", "min": 0.1}).json()["data"]
    assert d["filter"] == {"min_qty": 0.1, "usd": None}
    assert d["rows"] and all(x["q"] >= 0.1 for x in d["rows"]) and d["scanned"] == 1000
    d2 = client.get("/api/world/flow/bigtrades", params={"sym": "BTCUSDT", "usd": 50000}).json()["data"]
    assert all(x["value"] >= 50000 for x in d2["rows"])
    default = client.get("/api/world/flow/bigtrades", params={"sym": "BTCUSDT"}).json()["data"]
    assert default["filter"]["usd"] == 100_000  # the documented default for a USD pair


def test_footprint_route_shape_and_truncation(client):
    d = client.get("/api/world/flow/footprint", params={"sym": "BTCUSDT", "interval": "1m", "bars": 10}).json()["data"]
    assert d["interval"] == "1m" and d["bars"] and d["levels"] and d["truncated"] is True  # one recorded minute < 10 bars
    assert d["bars"][0]["partial"] is True
    assert sum(b["vol"] for b in d["bars"]) == pytest.approx(sum(sum(c[1] + c[2] for c in b["cells"]) for b in d["bars"]))
    assert d["cum_delta"][-1] == pytest.approx(sum(b["delta"] for b in d["bars"]))


def test_non_crypto_and_unknown_pairs_say_crypto_only(client):
    for sym in ("AAPL", "ETHUSDT", "$$$"):  # AAPL / ETHUSDT: Binance 400 (ETHUSDT is simply not recorded)
        r = client.get("/api/world/flow/trades", params={"sym": sym})
        assert r.status_code == 400, sym
        assert "ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS)" in r.text, sym
    assert client.get("/api/world/flow/footprint", params={"sym": "AAPL"}).status_code == 400


def test_an_indian_symbol_without_a_kite_ticker_is_a_clean_user_error_not_a_500(client):
    """TAS for `RELIANCE.NS` goes to the Kite tape (not Binance). With no Kite ticker (fixture mode / not logged in) it must say what
    to do, with a 4xx and a `kind`, never a 500 (an error kind with no HTTP status used to fall through to 500)."""
    r = client.get("/api/world/flow/trades", params={"sym": "RELIANCE.NS"})
    assert r.status_code == 401 and r.json()["kind"] == "login_required"
    assert "KITE" in r.json()["error"]


def test_bad_arguments_are_400(client):
    assert client.get("/api/world/flow/footprint", params={"sym": "BTCUSDT", "interval": "2m"}).status_code == 400
    assert client.get("/api/world/flow/bigtrades", params={"sym": "BTCUSDT", "min": -1}).status_code == 422
    assert client.get("/api/world/flow/bigtrades", params={"sym": "BTC-EUR", "usd": 1000}).status_code == 400
