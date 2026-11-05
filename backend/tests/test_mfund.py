"""MF: Indian mutual fund NAV from MFapi.in. Parsers and return maths on REAL recordings (2026-11-05, history of fund 122639 trimmed to 30 points); no network."""

import json
from datetime import date
from pathlib import Path

import pytest

from openterm.world import mfund

FIX = Path(__file__).parent / "fixtures"


def rec(name: str):
    """The body of a recorded MFapi answer."""
    return json.loads((FIX / f"mfapi_real_{name}.json").read_text(encoding="utf-8"))["body"]


def series(*pairs: tuple[str, float]) -> tuple[list[date], list[float]]:
    """Ascending (dates, navs) from ("2026-11-03", 90.7) pairs."""
    return [date.fromisoformat(d) for d, _ in pairs], [n for _, n in pairs]


def row(table: list[dict], period: str) -> dict:
    return next(r for r in table if r["period"] == period)


# --- what the user typed ------------------------------------------------------------------------------------------------
def test_query_is_a_code_or_words():
    assert mfund.norm_query("122639") == ("code", "122639")
    assert mfund.norm_query(" 0122639 ") == ("code", "122639")  # leading zeros dropped: the cache key and the URL stay canonical
    assert mfund.norm_query("  Parag   Parikh ") == ("search", "Parag Parikh")


@pytest.mark.parametrize("text", ["", "  ", "ab", "123", "12345678", "x" * 81])
def test_unusable_queries_are_bad_requests(text):
    with pytest.raises(mfund.MfundError) as e:
        mfund.norm_query(text)
    assert e.value.kind == "bad_request"


# --- search -----------------------------------------------------------------------------------------------------------
def test_search_parses_the_real_answer():
    items = mfund.parse_search(rec("search_parag"))
    assert len(items) == 15
    assert items[0] == {"code": 153965, "name": "Parag Parikh Flexi Cap Fund - Regular Plan - Monthly IDCW Payout"}
    assert {"code": 122639, "name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"} in items
    assert mfund.parse_search(rec("search_none")) == []  # no match is a valid, empty answer


def test_search_payload_caps_rows_but_reports_the_true_total():
    items = [{"code": i, "name": f"Fund {i}"} for i in range(1000, 1000 + mfund.SEARCH_LIMIT + 50)]
    p = mfund.search_payload("fund", items)
    assert p["mode"] == "SEARCH" and p["total"] == len(items) and p["shown"] == mfund.SEARCH_LIMIT == len(p["items"])


@pytest.mark.parametrize("body", [{"a": 1}, [{"schemeCode": "x", "schemeName": "n"}], [{"schemeName": "n"}], [None]])
def test_search_with_a_changed_shape_raises_instead_of_dropping_rows(body):
    with pytest.raises(mfund.MfundError):
        mfund.parse_search(body)


# --- one fund: parsing -------------------------------------------------------------------------------------------------
def test_fund_parses_the_real_answer_oldest_first():
    f = mfund.parse_fund(rec("fund_122639"))
    assert f["code"] == 122639 and f["name"] == "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    assert f["fund_house"] == "PPFAS Mutual Fund" and f["category"] == "Equity Scheme - Flexi Cap Fund"
    assert f["isin_growth"] == "INF879O01027" and f["isin_div"] is None
    assert len(f["dates"]) == len(f["navs"]) == 30
    assert f["dates"] == sorted(f["dates"]) and f["dates"][-1] == date(2026, 11, 3)  # the service sends newest first; we sort
    assert f["navs"][-1] == pytest.approx(90.7043)  # nav arrives as text and becomes a float


def test_unknown_scheme_is_none_not_an_error():
    assert mfund.parse_fund(rec("fund_unknown")) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["data"][0].update(nav="n.a."),
        lambda b: b["data"][0].update(nav="0.00000"),
        lambda b: b["data"][0].update(date="2026-11-03"),  # ISO instead of DD-MM-YYYY: a changed format must be loud
        lambda b: b["data"].append(dict(b["data"][0])),  # two NAVs for one day
        lambda b: b.pop("data"),
    ],
)
def test_bad_fund_data_raises(mutate):
    body = rec("fund_122639")
    mutate(body)
    with pytest.raises(mfund.MfundError) as e:
        mfund.parse_fund(body)
    assert e.value.kind == "unavailable"


# --- return maths ------------------------------------------------------------------------------------------------------
def test_minus_months_clamps_to_the_month_length():
    assert mfund.minus_months(date(2028, 5, 31), 3) == date(2028, 2, 29)  # leap year
    assert mfund.minus_months(date(2027, 5, 31), 3) == date(2027, 2, 28)
    assert mfund.minus_months(date(2026, 1, 15), 3) == date(2025, 10, 15)  # across a year end
    assert mfund.minus_months(date(2026, 11, 3), 60) == date(2021, 11, 3)


def test_real_recording_short_periods():
    f = mfund.parse_fund(rec("fund_122639"))
    table = mfund.returns(f["dates"], f["navs"])
    assert [r["period"] for r in table] == ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]
    one_d, one_w = row(table, "1D"), row(table, "1W")
    # 1D: latest 2026-11-03 (90.7043) against the NAV of Monday 2026-11-02 (89.7397)
    assert one_d["base_date"] == "2026-11-02" and one_d["kind"] == mfund.ABSOLUTE
    assert one_d["pct"] == pytest.approx((90.7043 / 89.7397 - 1) * 100, rel=1e-9)
    # 1W: target 2026-10-27, a Tuesday with its own NAV (89.2762)
    assert one_w["base_date"] == "2026-10-27" and one_w["pct"] == pytest.approx((90.7043 / 89.2762 - 1) * 100, rel=1e-9)


def test_history_shorter_than_the_period_gives_a_dash_not_a_number():
    f = mfund.parse_fund(rec("fund_122639"))  # 30 points only cover about six weeks
    table = mfund.returns(f["dates"], f["navs"])
    for p in ("3M", "6M", "1Y", "3Y", "5Y"):
        r = row(table, p)
        assert r["pct"] is None and r["base_date"] is None and r["why"].startswith("HISTORY STARTS 2026-"), p


def test_base_is_the_nearest_earlier_nav_when_the_target_is_a_weekend():
    # target for 1W from Monday 2026-11-02 is Monday 2026-10-26 (no NAV that day), so the Friday before is the base
    dates, navs = series(("2026-10-23", 100.0), ("2026-10-27", 101.0), ("2026-11-02", 102.0))
    r = row(mfund.returns(dates, navs), "1W")
    assert r["base_date"] == "2026-10-23" and r["pct"] == pytest.approx(2.0)


def test_one_year_is_absolute_and_three_year_is_cagr_with_known_values():
    # latest 2028-02-28 at 133.1; one year back (2027-02-28) 121.0 and three years back (2025-02-28, 1,095 days: no 29 February in between) 100.0.
    dates, navs = series(("2025-02-28", 100.0), ("2027-02-28", 121.0), ("2028-02-28", 133.1))
    table = mfund.returns(dates, navs)
    one_y, three_y = row(table, "1Y"), row(table, "3Y")
    assert one_y["kind"] == "ABSOLUTE RETURN" and one_y["pct"] == pytest.approx(10.0)  # 133.1 / 121 - 1
    assert three_y["kind"] == "CAGR" and three_y["base_date"] == "2025-02-28"
    assert three_y["pct"] == pytest.approx(10.0)  # 1.1 ** 3 = 1.331, annualised over exactly 3 x 365 days
    assert row(table, "5Y")["pct"] is None


def test_cagr_uses_the_days_actually_elapsed_to_the_base_date():
    # 3Y target 2025-02-28 has no NAV; the nearest earlier one is 2025-02-24 (4 days earlier), so the exponent is 365/1099, not 365/1095.
    dates, navs = series(("2025-02-24", 100.0), ("2028-02-28", 133.1))
    r = row(mfund.returns(dates, navs), "3Y")
    assert r["base_date"] == "2025-02-24"
    assert r["pct"] == pytest.approx(((133.1 / 100.0) ** (365 / 1099) - 1) * 100)


def test_a_hole_in_the_history_is_a_dash():
    # the only earlier NAV is 20 days before the 1W target: farther than MAX_GAP_DAYS, so no base is used
    dates, navs = series(("2026-10-06", 100.0), ("2026-11-02", 102.0))
    r = row(mfund.returns(dates, navs), "1W")
    assert r["pct"] is None and "NO NAV WITHIN" in r["why"]


def test_falling_nav_gives_a_negative_return():
    dates, navs = series(("2026-10-31", 50.0), ("2026-11-02", 45.0))
    assert row(mfund.returns(dates, navs), "1D")["pct"] == pytest.approx(-10.0)


# --- payload -----------------------------------------------------------------------------------------------------------
def test_fund_payload_for_the_real_recording():
    p = mfund.fund_payload(mfund.parse_fund(rec("fund_122639")))
    assert p["mode"] == "FUND" and p["points"] == 30 and p["first_date"] < p["latest"]["date"] == "2026-11-03"
    assert p["latest"]["nav"] == pytest.approx(90.7043)
    assert len(p["t"]) == len(p["v"]) == 30 and p["t"] == sorted(p["t"])
    assert p["t"][-1] == 1793664000  # 2026-11-03 00:00 UTC
    assert p["payout_plan"] is False and "IDCW" not in p["note"]
    assert "NOT A FORECAST" in p["note"] and "CAGR" in p["note"]


def test_payout_plans_carry_the_idcw_warning():
    body = rec("fund_122639")
    body["meta"]["scheme_name"] = "Some Fund - Direct Plan - Monthly IDCW Payout"
    p = mfund.fund_payload(mfund.parse_fund(body))
    assert p["payout_plan"] is True and "LEAVE THE PAYOUTS OUT" in p["note"]


# --- route (fixture mode: the recorded service) ---------------------------------------------------------------------------
def test_route_search_by_words(client):
    r = client.get("/api/world/mf", params={"q": "parag parikh"}).json()
    d = r["data"]
    assert d["mode"] == "SEARCH" and d["total"] == 15 and d["items"][0]["code"] == 153965
    assert r["source"] == "MFAPI.IN" and "NOT AN OFFICIAL AMFI API" in d["source_note"]
    assert client.get("/api/world/mf", params={"q": "parikh flexi direct"}).json()["data"]["total"] == 2  # all words, any order


def test_route_search_with_no_match_is_an_empty_list_not_an_error(client):
    r = client.get("/api/world/mf", params={"q": "zzzzqqq"})
    assert r.status_code == 200 and r.json()["data"]["items"] == []


def test_route_fund_by_scheme_code(client):
    r = client.get("/api/world/mf", params={"q": "122639"}).json()
    d = r["data"]
    assert d["mode"] == "FUND" and d["name"].startswith("Parag Parikh Flexi Cap") and d["latest"]["date"] == "2026-11-03"
    assert row(d["returns"], "1D")["pct"] == pytest.approx((90.7043 / 89.7397 - 1) * 100)
    assert r["source"] == "MFAPI.IN" and r["stale"] is False and "MAY LAG A DAY" in d["source_note"]


def test_route_unknown_scheme_code_is_a_not_found_with_advice(client):
    r = client.get("/api/world/mf", params={"q": "9999999"})
    assert r.status_code == 404 and "9999999" in r.json()["error"] and "MF <WORDS>" in r.json()["error"]


def test_route_bad_words_are_a_bad_request(client):
    r = client.get("/api/world/mf", params={"q": "ab"})
    assert r.status_code == 400 and "FUND NAME OR SCHEME CODE" in r.json()["error"]
    assert client.get("/api/world/mf", params={"q": "123"}).status_code == 400
