"""Phase 19 step 5: NYSE / Nasdaq holidays by rule (checked against the published lists), early closes, and the Nager.Date parser."""

import json
from datetime import date
from pathlib import Path

import pytest

from openterm.world import nyse_holidays as nh

FIX = Path(__file__).parent / "fixtures"

# The published NYSE full-day closures (nyse.com "Holidays & Trading Hours"), 2024-2027, plus the 2025 special closure.
PUBLISHED = {
    2024: ["2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25"],
    2025: ["2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25"],
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"],
    2027: ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"],
}
PUBLISHED_EARLY = {
    2024: ["2024-07-03", "2024-11-29", "2024-12-24"],
    2025: ["2025-07-03", "2025-11-28", "2025-12-24"],
    2026: ["2026-11-27", "2026-12-24"],
    2027: ["2027-11-26"],
}


@pytest.mark.parametrize("year", sorted(PUBLISHED))
def test_full_day_closures_match_the_published_list(year):
    assert sorted(d.isoformat() for d in nh.holidays(year)) == PUBLISHED[year]


@pytest.mark.parametrize("year", sorted(PUBLISHED_EARLY))
def test_early_closes_match_the_published_list(year):
    assert sorted(d.isoformat() for d in nh.early_closes(year)) == PUBLISHED_EARLY[year]


def test_good_friday_follows_easter():
    # Easter Sunday: 2024-03-31, 2025-04-20, 2026-04-05, 2027-03-28, 2038-04-25, 2000-04-23
    for y, easter in ((2024, "03-31"), (2025, "04-20"), (2026, "04-05"), (2027, "03-28"), (2038, "04-25"), (2000, "04-23")):
        assert nh.easter(y) == date.fromisoformat(f"{y}-{easter}")


def test_saturday_holiday_is_observed_friday_but_a_saturday_new_year_is_not():
    assert date(2026, 7, 3) in nh.holidays(2026)  # July 4 is a Saturday
    assert date(2027, 6, 18) in nh.holidays(2027)  # Juneteenth is a Saturday
    assert date(2027, 12, 31) not in nh.holidays(2027)  # New Year 2028 is a Saturday: the market is open on Friday
    assert date(2022, 12, 31) not in nh.holidays(2022) and date(2021, 12, 31) not in nh.holidays(2021)


def test_sunday_holiday_is_observed_monday():
    assert date(2027, 7, 5) in nh.holidays(2027)
    assert date(2022, 12, 26) in nh.holidays(2022)  # Christmas Sunday


def test_juneteenth_only_from_2022():
    assert date(2021, 6, 18) not in nh.holidays(2021) and date(2021, 6, 19) not in nh.holidays(2021)
    assert date(2022, 6, 20) in nh.holidays(2022)


def test_names_and_status_calls():
    assert nh.holidays(2026)[date(2026, 4, 3)] == "Good Friday"
    assert nh.holidays(2025)[date(2025, 1, 9)].startswith("National Day of Mourning")
    assert nh.status(date(2026, 11, 26)) == ("HOLIDAY", "Thanksgiving Day")
    assert nh.status(date(2026, 11, 27)) == ("EARLY", "Day after Thanksgiving, 1 pm close")
    assert nh.status(date(2026, 10, 14)) == ("OPEN", None)
    assert nh.status(date(2026, 10, 17)) == ("WEEKEND", None)


def test_year_outside_the_supported_range_is_refused_not_guessed():
    with pytest.raises(ValueError):
        nh.holidays(1990)
    with pytest.raises(ValueError):
        nh.holidays(2100)


# --- Nager.Date ---------------------------------------------------------------------------------------------------------
def test_nager_parser_keeps_national_holidays_and_marks_regional_ones():
    from openterm.world import holidays as wh

    body = json.loads((FIX / "nager_gb_2026.json").read_text(encoding="utf-8"))["body"]
    out = wh.parse_nager(body)
    by = {r["date"]: r for r in out}
    assert by["2026-04-03"]["name"] == "Good Friday" and by["2026-04-03"]["national"] is True
    assert by["2026-01-02"]["national"] is False  # Scotland only
    assert [r["date"] for r in out] == sorted(r["date"] for r in out)
    assert wh.national_dates(out) >= {"2026-04-03", "2026-12-25"}
    assert "2026-01-02" not in wh.national_dates(out)


def test_nager_non_public_types_are_dropped_and_empty_is_empty():
    from openterm.world import holidays as wh

    rows = [{"date": "2026-05-04", "name": "Bank", "global": True, "types": ["Bank"]}, {"date": "2026-05-25", "name": "Spring", "global": True, "types": ["Public"]}]
    assert [r["date"] for r in wh.parse_nager(rows)] == ["2026-05-25"]
    assert wh.parse_nager([]) == []
    assert wh.parse_nager(None) == []
