"""Phase 14 step 5: pure pieces of the surface (openterm.options.surface, hivg, chain): no client, no network."""

import json
import math
from pathlib import Path

import pytest

from openterm.options import chain as ch
from openterm.options import hivg as hv
from openterm.options import surface as sf
from openterm.options import tables as ot

FIX = Path(__file__).parent / "fixtures"


def test_pick_expiries_is_the_rule_the_recorder_used():
    rec = json.loads((FIX / "yahoo_options_aapl_1792368000.json").read_bytes().decode("utf-8"))["body"]
    dates = rec["optionChain"]["result"][0]["expirationDates"]
    picked = sf.pick_expiries(dates)
    assert len(picked) == 8 and picked[0] == dates[0]
    for ep in picked:
        assert (FIX / f"yahoo_options_aapl_{ep}.json").exists()   # the eight recorded chains are exactly these
    assert sf.pick_expiries([]) == [] and sf.pick_expiries([5]) == [5]
    assert sf.pick_expiries([5, 5 + 86400]) == [5, 5 + 86400]


def test_fit_recovers_an_exact_quadratic_and_refuses_thin_data():
    ks = [-0.3, -0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 0.3]
    f = sf.fit_smile([(k, 0.25 - 0.1 * k + 0.5 * k * k) for k in ks])
    assert (f.a, f.b, f.c) == pytest.approx((0.25, -0.1, 0.5), abs=1e-10)
    assert f.rmse < 1e-12 and f.n == 9 and (f.k_min, f.k_max) == (-0.3, 0.3)
    assert sf.fit_smile([(0.0, 0.2)] * 8) is None            # all at one k
    assert sf.fit_smile([(k, 0.2) for k in ks[:5]]) is None  # fewer than MIN_POINTS


def test_fit_is_never_extrapolated():
    ks = [-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05]
    f = sf.fit_smile([(k, 0.3 + 2.0 * k * k) for k in ks])
    row = sf.grid_row(f)
    assert row[4] == pytest.approx(0.3)                      # moneyness 1.00 is inside the quotes
    assert row[0] is None and row[-1] is None                # 80% and 120% are far outside +/-5% in k
    assert f.iv_in_range(0.2) is None and f.iv_in_range(0.04) == pytest.approx(0.3 + 2 * 0.04**2)


def test_delta_strike_on_a_flat_smile_matches_the_closed_form():
    f = sf.fit_smile([(k / 20, 0.2) for k in range(-12, 13)])
    T, s = 0.5, 0.2
    kc = sf.delta_strike(f, T, True)
    assert kc == pytest.approx(0.5 * s * s * T + 0.6744897501960817 * s * math.sqrt(T), abs=1e-7)
    kp = sf.delta_strike(f, T, False)
    assert kp == pytest.approx(0.5 * s * s * T - 0.6744897501960817 * s * math.sqrt(T), abs=1e-7)
    m = sf.skew_metrics(f, T)
    assert m["rr25"] == pytest.approx(0.0, abs=1e-9) and m["bf25"] == pytest.approx(0.0, abs=1e-9)
    # a strike outside the quoted range is not reported
    thin = sf.fit_smile([(k / 100, 0.2) for k in range(-6, 7)])
    assert sf.delta_strike(thin, 1.0, True) is None


def test_total_variance_interpolation():
    flat = [(0.1, 0.3), (0.5, 0.3), (1.0, 0.3)]
    assert sf.interp_total_variance(flat, 0.25) == (pytest.approx(0.3), False)
    iv, outside = sf.interp_total_variance(flat, 2.0)
    assert iv == 0.3 and outside
    # linear in total variance: sigma^2 T halfway between 0.04*0.25 and 0.09*0.75 at T = 0.5
    iv, _ = sf.interp_total_variance([(0.25, 0.2), (0.75, 0.3)], 0.5)
    assert iv == pytest.approx(math.sqrt((0.04 * 0.25 + 0.09 * 0.75) / 2 / 0.5))


def test_realized_vol_by_hand():
    closes = [100.0, 101.0, 100.0, 102.0, 101.0, 103.0]
    r = hv.log_returns(closes)
    assert len(r) == 5
    mean = sum(r) / 5
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / 4)
    assert hv.cc_vol(r, 5) == pytest.approx(sd * math.sqrt(252))
    assert hv.cc_vol(r, 6) is None and hv.cc_vol([None, 0.01, 0.02], 3) is None
    assert hv.cc_vol([0.01] * 10, 10) == pytest.approx(0.0, abs=1e-12)
    hi, lo = [101.0, 102.0], [99.0, 100.0]
    want = math.sqrt((math.log(101 / 99) ** 2 + math.log(102 / 100) ** 2) / (4 * math.log(2) * 2)) * math.sqrt(252)
    assert hv.parkinson_vol(hi, lo, 2) == pytest.approx(want)
    roll = hv.rolling_cc(r, 3)
    assert roll[:2] == [None, None] and roll[2] == pytest.approx(hv.cc_vol(r[:3], 3))
    assert hv.percentile_rank([0.2, 0.3, 0.4], 0.3) == (pytest.approx(0.5), pytest.approx(2 / 3))


def test_deribit_parse_uses_mark_iv_and_the_expiry_forward():
    book = json.loads((FIX / "deribit_book_btc.json").read_bytes().decode("utf-8"))["body"]
    index = json.loads((FIX / "deribit_index_btc.json").read_bytes().decode("utf-8"))["body"]
    out = ch.parse_deribit(book, index, "BTC", "deribit")
    assert out["index"] == 81483.01 and len(out["expiries"]) == 4
    first = out["expiries"][0]
    assert first["expiry"] == ch.deribit_expiry("18OCT26") and first["forward"] > 80000
    inst = next(x for x in book["result"] if x["instrument_name"] == "BTC-18OCT26-85000-C")
    call = next(c for c in first["calls"] if c["strike"] == 85000.0)
    assert call["iv"] == inst["mark_iv"] / 100.0 and call["oi"] == inst["open_interest"]
    assert ch.deribit_expiry("6NOV26") == ch.deribit_expiry("06NOV26")   # a day without a leading zero parses


def test_years_to_expiry_and_greeks_without_an_iv():
    assert ch.years_to_expiry(1792368000, 1792368000 + 20 * 3600) == 0.0
    assert ch.years_to_expiry(1792368000, 1792368000 + 10 * 3600) == pytest.approx(10 * 3600 / (365 * 86400))
    c = {"strike": 100.0, "bid": 0.0, "ask": 0.05, "iv_vendor": 1e-05}
    row = ch.greeks_row(c, "call", 90.0, 0.5, 0.04, 0.0)   # no two-sided market and the vendor IV is a placeholder
    assert row["iv"] is None and row["delta"] is None and row["iv_src"] is None
    d = ot.keep("call", 90.0, 100.0, "ITM")
    assert d is True and ot.keep("put", 90.0, 100.0, "ITM") is False
