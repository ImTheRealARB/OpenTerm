"""Central bank rate-decision dates (CENB): a DATED TABLE, not a feed.

Each bank's own schedule page is read by a person; the dates below were transcribed on AS_OF from the URL in `BANKS`. A date listed here is the DECISION
day (the last day of a multi-day meeting). A bank/year that is missing is shown as `CALENDAR NOT LOADED FOR <year>`, never estimated. The Fed's dates are
NOT in this table: they come live from federalreserve.gov (the Phase 14 FOMC provider) and only fall back to "not loaded" when that page is down.
Update this file when a bank publishes its next year; `AS_OF` must move with it.
"""

from __future__ import annotations

from datetime import date

AS_OF = "2026-10-18"

BANKS: dict[str, dict] = {
    "FED": {"name": "Federal Reserve (FOMC)", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "live": True, "dates": {}},
    "ECB": {"name": "European Central Bank", "url": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
            "dates": {2026: ["2026-10-29", "2026-12-17"],  # the page lists only the remaining 2026 meetings
                      2027: ["2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10", "2027-07-22", "2027-09-09", "2027-10-28", "2027-12-16"]}},
    "BOE": {"name": "Bank of England (MPC)", "url": "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
            "dates": {2026: ["2026-02-05", "2026-03-19", "2026-04-30", "2026-06-18", "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17"],
                      2027: ["2027-02-04", "2027-03-18", "2027-04-29", "2027-06-17", "2027-07-29", "2027-09-16", "2027-11-04", "2027-12-16"]}},
    "BOJ": {"name": "Bank of Japan", "url": "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
            "dates": {2026: ["2026-01-23", "2026-03-19", "2026-04-28", "2026-06-16", "2026-07-31", "2026-09-18", "2026-10-30", "2026-12-18"],
                      2027: ["2027-01-22", "2027-03-18", "2027-04-28", "2027-06-11", "2027-07-22", "2027-09-22", "2027-10-29", "2027-12-17"]}},
    "BOC": {"name": "Bank of Canada", "url": "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
            "dates": {2026: ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-10", "2026-07-15", "2026-09-02", "2026-10-28", "2026-12-09"],
                      2027: ["2027-01-27", "2027-03-03", "2027-04-28", "2027-06-02", "2027-07-21", "2027-09-08", "2027-10-27", "2027-12-08"]}},
    "RBA": {"name": "Reserve Bank of Australia", "url": "https://www.rba.gov.au/schedules-events/board-meeting-schedules.html",
            "dates": {2026: ["2026-02-03", "2026-03-17", "2026-05-05", "2026-06-16", "2026-08-11", "2026-09-29", "2026-11-03", "2026-12-08"],
                      2027: ["2027-02-09", "2027-03-23", "2027-05-04", "2027-06-22", "2027-08-10", "2027-09-28", "2027-11-02", "2027-12-14"]}},
    "RBI": {"name": "Reserve Bank of India (MPC)", "url": "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=62422",
            "dates": {2026: ["2026-04-08", "2026-06-05", "2026-08-05", "2026-10-07", "2026-12-04"], 2027: ["2027-02-05"]}},  # FY2026-27 schedule, announced 2026-03-23
    "SNB": {"name": "Swiss National Bank", "url": "https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions",
            "dates": {2026: ["2026-03-19", "2026-06-18", "2026-09-24"]}},  # the page does not list the December 2026 assessment yet
}
PARTIAL = {("ECB", 2026): "ONLY THE REMAINING 2026 MEETINGS ARE LISTED ON THE ECB PAGE", ("RBI", 2027): "RBI HAS PUBLISHED ONLY THE FEBRUARY 2027 MEETING (FY2026-27)",
           ("SNB", 2026): "THE SNB PAGE DOES NOT LIST THE DECEMBER 2026 ASSESSMENT YET"}
ORDER = tuple(BANKS)
RANGE_NOTE = "DECISION DATES FROM EACH BANK'S PUBLISHED SCHEDULE, TRANSCRIBED " + AS_OF


def decisions(bank: str, year: int, live: list[str] | None = None) -> list[str] | None:
    """Sorted decision dates of `year`, or None when that year is not loaded. The Fed's list is `live` (from the Fed's own page)."""
    if BANKS[bank].get("live"):
        got = sorted(d for d in (live or []) if d.startswith(f"{year}-"))
        return got or None
    got = BANKS[bank]["dates"].get(year)
    return sorted(got) if got else None


def around(dates: list[str], today: date) -> tuple[str | None, str | None, str | None]:
    """(last decision on or before today, next after today, the one after that)."""
    iso = today.isoformat()
    past = [d for d in dates if d <= iso]
    future = [d for d in dates if d > iso]
    return (past[-1] if past else None, future[0] if future else None, future[1] if len(future) > 1 else None)
