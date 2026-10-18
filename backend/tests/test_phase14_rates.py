"""Phase 14 step 6: pure parsers of the RATES views (openterm/rates/parse.py), on the recorded answers in tests/fixtures. No I/O."""

import json
from pathlib import Path

import pytest

from openterm.rates import parse as rp

FIX = Path(__file__).parent / "fixtures"


def body(name: str):
    rec = json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))
    return rec["body"] if "body" in rec else rec["text"]


def by_tenor(curve: dict) -> dict:
    return {t["tenor"]: t for t in curve["tenors"]}


def test_tenor_years():
    assert rp.tenor_years("3M") == 0.25 and rp.tenor_years("10Y") == 10.0
    with pytest.raises(rp.RatesParseError):
        rp.tenor_years("LONG")


def test_ecb_sdmx_json_latest_and_history():
    c = rp.parse_ecb(body("ecb_yc_spot"))
    assert [t["tenor"] for t in c["tenors"]] == ["3M", "6M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y"]   # sorted by maturity
    assert c["dates"][0] == "2026-10-02" and c["dates"][-1] == "2026-10-15" and len(c["dates"]) == 10
    t10 = by_tenor(c)["10Y"]   # series 0 of the recording (SR_10Y)
    assert t10["years"] == 10.0 and t10["values"][0] == pytest.approx(3.4639685465) and t10["values"][-1] == pytest.approx(3.390425514)
    assert by_tenor(c)["3M"]["years"] == 0.25
    rows = {r["tenor"]: r for r in rp.curve_rows(c)}
    assert rows["10Y"]["yield"] == pytest.approx(3.390425514)
    assert rows["10Y"]["d1"] == pytest.approx((3.390425514 - 3.510796188) * 100)
    assert rows["10Y"]["d5"] == pytest.approx((3.390425514 - 3.51918971) * 100)   # observation index 4 is five back from index 9


def test_ecb_rejects_other_shapes():
    with pytest.raises(rp.RatesParseError):
        rp.parse_ecb({"nope": 1})


def test_boc_valet_keeps_fixed_maturities_only():
    c = rp.parse_boc(body("boc_yields"))
    assert [t["tenor"] for t in c["tenors"]] == ["2Y", "3Y", "5Y", "7Y", "10Y"]   # LONG and RRB have no fixed maturity
    assert c["dates"][0] == "2026-10-01" and c["dates"][-1] == "2026-10-15"       # the source lists newest first; sorted here
    rows = {r["tenor"]: r for r in rp.curve_rows(c)}
    assert rows["10Y"]["yield"] == pytest.approx(3.83)
    assert rows["10Y"]["d1"] == pytest.approx((3.83 - 3.85) * 100)
    assert rows["10Y"]["d5"] == pytest.approx((3.83 - 3.94) * 100)   # five observations back is 2026-10-07


def test_mof_csv_dashes_are_missing_and_dates_are_iso():
    text = "Interest Rate,,,(Unit : %)\nDate,1Y,2Y,40Y\n2026/7/30,1.2,1.5,-\n2026/7/31,1.255,1.507,3.967\n2026/8/3,1.287,1.562,3.948\n"
    c = rp.parse_mof(text)
    assert c["dates"] == ["2026-07-30", "2026-07-31", "2026-08-03"]
    t40 = by_tenor(c)["40Y"]
    assert t40["values"] == [None, 3.967, 3.948]   # a missing value is None, never filled
    rows = {r["tenor"]: r for r in rp.curve_rows(c)}
    assert rows["1Y"]["d1"] == pytest.approx((1.287 - 1.255) * 100) and rows["1Y"]["d5"] is None   # fewer than six observations
    real = rp.parse_mof(body("mof_jgb"))
    assert real["dates"][-1] == "2026-09-30" and len(real["tenors"]) == 15 and len(real["dates"]) == 40
    assert rp.parse_mof(body("mof_jgb"), keep=5)["dates"][0] == "2026-09-24"


def test_boe_csv_par_yields():
    c = rp.parse_boe(body("boe_par_yields"))
    assert [t["tenor"] for t in c["tenors"]] == ["5Y", "10Y", "20Y"]
    assert c["dates"][0] == "2026-09-01" and c["dates"][-1] == "2026-10-14"
    assert {r["tenor"]: r["yield"] for r in rp.curve_rows(c)} == pytest.approx({"5Y": 4.9692, "10Y": 5.383, "20Y": 5.7225})
    with pytest.raises(rp.RatesParseError):
        rp.parse_boe("<html>blocked</html>")


def test_curve_points_skip_missing():
    c = {"dates": ["a", "b"], "tenors": [{"tenor": "1Y", "years": 1.0, "values": [1.0, 2.0]}, {"tenor": "2Y", "years": 2.0, "values": [1.5, None]}]}
    assert rp.curve_points(c) == [(1.0, 2.0)]


def test_oas_csv_skips_headers_and_missing_values():
    text = "observation_date,BAMLC0A0CM\n2026-10-13,.\n2026-10-14,0.84\n2026-10-15,\n2026-10-16,0.85\n"
    assert rp.parse_oas_csv(text, "BAMLC0A0CM") == [("2026-10-14", 0.84), ("2026-10-16", 0.85)]
    with pytest.raises(rp.RatesParseError):
        rp.parse_oas_csv(text, "OTHER")
    real = rp.parse_oas_csv(body("fred_csv_BAMLC0A0CM"), "BAMLC0A0CM")   # the recording repeats its header line
    assert real[-1] == ("2026-10-15", 0.84) and all(len(d) == 10 for d, _ in real)


def test_oas_row_changes_and_percentile():
    obs = [(f"2026-01-{i:02d}", float(i)) for i in range(1, 29)]   # 1.0 .. 28.0 percent
    r = rp.oas_row("X", "name", obs)
    assert r["bp"] == pytest.approx(2800.0) and r["date"] == "2026-01-28"
    assert r["d1"] == pytest.approx(100.0) and r["d5"] == pytest.approx(500.0) and r["d21"] == pytest.approx(2100.0)
    assert r["pct_1y"] == pytest.approx(100.0)   # today's value is the highest of the window
    falling = rp.oas_row("X", "name", [("2026-01-01", 3.0), ("2026-01-02", 2.0), ("2026-01-03", 1.0), ("2026-01-04", 2.5)])
    assert falling["pct_1y"] == pytest.approx(75.0) and falling["d5"] is None and falling["d21"] is None
    assert rp.oas_row("X", "name", [])["bp"] is None


def test_oas_percentile_window_is_one_year():
    obs = [("2024-01-01", 9.0), ("2026-01-01", 1.0), ("2026-01-02", 2.0)]
    assert rp.oas_row("X", "n", obs)["pct_1y"] == pytest.approx(100.0)   # the 2024 value is outside the last 365 days


def test_auctions_parse_and_order():
    rows = rp.parse_auctions(body("treasurydirect_auctioned"))
    assert len(rows) == 35
    first = rows[0]
    assert first["cusip"] == "912797VX2" and first["auction_date"] == "2026-10-15" and first["issue_date"] == "2026-10-20"
    assert first["offering"] == pytest.approx(110e9) and first["bid_to_cover"] == pytest.approx(2.56) and first["high_rate"] == pytest.approx(4.0)
    dates = [r["auction_date"] for r in rp.newest_first(rows)]
    assert dates == sorted(dates, reverse=True)
    assert rp.newest_first(rows)[0]["cusip"] == first["cusip"]   # stable within a day
    up = rp.parse_auctions(body("treasurydirect_upcoming"))
    assert up[0]["bid_to_cover"] is None and up[0]["high_rate"] is None   # not auctioned yet: nothing invented
    soon = [r["auction_date"] for r in rp.soonest_first(up)]
    assert soon == sorted(soon)
