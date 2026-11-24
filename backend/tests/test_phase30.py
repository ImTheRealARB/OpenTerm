"""Phase 30 (macro, rates and commodities depth): the pure maths and the source parsers, fed with the recorded fixtures. No network,
no app. Routes and providers are covered by the fixture-mode smoke in the e2e suite (smoke_new_functions.spec.ts)."""

import base64
import json
import re
from datetime import date
from pathlib import Path

import pytest

from openterm.macrod import boards, calendars, curves, parse, xlsx
from openterm.macrod.service import percentile, rank_returns, value_before

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def load(name: str):
    rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    if "b64" in rec:
        return base64.b64decode(rec["b64"])
    return rec["text"] if "text" in rec else rec["body"]


# --- FWCV and WIRP odds ---------------------------------------------------------------------------------------------------------


def test_bootstrap_flat_curve_has_flat_zeros_and_forwards():
    zc = curves.bootstrap([0.5, 1, 2, 5, 10, 30], [5.0] * 6)
    assert all(abs(p["zero"] - 5.0) < 1e-9 for p in zc)
    assert all(abs(r["rate"] - 5.0) < 1e-9 for r in curves.forward_table(zc))
    with pytest.raises(ValueError, match="THREE"):
        curves.bootstrap([1, 2], [4.0, 4.1])


def test_bootstrap_upward_curve_forwards_above_spot():
    zc = curves.bootstrap([0.5, 1, 2, 5, 10], [4.0, 4.2, 4.5, 4.8, 5.0])
    f = {r["name"]: r for r in curves.forward_table(zc)}
    assert f["5y5y"]["rate"] > f["5y5y"]["spot_end"] > 4.0
    assert f["10y10y"]["rate"] is None  # off the curve: not extrapolated


def test_meeting_odds_standard_method():
    assert curves.meeting_odds(-10) == pytest.approx({0: 0.6, -1: 0.4})
    assert curves.meeting_odds(30) == pytest.approx({1: 0.8, 2: 0.2})
    assert curves.meeting_odds(0) == {0: 1.0}
    rows = curves.odds_table([{"meeting": "2026-12-09", "change_bp": -12.5, "cum_bp": -12.5},
                              {"meeting": "2027-01-27", "change_bp": -25.0, "cum_bp": -37.5}])
    assert rows[0]["p_cut"] == pytest.approx(0.5) and rows[0]["p_hold"] == pytest.approx(0.5)
    assert rows[1]["p_cut"] == pytest.approx(1.0) and rows[1]["mode_bp"] in (-25.0, -50.0) and rows[1]["mode_p"] == pytest.approx(0.5)


# --- CTM and CDR ----------------------------------------------------------------------------------------------------------------


def test_contract_rules():
    # CLF27: the 25th of Dec 2026 is a holiday, so 3 business days before Thu 24 Dec = Mon 21 Dec
    assert calendars.RULES["CL"][0](2027, 1) == date(2026, 12, 21)
    assert calendars.RULES["ES"][0](2026, 12) == date(2026, 12, 18)  # third Friday
    assert calendars.RULES["GC"][0](2026, 12) == date(2026, 12, 29)  # third-last business day (24 Dec half day counts, 25 Dec not)
    assert calendars.RULES["GC"][1](2026, 12) == date(2026, 11, 30)  # first notice: last business day of November
    rows = calendars.contracts("NG", date(2026, 11, 24))
    # NGZ26: third-last business day of November (26 Nov is Thanksgiving; 27 Nov trades) = Wed 25 Nov
    assert rows[0]["contract"] == "NGZ26" and rows[0]["last_trade"] == "2026-11-25"
    with pytest.raises(ValueError, match="NO RULE"):
        calendars.contracts("XX", date(2026, 1, 1))


def test_hours_mirror_frontend_table():
    ts = (ROOT / "frontend" / "src" / "markets" / "hours.ts").read_text(encoding="utf-8")
    for code, (_, tz, sessions) in calendars.HOURS.items():
        line = next(ln for ln in ts.splitlines() if f'code: "{code}"' in ln)
        assert f'tz: "{tz}"' in line
        hm = [(int(h), int(m or 0)) for h, m in re.findall(r"hm\((\d+)(?:, (\d+))?\)", line)]
        want = [tuple(int(x) for x in t.split(":")) for s in sessions for t in s.split("-")]
        assert hm == want, code


# --- parsers --------------------------------------------------------------------------------------------------------------------


def test_money_market_parsers():
    sofr = parse.nyfed(load("nyfed_sofr"))
    assert sofr[0]["date"] > sofr[-1]["date"] and 0 < sofr[0]["rate"] < 20 and sofr[0]["p1"] <= sofr[0]["p99"]
    estr = parse.ecb_csv(load("ecb_estr"))
    assert len(estr) > 20 and estr[0][0] > estr[-1][0]
    sonia = parse.boe_csv(load("boe_sonia"), "IUDSOIA")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", sonia[0][0])
    with pytest.raises(parse.ParseError):
        parse.nyfed({"x": 1})


def test_gdpnow_and_spf_workbooks():
    g = parse.gdpnow(load("atlfed_gdpnow_trimmed"))
    assert g["path"][0]["releases"].startswith("Initial GDPNow")
    q = g["past"][-1]
    assert q["n"] > 10 and q["bea"] is not None and re.fullmatch(r"\d{4}Q\d", q["quarter"])
    s = parse.spf(load("philfed_spf_rgdp"))
    assert re.fullmatch(r"\d{4}Q\d", s["survey"]) and len(s["quarterly"]) == 5
    u = parse.spf(load("philfed_spf_unemp"))
    assert u["annual"] and all(3 < a["value"] < 10 for a in u["annual"] if a["value"])


def test_xlsx_helpers():
    assert xlsx._col_index("A1") == 0 and xlsx._col_index("AB7") == 27
    assert xlsx.excel_date(46324.0) == date(2026, 10, 29)  # GDPNow's first 2026Q4 nowcast, the day after the Q3 advance estimate
    with pytest.raises(xlsx.XlsxError, match="NOT A ZIP"):
        xlsx.sheet_names(b"not a zip")


def test_forecast_parsers():
    imf = parse.imf_datamapper(load("imf_dm_ngdp_rpch"), "NGDP_RPCH")
    assert "USA" in imf and "2026" in imf["USA"]
    oecd = parse.oecd_csv(load("oecd_eo"))
    assert ("USA", "UNR") in oecd


def test_fomc_statement_and_diff():
    names = sorted(p.stem for p in FIX.glob("fed_statement_*.json"))
    old, new = (parse.fomc_statement(load(n)) for n in names[-2:])
    assert any("federal funds rate" in p for p in new)
    assert not any(p.startswith("For media") for p in new)
    d = parse.word_diff(["rates held at 4 percent"], ["rates cut to 3.75 percent"])
    assert [r["op"] for r in d] == ["SAME", "REMOVED", "ADDED", "SAME"]
    assert " ".join(r["text"] for r in parse.word_diff(old, new) if r["op"] != "REMOVED").replace(" ¶ ", " ") == " ".join(new)


def test_treasury_wasde_eia_nass_parsers():
    t = parse.td_securities(load("td_securities_auctioned"))
    assert all(len(r["cusip"]) == 9 for r in t) and any(r["interestRate"] for r in t)
    w = parse.wasde(load("wasde_xml_trimmed"))
    corn = next(x for x in w["tables"] if x["label"] == "US CORN")
    assert any(r["item"] == "Ending Stocks" for r in corn["rows"]) and len(corn["columns"]) >= 3
    links = parse.wasde_links(load("wasde_page"))
    assert links[0]["xml"].endswith(".xml")
    e = parse.eia_series(load("eia_docshape_pet_wcestus1_w"))
    assert e["points"][0][0] > e["points"][-1][0]
    n = parse.nass(load("nass_docshape_condition_corn_2026"))
    assert n[0]["value"] is not None


def test_etf_valuation_inverts_yahoo_ratios():
    spy = load("yahoo_etfval_wpe")["SPY"]
    v = parse.etf_valuation(spy)
    raw = spy["quoteSummary"]["result"][0]["topHoldings"]["equityHoldings"]["priceToEarnings"]["raw"]
    assert v["pe"] == pytest.approx(1 / raw) and 5 < v["pe"] < 80 and v["pe_source"] == "holdings"


# --- board helpers --------------------------------------------------------------------------------------------------------------


def test_series_helpers_and_currency_ranks():
    day = 86400
    pts = [(i * day, float(i)) for i in range(400)]
    assert value_before(pts, 365) == 34.0
    assert percentile([1, 2, 3, 4], 3) == 0.75
    rows = [{"date": "2025-12-31", "quote": "EUR", "rate": 0.90}, {"date": "2026-11-20", "quote": "EUR", "rate": 0.85},
            {"date": "2025-12-31", "quote": "INR", "rate": 85.0}, {"date": "2026-11-20", "quote": "INR", "rate": 90.0}]
    r = rank_returns(rows, date(2026, 11, 24))
    eur = next(x for x in r["USD"] if x["ccy"] == "EUR")
    assert eur["YTD"] == pytest.approx(0.90 / 0.85 - 1)  # fewer euros per dollar: the euro gained
    eur_inr = next(x for x in r["INR"] if x["ccy"] == "EUR")
    assert eur_inr["YTD"] == pytest.approx((90 / 0.85) / (85 / 0.90) - 1)


def test_board_ids_are_unique_and_recorded():
    assert len(boards.ALL_FRED) == len(set(boards.ALL_FRED))
    missing = [i for i in boards.ALL_FRED if not (FIX / f"fred_csv_{i}.json").exists()]
    assert missing == [], "run scripts/record_phase30.py fred"
