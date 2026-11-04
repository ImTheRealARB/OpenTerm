"""NSE (India) full-day closures by RULE (pure; no network, nothing scraped).

What is computed here, and only this:
  * fixed-date national holidays: Republic Day (Jan 26), Dr. Ambedkar Jayanti (Apr 14), Maharashtra Day (May 1),
    Independence Day (Aug 15), Gandhi Jayanti (Oct 2), Christmas (Dec 25);
  * Good Friday (two days before Easter, same Gregorian rule as NYSE).
NSE does NOT move a holiday that falls on a weekend, so those years simply have no closure on a weekday.

What is NOT here: the festival holidays (Holi, Ram Navami, Eid, Diwali, Dussehra, Guru Nanak Jayanti...). They follow
lunar calendars and NSE publishes the list each year, so no simple rule gives them. On those days the market light
will wrongly say OPEN; the label returned to the UI says so.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .nyse_holidays import FIRST_YEAR, LAST_YEAR, easter

LABEL = "NSE FIXED-DATE HOLIDAYS + GOOD FRIDAY BY RULE (FESTIVAL HOLIDAYS NOT INCLUDED)"

# (month, day, name)
FIXED = (
    (1, 26, "Republic Day"),
    (4, 14, "Dr. Baba Saheb Ambedkar Jayanti"),
    (5, 1, "Maharashtra Day"),
    (8, 15, "Independence Day"),
    (10, 2, "Gandhi Jayanti"),
    (12, 25, "Christmas"),
)


def holidays(year: int) -> dict[date, str]:
    """Weekday closures in `year` from the rules above, sorted by date."""
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise ValueError(f"YEAR {year} OUTSIDE {FIRST_YEAR}-{LAST_YEAR}")
    out: dict[date, str] = {date(year, m, d): name for m, d, name in FIXED}
    out[date.fromordinal(easter(year).toordinal() - 2)] = "Good Friday"
    # weekday() is 0-4 for Monday-Friday: a Saturday or Sunday date is dropped, not shifted
    return dict(sorted((d, n) for d, n in out.items() if d.weekday() < 5))


def payload(year: int) -> dict[str, Any]:
    """Same shape as `holidays.nyse_payload`; `basis: "fixed"` tells the UI the list is partial."""
    return {
        "mkt": "IN", "year": year, "basis": "fixed", "label": LABEL,
        "holidays": [{"date": d.isoformat(), "name": n, "national": True} for d, n in holidays(year).items()],
        "early": [], "source": "nse_rules",
    }
