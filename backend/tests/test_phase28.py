"""Phase 28 options analytics: pure maths only (minimal test bar)."""

import math

from openterm.options import analytics as an


def test_probabilities_and_touch():
    # ATM, zero rate: P(call ITM) = N(-0.5 sigma sqrt T) just under one half; call + put probabilities sum to 1.
    pc = an.prob_itm(100, 100, 1.0, 0.0, 0.0, 0.2, "call")
    pp = an.prob_itm(100, 100, 1.0, 0.0, 0.0, 0.2, "put")
    assert abs(pc - an.ncdf(-0.1)) < 1e-12 and abs(pc + pp - 1) < 1e-12
    assert an.prob_itm(100, 100, 1.0, 0.0, 0.0, None, "call") is None
    assert an.prob_touch(0.3, False) == 0.6 and an.prob_touch(0.7, False) == 1.0 and an.prob_touch(0.2, True) == 1.0
    rows = [{"strike": 90, "iv": 0.2, "bid": 11, "ask": 12, "last": None}]
    an.prob_columns(rows, "call", 100, 0.5, 0.0, 0.0)
    assert rows[0]["breakeven"] == 101.5 and rows[0]["extrinsic"] == 1.5 and rows[0]["p_touch"] == 1.0


def test_expected_move_max_pain_walls():
    calls = [{"strike": k, "bid": b, "ask": b + 0.2, "oi": o, "volume": 1} for k, b, o in ((95, 6, 10), (100, 3, 500), (105, 1, 900))]
    puts = [{"strike": k, "bid": b, "ask": b + 0.2, "oi": o, "volume": 1} for k, b, o in ((95, 1, 800), (100, 3, 300), (105, 6, 5))]
    em = an.expected_move(100, 0.25, calls, puts, 0.2)
    assert em["strike"] == 100 and abs(em["straddle"] - 6.2) < 1e-9 and abs(em["sigma"] - 10.0) < 1e-9
    assert an.max_pain(calls, puts) == 100
    assert an.walls(calls) == 105 and an.walls(puts) == 95


def test_pl_curves_and_probability_of_profit():
    legs = [{"qty": 1, "type": "C", "strike": 100}]
    curve = an.pl_curves(legs, [5.0], [80 + j for j in range(41)], 0.5, 0.0, 0.2, 100, 30, 0.0)
    at = {c["spot"]: c for c in curve}
    assert at[80]["expiry"] == -500 and abs(at[120]["expiry"] - 1500) < 1e-9
    assert at[120]["today"] > at[120]["expiry"]  # time value left before expiry
    pop = an.prob_profit(curve, 100, 0.5, 0.0, 0.2)
    # P(S_T > 105) under the model, within the grid's half-step resolution
    exact = 1 - an.ncdf((math.log(105 / 100) + 0.5 * 0.04 * 0.5) / (0.2 * math.sqrt(0.5)))
    assert abs(pop - exact) < 0.03


def test_cone_buildup_rank_occ_report_moves():
    c = an.cone(100, [(2.0, 1.0, 0.2), (1.0, 0.0, 0.2)])
    assert len(c) == 1 and abs(c[0]["hi1"] - 100 * math.exp(0.2)) < 1e-9
    assert an.buildup(1, 5) == "LONG BUILDUP" and an.buildup(-1, 5) == "SHORT BUILDUP"
    assert an.buildup(1, -5) == "SHORT COVERING" and an.buildup(-1, -5) == "LONG UNWINDING" and an.buildup(0, 5) is None
    rank, pct = an.iv_rank([0.2, 0.4, 0.3], 0.3)
    assert abs(rank - 0.5) < 1e-12 and pct == 1 / 3
    assert an.parse_occ("AAPL260116C00200000") == {"root": "AAPL", "expiry": "2026-01-16", "type": "C", "strike": 200.0}
    day = 86400
    moves = an.report_moves(["1970-01-03"], [0, day, 2 * day, 3 * day], [10, 10, 11, 12])
    assert moves[0]["before"] == 10 and moves[0]["after"] == 12
