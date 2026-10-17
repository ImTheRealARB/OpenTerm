"""Phase 13 step 3: parser edge cases and fallbacks for DVD, SPLT, CACS, IPO, SI (pure functions plus provider outages)."""

from datetime import date

import pytest

from openterm.providers.base import ProviderError
from openterm.research import corp_parse as cp
from openterm.research.table import iso_date, number, us_date


def test_number_and_date_helpers_never_guess():
    assert number("$1,234.50") == 1234.5 and number("9,375,000") == 9375000 and number("12.5%") == 12.5
    assert number("N/A") is None and number("") is None and number(None) is None
    assert us_date("8/2/2026") == "2026-08-02" and us_date("08/10/2026") == "2026-08-10"
    assert us_date("N/A") is None and us_date("") is None and us_date("2026-08-10") is None
    assert iso_date(0) is None and iso_date(None) is None and iso_date(1791830866) == "2026-10-12"


def test_parse_short_volume_skips_header_and_bad_lines():
    text = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20261016|AAPL|10.5|1|20|B,Q\nbroken\n20261016|X|a|b|c|Q\n"
    assert cp.parse_short_volume(text) == {"AAPL": (10.5, 1.0, 20.0)}


def test_valid_month():
    assert cp.valid_month("2026-10") == "2026-10"
    assert cp.valid_month(None, date(2026, 3, 9)) == "2026-03"
    for bad in ("2026-9", "2026-13", "26-10", "2026/10", "abcd-ef", "1800-01"):
        with pytest.raises(ValueError):
            cp.valid_month(bad)


def test_nasdaq_dividends_drop_rows_without_an_ex_date_and_keep_na_amounts_empty():
    body = {"data": {"annualizedDividend": "1.08", "yield": "0.32%", "exDividendDate": "08/10/2026", "dividendPaymentDate": "N/A",
                     "dividends": {"rows": [
                         {"exOrEffDate": "N/A", "amount": "$0.27", "type": "Cash"},
                         {"exOrEffDate": "8/10/2026", "amount": "N/A", "type": "Cash", "declarationDate": "N/A"}]}}}
    raw = cp.nasdaq_dividends(body, "x")
    assert len(raw["rows"]) == 1 and raw["rows"][0]["amount"] is None and raw["rows"][0]["declared"] is None
    assert raw["yield"] == pytest.approx(0.0032) and raw["pay_date"] is None
    with pytest.raises(ProviderError) as e:
        cp.nasdaq_dividends({"data": None}, "x")
    assert e.value.kind == "not_found"


def test_yahoo_dividends_trailing_twelve_months_is_computed_from_the_rows_shown():
    rows = [{"ex_date": "2026-08-10", "amount": 0.27, "type": "Cash", "declared": None, "record": None, "pay": None},
            {"ex_date": "2026-05-11", "amount": 0.27, "type": "Cash", "declared": None, "record": None, "pay": None},
            {"ex_date": "2025-08-11", "amount": 0.26, "type": "Cash", "declared": None, "record": None, "pay": None},
            {"ex_date": "2025-08-09", "amount": 0.25, "type": "Cash", "declared": None, "record": None, "pay": None}]
    p = cp.dvd_payload("AAPL", {"rows": rows, "annual": None, "yield": None, "ex_date": None, "pay_date": None, "source": "yahoo_research"})
    last12 = next(h for h in p["headline"] if h["label"].startswith("PAID IN THE 12 MONTHS"))
    assert last12["raw"] == pytest.approx(0.27 + 0.27 + 0.26)  # 2025-08-09 is more than 365 days before 2026-08-10
    assert p["notes"] and "NASDAQ" in p["notes"][0]  # the missing dates are admitted, not hidden


def test_cacs_with_one_source_down_says_so_and_still_lists_the_other():
    splt = {"rows": [{"date": "2020-08-31", "ratio": "4:1", "numerator": 4, "denominator": 1}], "source": "yahoo_research"}
    p = cp.cacs_payload("AAPL", None, splt, ["DIVIDENDS"], "yahoo_research")
    assert [r["kind"] for r in p["sections"][0]["rows"]] == ["SPLIT"]
    assert any("DIVIDENDS UNAVAILABLE" in n for n in p["notes"])


def test_si_change_is_against_the_next_older_row_and_missing_days_do_not_break_totals():
    interest = {"rows": [{"date": "2026-09-30", "interest": 90.0, "avg_volume": None, "days_to_cover": None},
                         {"date": "2026-09-15", "interest": 100.0, "avg_volume": None, "days_to_cover": None},
                         {"date": "2026-08-31", "interest": None, "avg_volume": None, "days_to_cover": None}], "source": "s"}
    p = cp.si_payload("X", interest, None, "FINRA DAILY SHORT VOLUME UNAVAILABLE (finra: down)", None)
    rows = p["sections"][0]["rows"]
    assert rows[0]["change"] == pytest.approx(-0.1) and rows[1]["change"] is None and rows[2]["change"] is None
    assert p["sections"][1]["rows"] == [] and any("YAHOO KEY STATISTICS UNAVAILABLE" in n for n in p["notes"])
    assert any("FINRA" in n for n in p["notes"])


def test_yahoo_short_interest_fallback_has_two_rows_and_no_invented_volume():
    summary = {"defaultKeyStatistics": {"sharesShort": {"raw": 120763539}, "dateShortInterest": {"raw": 1790726400},
                                        "sharesShortPriorMonth": {"raw": 139749097}, "sharesShortPreviousMonthDate": {"raw": 1788134400},
                                        "shortRatio": {"raw": 2.82}}}
    raw = cp.yahoo_short_interest(summary, "yahoo_research")
    assert [r["date"] for r in raw["rows"]] == ["2026-09-30", "2026-08-31"]
    assert raw["rows"][0]["avg_volume"] is None and raw["rows"][0]["days_to_cover"] == 2.82
    with pytest.raises(ProviderError):
        cp.yahoo_short_interest({"defaultKeyStatistics": {}}, "y")


def test_decode_items_keeps_unknown_item_numbers():
    assert cp.decode_items("2.02,9.01") == "2.02 RESULTS OF OPERATIONS; 9.01 EXHIBITS"
    assert cp.decode_items("6.01") == "6.01" and cp.decode_items(None) == ""


def test_dvd_falls_back_to_yahoo_when_nasdaq_is_down(client):
    async def down(*_a, **_k):
        raise ProviderError("unavailable", "nasdaq down")

    client.app.state.service.router.providers["nasdaq_research"].dividends = down
    r = client.get("/api/research/dvd", params={"symbol": "AAPL"})
    assert r.status_code == 200
    d = r.json()
    assert d["fallback_from"] == ["nasdaq_research"] and d["source"].startswith("yahoo_research")
    rows = d["data"]["sections"][0]["rows"]
    assert rows[0]["amount"] == pytest.approx(0.27) and rows[0]["declared"] is None  # dates only Nasdaq has: left empty
    assert any("NASDAQ" in n for n in d["data"]["notes"])


def test_si_falls_back_to_yahoo_key_statistics(client):
    async def down(*_a, **_k):
        raise ProviderError("unavailable", "nasdaq down")

    client.app.state.service.router.providers["nasdaq_research"].short_interest = down
    client.app.state.service.router.providers["finra"].today = lambda: date(2026, 10, 18)
    d = client.get("/api/research/si", params={"symbol": "AAPL"}).json()
    assert d["fallback_from"] == ["nasdaq_research"]
    rows = d["data"]["sections"][0]["rows"]
    assert [r["date"] for r in rows] == ["2026-09-30", "2026-08-31"] and rows[0]["interest"] == 120763539


def test_research_unknown_function_and_missing_symbol(client):
    assert client.get("/api/research/nope", params={"symbol": "AAPL"}).json()["kind"] == "not_found"
    r = client.get("/api/research/dvd")
    assert r.status_code == 400 and r.json()["kind"] == "bad_request"
