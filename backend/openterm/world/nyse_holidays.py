"""NYSE / Nasdaq full-day closures and 1 pm early closes by rule (pure; no network).

Rules (NYSE Rule 7.2 and the published holiday list): a holiday on a Saturday is observed on the Friday before, on a Sunday on the Monday
after, EXCEPT New Year's Day on a Saturday, which is not observed (the market is open that Friday). Good Friday is two days before Easter.
Juneteenth is a holiday from 2022. Early closes: the day after Thanksgiving; Christmas Eve; July 3, each only when it is a trading weekday
(and for July 3 only when July 4 is itself a weekday). Special one-off closures cannot be derived: they live in SPECIAL below with their reason.
Checked in tests against the published lists for 2024-2027.
"""

from __future__ import annotations

from datetime import date, timedelta

FIRST_YEAR = 2000
LAST_YEAR = 2040

# One-off full-day closures that follow no rule.
SPECIAL = {
    date(2001, 9, 11): "September 11 attacks", date(2001, 9, 12): "September 11 attacks", date(2001, 9, 13): "September 11 attacks",
    date(2001, 9, 14): "September 11 attacks", date(2004, 6, 11): "National Day of Mourning for Ronald Reagan",
    date(2007, 1, 2): "National Day of Mourning for Gerald Ford", date(2012, 10, 29): "Hurricane Sandy", date(2012, 10, 30): "Hurricane Sandy",
    date(2018, 12, 5): "National Day of Mourning for George H.W. Bush", date(2025, 1, 9): "National Day of Mourning for Jimmy Carter",
}


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous / Meeus algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _check(year: int) -> None:
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise ValueError(f"YEAR {year} OUTSIDE {FIRST_YEAR}-{LAST_YEAR}")


def holidays(year: int) -> dict[date, str]:
    """Full-day closures falling in `year` (an observed date can move across the year edge: Jan 1 of next year is never observed on Dec 31)."""
    _check(year)
    out: dict[date, str] = {}

    def add(d: date | None, name: str) -> None:
        if d is not None and d.year == year:
            out[d] = name

    add(_observed(date(year, 1, 1), saturday_to_friday=False), "New Year's Day")
    add(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")
    add(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")
    add(easter(year) - timedelta(days=2), "Good Friday")
    add(_last_weekday(year, 5, 0), "Memorial Day")
    if year >= 2022:
        add(_observed(date(year, 6, 19)), "Juneteenth National Independence Day")
    add(_observed(date(year, 7, 4)), "Independence Day")
    add(_nth_weekday(year, 9, 0, 1), "Labor Day")
    add(_nth_weekday(year, 11, 3, 4), "Thanksgiving Day")
    add(_observed(date(year, 12, 25)), "Christmas Day")
    for d, why in SPECIAL.items():
        if d.year == year:
            out[d] = why
    return dict(sorted(out.items()))


def early_closes(year: int) -> dict[date, str]:
    """1 pm closes: day after Thanksgiving, Christmas Eve, July 3 (each only on a trading weekday)."""
    _check(year)
    closed = holidays(year)
    out: dict[date, str] = {}
    out[_nth_weekday(year, 11, 3, 4) + timedelta(days=1)] = "Day after Thanksgiving, 1 pm close"
    eve = date(year, 12, 24)
    if eve.weekday() < 5 and eve not in closed:
        out[eve] = "Christmas Eve, 1 pm close"
    jul3, jul4 = date(year, 7, 3), date(year, 7, 4)
    if jul3.weekday() < 5 and jul4.weekday() < 5 and jul3 not in closed:
        out[jul3] = "Day before Independence Day, 1 pm close"
    return dict(sorted((d, n) for d, n in out.items() if d not in closed))


def status(d: date) -> tuple[str, str | None]:
    """(OPEN | EARLY | HOLIDAY | WEEKEND, name)."""
    if d.weekday() >= 5:
        return "WEEKEND", None
    h = holidays(d.year)
    if d in h:
        return "HOLIDAY", h[d]
    e = early_closes(d.year)
    if d in e:
        return "EARLY", e[d]
    return "OPEN", None
