"""Phase 29 fundamentals maths (pure): scores, GF series, frames rules and stats, EM matrix, revision score."""

import math
from datetime import date

import pytest

from openterm.fund import estimates as es
from openterm.fund import frames as fr
from openterm.fund import metrics as mt
from openterm.fund import scores as sc

YEAR = {"revenue": 1000.0, "cost_of_revenue": 600.0, "gross_profit": 400.0, "operating_income": 150.0, "net_income": 100.0,
        "total_assets": 2000.0, "total_liabilities": 1200.0, "current_assets": 800.0, "current_liabilities": 500.0,
        "retained_earnings": 300.0, "equity": 800.0, "long_term_debt": 400.0, "operating_cf": 160.0, "shares_diluted": 50.0,
        "receivables": 120.0, "ppe": 500.0, "da": 60.0, "sga": 90.0}


def test_altman_beneish_piotroski_ohlson_known_values():
    z = sc.altman_z(YEAR, market_cap=2400.0)
    # 1.2*0.15 + 1.4*0.15 + 3.3*0.075 + 0.6*2.0 + 1.0*0.5 = 2.3375 (grey zone)
    assert z["score"] == pytest.approx(2.3375) and z["zone"] == "GREY"
    assert sc.altman_z(YEAR, None)["missing"] == ["market_cap"] and sc.altman_z(YEAR, None)["score"] is None
    # Same year twice: every index is 1, so M = -4.84 + 0.920 + 0.528 + 0.404 + 0.892 + 0.115 - 0.172 - 0.327 + 4.679 TATA
    m = sc.beneish_m(YEAR, YEAR)["score"]
    assert m == pytest.approx(-2.48 + 4.679 * (100 - 160) / 2000)
    better = {**YEAR, "net_income": 150.0, "operating_cf": 200.0, "revenue": 1100.0, "gross_profit": 480.0, "long_term_debt": 300.0, "current_assets": 900.0}
    f = sc.piotroski_f(better, YEAR)
    assert f["score"] == 9.0 and f["zone"] == "STRONG"
    o = sc.ohlson_o(YEAR, YEAR)
    assert o["score"] is not None and 0 < dict(o["inputs"])["PROBABILITY"] < 1


def test_merton_solution_satisfies_both_equations():
    out = sc.merton_dd(equity=100.0, sigma_e=0.4, current_liabilities=60.0, long_term_debt=40.0, r=0.04)
    inp = dict(out["inputs"])
    v, sv, d, r = inp["ASSET VALUE V (SOLVED)"], inp["ASSET VOL (SOLVED)"], inp["DEFAULT POINT D"], 0.04
    n = sc._N.cdf
    d1 = (math.log(v / d) + (r + sv * sv / 2)) / sv
    d2 = d1 - sv
    assert d == 80.0
    assert v * n(d1) - d * math.exp(-r) * n(d2) == pytest.approx(100.0, rel=1e-5)  # equity is a call on the assets
    assert n(d1) * sv * v == pytest.approx(0.4 * 100.0, rel=1e-5)                # equity vol links to asset vol
    assert out["score"] > 2 and sc.merton_dd(100.0, None, 60.0, 40.0, 0.04)["missing"] == ["equity_vol"]


def test_valuation_series_uses_only_filed_periods():
    rows = [{"end": "2023-12-31", "filed": "2024-02-01", "eps_diluted": 2.0, "label": "FY2023"},
            {"end": "2024-12-31", "filed": "2025-02-01", "eps_diluted": 4.0, "label": "FY2024"}]
    t = [mt.epoch("2024-01-15"), mt.epoch("2024-06-03"), mt.epoch("2025-01-20"), mt.epoch("2025-03-03")]
    pts = mt.valuation_series(rows, "PE", t, [50.0, 60.0, 80.0, 80.0])
    # Before the first filing: no value at all; after FY2024 is filed the EPS switches from 2 to 4.
    assert [v for _, v in pts] == [30.0, 40.0, 20.0]
    q = [{"revenue": float(i), "label": f"Q{i}"} for i in range(1, 6)]
    assert [r["revenue"] for r in mt.ttm(q)] == [None, None, None, 10.0, 14.0]
    lad = mt.ladder({"mat_y1": 10.0, "mat_y2": 30.0, "mat_after": 60.0})
    assert [x["share"] for x in lad] == [0.1, 0.3, None, None, None, 0.6]


def test_frames_rules_known_date_and_stats():
    assert fr.parse_rules(["margin>0.1", "ROE>=15%"]) == [("MARGIN", ">", 0.1), ("ROE", ">=", 0.15)]
    with pytest.raises(ValueError):
        fr.parse_rules(["PE<10"])
    vals = fr.fields_for({"revenue": 100.0, "net_income": 20.0, "equity": 50.0, "liabilities": 25.0, "operating_income": 30.0},
                         {"revenue": 80.0})
    assert vals["MARGIN"] == 0.2 and vals["GROWTH"] == pytest.approx(0.25) and vals["DE"] == 0.5
    assert fr.passes(vals, [("MARGIN", ">", 0.1)]) and not fr.passes({"MARGIN": None}, [("MARGIN", ">", 0.1)])
    assert fr.known_date("2024-12-31") == date(2025, 3, 31) and fr.known_date("2024-09-30", annual=False) == date(2024, 11, 14)
    s = fr.stats([0.1, -0.1])
    assert s["total"] == pytest.approx(-0.01) and s["maxdd"] == pytest.approx(-0.1) and s["hit"] == 0.5
    assert fr.iqr([1.0, 2.0, 3.0, 4.0, 5.0]) == 2.0


def test_em_matrix_and_revision_score():
    q = [{"label": "Q1 FY2025", "end": "2024-12-28", "eps_diluted": 2.4, "revenue": 1.2e11},
         {"label": "FY2024", "end": "2024-09-28"}]
    m = es.matrix(q, [{"quarter": "2024-12-31", "actual": 2.4, "estimate": 2.35, "surprise": 0.021}])
    assert m["years"] == [2025] and m["cells"][("Q1", 2025)]["est"] == 2.35
    r = es.revision_score([{"period": "0Q", "now": 1.05, "d30": 1.0, "d90": 0.9}], [{"period": "0Q", "up30": 3, "down30": 1}])
    # breadth (3-1)/4 = 0.5; drift 5% / 5% = 1 -> 50*0.5 + 50*1 = 75
    assert r["score"] == pytest.approx(75.0)


def test_split_adjust_puts_old_eps_on_todays_share_basis():
    rows = [{"end": "2018-09-29", "shares_diluted": 5.0e9, "eps_diluted": 11.9},
            {"end": "2019-09-28", "shares_diluted": 18.6e9, "eps_diluted": 2.97},  # restated after the 4-for-1 split
            {"end": "2020-09-26", "shares_diluted": 17.5e9, "eps_diluted": 3.28}]
    out, notes = mt.split_adjust(rows)
    assert out[0]["eps_diluted"] == pytest.approx(11.9 / 4) and out[0]["shares_diluted"] == 20.0e9
    assert out[1]["eps_diluted"] == 2.97 and len(notes) == 1 and "x4" in notes[0]
