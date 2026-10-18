"""Phase 13: equity research gaps (spec: docs/specs/PHASE_13.md).

API-level contract tests written before the code, in fixture mode (no network). Each group is strict-xfail until its
build step lands; that step deletes the marker (EST = step 2, CORP = step 3, VAL = step 4, FUND = step 5, KEYED = step 6).
Expected numbers are read from the recorded answers in tests/fixtures (recorded 2026-10-18 by
scripts/record_phase13.py) and written out next to the assertion. Parser unit tests live in the per-step files.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def xf(group: str, step: int):
    return pytest.mark.xfail(strict=True, reason=f"Phase 13 step {step}: {group}")


EST = lambda f: f  # step 2 landed
CORP = lambda f: f  # step 3 landed
VAL = lambda f: f  # step 4 landed
FUND = lambda f: f  # step 5 landed
KEYED = xf("KEYED", 6)


def fixture_body(name: str):
    return json.loads((FIX / f"{name}.json").read_bytes().decode("utf-8"))


def data(client, path: str, **params):
    r = client.get(f"/api/{path}", params=params)
    assert r.status_code == 200, (path, params, r.status_code, r.text[:300])
    return r.json()


def section(d: dict, sid: str) -> dict:
    return next(s for s in d["data"]["sections"] if s["id"] == sid)


def headline(d: dict, label: str) -> dict:
    return next(h for h in d["data"]["headline"] if h["label"] == label)


def assert_table_payload(d: dict):
    """The shape every new function shares (decision A)."""
    p = d["data"]
    assert set(p) >= {"symbol", "title", "headline", "sections", "notes"}
    assert d["source"] and "stale" in d and "fallback_from" in d
    for s in p["sections"]:
        assert set(s) >= {"id", "title", "columns", "rows"}
        keys = {c["key"] for c in s["columns"]}
        assert all(c["kind"] in ("text", "int", "num", "pct", "money", "price", "date") for c in s["columns"])
        for row in s["rows"]:
            assert keys <= set(row), (s["id"], keys - set(row))


# --- EST: EE, EEO, ANR, MGMT ------------------------------------------------------------------------------------

@EST
def test_ee_estimates_by_period(client):
    d = data(client, "research/ee", symbol="AAPL")
    assert_table_payload(d)
    eps = section(d, "eps")
    assert [r["period"] for r in eps["rows"]] == ["CURRENT QTR", "NEXT QTR", "CURRENT YEAR", "NEXT YEAR"]
    cur = eps["rows"][0]  # recorded: 0q, end 2026-09-30
    assert cur["end"] == "2026-09-30"
    assert cur["avg"] == pytest.approx(1.97842)
    assert (cur["low"], cur["high"], cur["analysts"], cur["year_ago"]) == (1.93, 2.07, 27, 1.85)
    assert cur["growth"] == pytest.approx(0.0694)
    rev = section(d, "revenue")["rows"][0]
    assert rev["avg"] == 113626875100 and rev["year_ago"] == 102466000000
    assert d["source"].startswith("yahoo_research")


@EST
def test_ee_unknown_symbol_is_not_found(client):
    r = client.get("/api/research/ee", params={"symbol": "ZZZZNOPE"})
    assert r.status_code == 404 and r.json()["kind"] == "not_found"  # not FastAPI's own 404 for a missing route


@EST
def test_eeo_trend_revisions_and_surprises(client):
    d = data(client, "research/eeo", symbol="AAPL")
    assert_table_payload(d)
    trend = section(d, "trend")["rows"][0]
    assert (trend["now"], trend["d7"], trend["d30"], trend["d60"], trend["d90"]) == pytest.approx(
        (1.97842, 1.9785, 1.97754, 1.97656, 2.01755))
    rev = section(d, "revisions")["rows"][0]
    assert (rev["up7"], rev["up30"], rev["down7"], rev["down30"]) == (0, 1, 1, 1)
    sur = section(d, "surprises")["rows"]
    assert len(sur) == 4
    q = next(r for r in sur if r["quarter"] == "2025-09-30")  # recorded: actual 1.85 vs 1.76993, surprise 4.52%
    assert q["actual"] == 1.85 and q["estimate"] == pytest.approx(1.76993)
    assert q["diff"] == 0.08 and q["surprise"] == pytest.approx(0.0452)
    assert [r["quarter"] for r in sur] == sorted((r["quarter"] for r in sur), reverse=True)  # newest first


@EST
def test_anr_ratings_targets_and_actions(client):
    d = data(client, "research/anr", symbol="AAPL")
    assert_table_payload(d)
    assert headline(d, "TARGET MEAN")["raw"] == pytest.approx(329.3759)
    assert headline(d, "TARGET HIGH")["raw"] == 405.0 and headline(d, "TARGET LOW")["raw"] == 215.0
    assert headline(d, "ANALYSTS")["raw"] == 39
    assert headline(d, "UPSIDE TO MEAN TARGET")["raw"] == pytest.approx(329.3759 / 343.46 - 1)
    mix = section(d, "trend")["rows"][0]
    assert (mix["strong_buy"], mix["buy"], mix["hold"], mix["sell"], mix["strong_sell"]) == (6, 19, 13, 3, 3)
    act = section(d, "actions")["rows"][0]
    assert act["firm"] == "JP Morgan" and act["pt_action"] == "Raises"
    assert (act["pt"], act["pt_prior"]) == (360.0, 340.0)
    assert act["date"] == "2026-10-12"  # epoch 1791830866


@EST
def test_mgmt_officers_and_proxy(client):
    d = data(client, "research/mgmt", symbol="AAPL")
    assert_table_payload(d)
    first = section(d, "officers")["rows"][0]
    assert first["name"] == "Mr. Timothy D. Cook" and first["title"] == "Executive Chairman of the Board"
    assert (first["age"], first["pay"], first["fiscal_year"]) == (64, 16759518, 2025)
    assert headline(d, "EMPLOYEES")["raw"] == 150000
    assert section(d, "proxy")["rows"] is not None  # DEF 14A links from the filings feed (may be empty in the fixture)
    assert any("BOARD" in n for n in d["data"]["notes"])


# --- CORP: DVD, SPLT, CACS, IPO, SI, EVTS ------------------------------------------------------------------------

@CORP
def test_dvd_history_with_dates(client):
    d = data(client, "research/dvd", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "dividends")["rows"]
    top = rows[0]  # recorded Nasdaq: ex 08/10/2026 $0.27, declared 07/30, record 08/10, paid 08/13
    assert (top["ex_date"], top["amount"], top["declared"], top["record"], top["pay"]) == (
        "2026-08-10", 0.27, "2026-07-30", "2026-08-10", "2026-08-13")
    assert [r["ex_date"] for r in rows] == sorted((r["ex_date"] for r in rows), reverse=True)
    assert headline(d, "ANNUAL DIVIDEND")["raw"] == pytest.approx(1.08)
    assert d["source"].startswith("nasdaq_research")


@CORP
def test_splt_from_chart_events(client):
    d = data(client, "research/splt", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "splits")["rows"]
    assert len(rows) == 5
    last = rows[0]
    assert last["date"] == "2020-08-31" and (last["numerator"], last["denominator"]) == (4, 1) and last["ratio"] == "4:1"


@CORP
def test_cacs_merges_dividends_and_splits(client):
    d = data(client, "research/cacs", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "actions")["rows"]
    kinds = {r["kind"] for r in rows}
    assert kinds == {"DIVIDEND", "SPLIT"}
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)
    assert any(r["kind"] == "SPLIT" and r["date"] == "2020-08-31" and r["detail"] == "4:1" for r in rows)
    assert any(r["kind"] == "DIVIDEND" and r["date"] == "2026-08-10" for r in rows)
    assert any("EVTS" in n for n in d["data"]["notes"])


@CORP
def test_ipo_calendar_month(client):
    d = data(client, "research/ipo", month="2026-10")
    assert_table_payload(d)
    assert [s["id"] for s in d["data"]["sections"]] == ["upcoming", "priced", "filed", "withdrawn"]
    iam = next(r for r in section(d, "priced")["rows"] if r["symbol"] == "IAM")
    assert iam["company"] == "Iambic Therapeutics, Inc." and iam["price"] == 16.0
    assert iam["shares"] == 9375000 and iam["date"] == "2026-10-15" and iam["amount"] == 150000000
    assert client.get("/api/research/ipo", params={"month": "2026-9"}).status_code == 400
    assert client.get("/api/research/ipo", params={"month": "2019-01"}).status_code == 404  # not recorded


@CORP
def test_si_interest_and_daily_short_volume(client):
    finra = client.app.state.service.router.providers["finra"]
    finra.today = lambda: date(2026, 10, 18)
    d = data(client, "research/si", symbol="AAPL")
    assert_table_payload(d)
    si = section(d, "interest")["rows"]
    a, b = si[0], si[1]  # recorded Nasdaq/FINRA semi-monthly: 09/30/2026 then 09/15/2026
    assert a["date"] == "2026-09-30" and a["interest"] == 120763539 and a["avg_volume"] == 39858260
    assert a["days_to_cover"] == pytest.approx(3.029825)
    assert a["change"] == pytest.approx(120763539 / 128753092 - 1)
    assert b["date"] == "2026-09-15"
    vol = section(d, "volume")["rows"]
    assert len(vol) == 10 and vol[0]["date"] == "2026-10-16"  # recorded FINRA Reg SHO, newest first
    assert vol[0]["short_volume"] == pytest.approx(10797560.119118)
    assert vol[0]["total_volume"] == pytest.approx(20042726.828349)
    assert vol[0]["short_pct"] == pytest.approx(10797560.119118 / 20042726.828349)
    assert headline(d, "SHORT % OF FLOAT")["raw"] == pytest.approx(0.0083)  # Yahoo keystats, labelled with its source


@CORP
def test_si_without_finra_days_still_answers(client):
    finra = client.app.state.service.router.providers["finra"]
    finra.today = lambda: date(2031, 1, 1)  # no recorded file within the look-back window
    d = data(client, "research/si", symbol="AAPL")
    assert section(d, "volume")["rows"] == []
    assert any("FINRA" in n for n in d["data"]["notes"])


@CORP
def test_evts_decodes_8k_items(client):
    d = data(client, "research/evts", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "events")["rows"]
    assert all(r["form"].startswith("8-K") for r in rows)
    r0 = next(r for r in rows if r["date"] == "2026-07-30")  # recorded: items 2.02,9.01
    assert "RESULTS OF OPERATIONS" in r0["items"].upper() and "2.02" in r0["items"] and r0["url"]
    amend = next(r for r in rows if r["date"] == "2026-09-01")
    assert amend["form"] == "8-K/A" and "5.02" in amend["items"]


# --- VAL: DCF, WACC, RV ----------------------------------------------------------------------------------------

@VAL
def test_dcf_not_runnable_lists_every_missing_input(client):
    d = data(client, "valuation/dcf", symbol="AAPL")
    p = d["data"]
    assert p["runnable"] is False and p["result"] is None
    for name in ("equity_risk_premium", "terminal_growth", "exit_multiple", "growth", "minority_interest",
                 "capital_structure_basis", "discounting_convention", "terminal_value_method"):
        assert name in p["missing"], name
    found = {f["input"]: f for f in p["found"]}
    assert found["beta"]["value"] == pytest.approx(1.069) and found["beta"]["source"]  # Yahoo keystats
    assert found["risk_free_rate"]["source"]  # Treasury 10Y, with its date
    assert "NOT RUNNABLE" in p["status"]


@VAL
def test_dcf_runs_and_reconciles(client):
    q = {"symbol": "AAPL", "erp": 5.5, "g": 2.5, "exitx": 14, "growth": 5, "basis": "current", "conv": "mid",
         "tv": "perp", "kd": 3.5, "other": 0}
    d = data(client, "valuation/dcf", **q)
    p = d["data"]
    assert p["runnable"] is True, p["missing"]
    r = p["result"]
    assert r["enterprise_value"] == pytest.approx(r["pv_explicit"] + r["pv_terminal"], rel=1e-9)
    assert r["value_per_share"] == pytest.approx(r["equity_value"] / r["diluted_shares"], rel=1e-9)
    names = {a["name"] for a in p["assumptions"]}
    assert {"terminal_growth", "exit_multiple", "equity_risk_premium", "growth"} <= names
    assert all(a["basis"] for a in p["assumptions"])
    assert r["terminal_cross_check"]["implied_exit_multiple"] is not None


@VAL
def test_wacc_matches_the_textbook_formula(client):
    d = data(client, "valuation/wacc", symbol="AAPL", erp=5.5, basis="current", kd=3.5)
    r = d["data"]["result"]
    ke = r["risk_free_rate"] + r["beta"] * r["equity_risk_premium"]
    wacc = r["equity_weight"] * ke + r["debt_weight"] * r["pretax_cost_of_debt"] * (1 - r["tax_rate"])
    assert r["wacc"] == pytest.approx(wacc, rel=1e-9)
    assert r["equity_weight"] + r["debt_weight"] == pytest.approx(1.0)
    bad = client.get("/api/valuation/wacc", params={"symbol": "AAPL", "erp": 5.5, "basis": "sideways"})
    assert bad.status_code == 400


@VAL
def test_rv_runs_or_names_what_is_missing(client):
    d = data(client, "valuation/rv", symbol="AAPL", peers="MSFT")
    p = d["data"]
    assert isinstance(p["runnable"], bool)
    if not p["runnable"]:
        assert p["missing"]
    else:
        assert p["result"]["peer_count"] >= 1 and any("ROBUST" in w.upper() for w in p["warnings"])


# --- FUND: ETF, MEMB, MGR --------------------------------------------------------------------------------------

@FUND
def test_etf_profile_holdings_and_sectors(client):
    d = data(client, "research/etf", symbol="SPY")
    assert_table_payload(d)
    assert headline(d, "EXPENSE RATIO")["raw"] == pytest.approx(0.000945)
    assert headline(d, "NET ASSETS")["raw"] == pytest.approx(781188872106.76)
    assert headline(d, "HOLDINGS AS OF")["value"] == "2026-06-30"  # genInfo repPdDate; repPdEnd (09-30) is the fiscal year end
    rows = section(d, "holdings")["rows"]
    assert len(rows) == 60  # the recorded N-PORT is trimmed to 60 positions
    assert [r["weight"] for r in rows] == sorted((r["weight"] for r in rows), reverse=True)
    aflac = next(r for r in rows if r["cusip"] == "001055102")
    assert aflac["name"] == "Aflac Inc" and aflac["value"] == pytest.approx(650898953.25)
    assert aflac["weight"] == pytest.approx(0.083321585405 / 100)
    tech = next(r for r in section(d, "sectors")["rows"] if r["sector"] == "technology")
    assert tech["weight"] == pytest.approx(0.4045)
    assert any("NAME" in n.upper() for n in d["data"]["notes"])  # ticker matching is labelled approximate


@FUND
def test_etf_falls_back_to_yahoo_top_holdings(client):
    from openterm.providers.base import ProviderError

    async def down(*_a, **_k):
        raise ProviderError("unavailable", "N-PORT down")

    client.app.state.service.router.providers["sec_nport"].holdings = down
    d = data(client, "research/etf", symbol="SPY")
    rows = section(d, "holdings")["rows"]
    assert len(rows) == 10 and rows[0]["symbol"] == "NVDA" and rows[0]["weight"] == pytest.approx(0.0836162)
    assert d["fallback_from"] == ["sec_nport"]
    assert any("TOP 10" in n.upper() for n in d["data"]["notes"])


@FUND
def test_memb_uses_the_proxy_etf(client):
    d = data(client, "research/memb", index="SPX")
    assert_table_payload(d)
    assert headline(d, "PROXY ETF")["value"] == "SPY"
    assert len(section(d, "members")["rows"]) == 60
    assert client.get("/api/research/memb", params={"index": "NOPE"}).status_code == 400


@FUND
def test_mgr_13f_quarter_over_quarter_changes(client):
    d = data(client, "research/mgr", manager="BERKSHIRE")
    assert_table_payload(d)
    assert headline(d, "MANAGER")["value"].upper() == "BERKSHIRE HATHAWAY INC"
    assert headline(d, "PERIOD")["value"] == "2026-06-30"

    def positions(acc: str) -> dict[str, int]:
        xml = fixture_body(f"sec_13f_{acc}")["text"]
        out: dict[str, int] = {}
        for blk in re.findall(r"<infoTable>.*?</infoTable>", xml, flags=re.DOTALL):
            cusip = re.search(r"<cusip>(.*?)</cusip>", blk).group(1)
            out[cusip] = out.get(cusip, 0) + int(re.search(r"<sshPrnamt>(\d+)</sshPrnamt>", blk).group(1))
        return out

    now, before = positions("0001193125-26-352200"), positions("0001193125-26-226661")
    want = {"NEW": len(now.keys() - before.keys()), "EXITED": len(before.keys() - now.keys()),
            "ADDED": sum(1 for c in now.keys() & before.keys() if now[c] > before[c]),
            "TRIMMED": sum(1 for c in now.keys() & before.keys() if now[c] < before[c]),
            "UNCHANGED": sum(1 for c in now.keys() & before.keys() if now[c] == before[c])}
    got: dict[str, int] = {}
    for r in section(d, "changes")["rows"]:
        got[r["status"]] = got.get(r["status"], 0) + 1
    assert got == {k: v for k, v in want.items() if v}
    assert client.get("/api/research/mgr", params={"manager": "NOSUCHFUND"}).status_code == 404


# --- KEYED: CN, key-required sections --------------------------------------------------------------------------

@KEYED
def test_cn_keyless_news_with_labelled_score_and_key_hints(client):
    d = data(client, "research/cn", symbol="AAPL")
    assert_table_payload(d)
    rows = section(d, "news")["rows"]
    assert rows and all(r["label"] in ("POS", "NEG", "NEU") for r in rows)
    assert any("KEYWORD SCORE, NOT A MODEL" in n for n in d["data"]["notes"])
    needs = {k["key"] for k in d["data"]["key_required"]}
    assert {"FINNHUB_API_KEY", "ALPACA_KEY_ID"} <= needs


@KEYED
def test_cn_gains_finnhub_headlines_once_keyed(client):
    r = client.put("/api/keys/finnhub", json={"fields": {"FINNHUB_API_KEY": "k" * 24}})
    assert r.status_code == 200
    d = data(client, "research/cn", symbol="AAPL")
    sources = {row["source"] for row in section(d, "news")["rows"]}
    assert "finnhub" in sources
    assert "FINNHUB_API_KEY" not in {k["key"] for k in d["data"]["key_required"]}
