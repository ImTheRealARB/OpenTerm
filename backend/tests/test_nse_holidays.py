"""NSE (India) holidays by rule: fixed-date national holidays + Good Friday only. Festival holidays (Diwali, Holi, Eid...) follow lunar calendars and are NOT computed."""

from datetime import date

import pytest

from openterm.world import nse_holidays as nse


def test_fixed_date_holidays_on_weekdays_are_closed():
    h = nse.holidays(2026)
    assert h[date(2026, 1, 26)] == "Republic Day"  # Monday
    assert h[date(2026, 10, 2)] == "Gandhi Jayanti"  # Friday
    assert h[date(2026, 12, 25)] == "Christmas"  # Friday
    assert h[date(2026, 5, 1)] == "Maharashtra Day"  # Friday
    assert h[date(2026, 4, 14)] == "Dr. Baba Saheb Ambedkar Jayanti"  # Tuesday
    assert h[date(2026, 4, 3)] == "Good Friday"


def test_weekend_fixed_dates_are_not_shifted():
    # 2026-08-15 is a Saturday; NSE does not move a weekend holiday to a weekday.
    assert date(2026, 8, 15) not in nse.holidays(2026)
    assert date(2026, 8, 14) not in nse.holidays(2026) and date(2026, 8, 17) not in nse.holidays(2026)
    # 2027-05-01 Saturday, 2027-10-02 Saturday, 2027-12-25 Saturday, 2028-01-26 is a Wednesday.
    h27 = nse.holidays(2027)
    assert date(2027, 5, 1) not in h27 and date(2027, 10, 2) not in h27 and date(2027, 12, 25) not in h27
    assert date(2027, 8, 15) not in h27  # Sunday
    assert date(2027, 1, 26) in h27  # Tuesday
    assert date(2028, 1, 26) in nse.holidays(2028)


def test_good_friday_follows_easter():
    assert date(2027, 3, 26) in nse.holidays(2027)
    assert date(2025, 4, 18) in nse.holidays(2025)


def test_result_is_sorted_and_in_year():
    ds = list(nse.holidays(2025))
    assert ds == sorted(ds) and all(d.year == 2025 for d in ds)


def test_year_outside_range_is_refused():
    with pytest.raises(ValueError):
        nse.holidays(1990)


def test_payload_is_honest_about_coverage():
    p = nse.payload(2026)
    assert p["mkt"] == "IN" and p["basis"] == "fixed" and p["early"] == []
    assert "FESTIVAL" in p["label"].upper() and "NOT INCLUDED" in p["label"].upper()
    assert all(h["national"] is True for h in p["holidays"])
    assert p["source"] == "nse_rules"


def test_route_india_serves_fixed_rules_not_404(client):
    r = client.get("/api/world/holidays", params={"mkt": "IN", "year": 2026})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["basis"] == "fixed" and "2026-01-26" in [h["date"] for h in d["holidays"]]
    assert "NOT INCLUDED" in d["label"].upper()
