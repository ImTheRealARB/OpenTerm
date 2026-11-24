"""CTM (contract table per futures root) and CDR (exchange calendar). Pure: dates in, rows out.

CTM: the expiry rules below were written from the exchanges' contract specifications (CME Group rulebook chapters for each root) and
are kept in one reviewed table, `RULES`. Business days use the NYSE holiday calendar as a stand-in for the CME Globex calendar:
the two differ on a few days (CME trades on some NYSE holidays with an early halt), so every date is labelled ESTIMATED and the
exchange's own calendar is the authority. Contract months come from the CT table (derivs/fut_parse.ROOTS), so CTM lists the same
contracts CT prices.

CDR: regular hours per market (the same table the market lights use, frontend/src/markets/hours.ts; a test keeps the two equal),
plus the holidays and early closes the lights already know.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from ..derivs import fut_parse as fp
from ..world import nse_holidays, nyse_holidays

# --- business days ------------------------------------------------------------------------------------------------------------

_HOL_CACHE: dict[int, set[date]] = {}


def _hols(year: int) -> set[date]:
    if year not in _HOL_CACHE:
        try:
            _HOL_CACHE[year] = set(nyse_holidays.holidays(year))
        except ValueError:  # outside the rule table's years: weekends only
            _HOL_CACHE[year] = set()
    return _HOL_CACHE[year]


def is_bday(d: date) -> bool:
    return d.weekday() < 5 and d not in _hols(d.year)


def add_bdays(d: date, n: int) -> date:
    """Move n business days (n < 0 goes back). n = 0 returns d unchanged."""
    step = 1 if n > 0 else -1
    while n:
        d += timedelta(days=step)
        if is_bday(d):
            n -= step
    return d


def last_bday(y: int, m: int) -> date:
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    while not is_bday(d):
        d -= timedelta(days=1)
    return d


def first_bday(y: int, m: int) -> date:
    d = date(y, m, 1)
    while not is_bday(d):
        d += timedelta(days=1)
    return d


def nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _prev_month(y: int, m: int, k: int = 1) -> tuple[int, int]:
    idx = y * 12 + (m - 1) - k
    return idx // 12, idx % 12 + 1


# --- CTM rules ----------------------------------------------------------------------------------------------------------------


def _cl_ltd(y: int, m: int) -> date:
    py, pm = _prev_month(y, m)
    d25 = date(py, pm, 25)
    base = d25 if is_bday(d25) else add_bdays(d25, -1)
    return add_bdays(base, -3)


def _comex_ltd(y: int, m: int) -> date:
    return add_bdays(last_bday(y, m), -2)


def _third_friday(y: int, m: int) -> date:
    d = nth_weekday(y, m, 4, 3)
    return d if is_bday(d) else add_bdays(d, -1)


def _fx_ltd(y: int, m: int) -> date:
    return add_bdays(nth_weekday(y, m, 2, 3), -2)


def _grain_ltd(y: int, m: int) -> date:
    return add_bdays(date(y, m, 15), -1)


def _prior_lbd(y: int, m: int) -> date:
    return last_bday(*_prev_month(y, m))


Rule = tuple[Callable[[int, int], date], Callable[[int, int], date] | None, str, str]

#: root -> (last trade day, first notice day or None when cash-settled / no notice, settlement, the rule in words)
RULES: dict[str, Rule] = {
    "CL": (_cl_ltd, lambda y, m: add_bdays(_cl_ltd(y, m), 1), "PHYSICAL",
           "LAST TRADE: 3 BUSINESS DAYS BEFORE THE 25TH OF THE PRIOR MONTH (BEFORE THE BUSINESS DAY PRIOR TO THE 25TH IF IT IS A HOLIDAY)"),
    "BZ": (lambda y, m: last_bday(*_prev_month(y, m, 2)), None, "CASH",
           "LAST TRADE: LAST BUSINESS DAY OF THE SECOND MONTH BEFORE THE CONTRACT MONTH"),
    "NG": (lambda y, m: add_bdays(date(y, m, 1), -3), lambda y, m: add_bdays(add_bdays(date(y, m, 1), -3), 1), "PHYSICAL",
           "LAST TRADE: 3 BUSINESS DAYS BEFORE THE FIRST CALENDAR DAY OF THE CONTRACT MONTH"),
    "HO": (_prior_lbd, None, "PHYSICAL", "LAST TRADE: LAST BUSINESS DAY OF THE MONTH BEFORE THE CONTRACT MONTH"),
    "RB": (_prior_lbd, None, "PHYSICAL", "LAST TRADE: LAST BUSINESS DAY OF THE MONTH BEFORE THE CONTRACT MONTH"),
    "GC": (_comex_ltd, _prior_lbd, "PHYSICAL", "LAST TRADE: THIRD-LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "SI": (_comex_ltd, _prior_lbd, "PHYSICAL", "LAST TRADE: THIRD-LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "HG": (_comex_ltd, _prior_lbd, "PHYSICAL", "LAST TRADE: THIRD-LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ES": (_third_friday, None, "CASH", "LAST TRADE: THIRD FRIDAY OF THE CONTRACT MONTH (9:30 ET SPECIAL OPENING QUOTATION)"),
    "NQ": (_third_friday, None, "CASH", "LAST TRADE: THIRD FRIDAY OF THE CONTRACT MONTH (9:30 ET SPECIAL OPENING QUOTATION)"),
    "RTY": (_third_friday, None, "CASH", "LAST TRADE: THIRD FRIDAY OF THE CONTRACT MONTH (9:30 ET SPECIAL OPENING QUOTATION)"),
    "6E": (_fx_ltd, None, "PHYSICAL", "LAST TRADE: 2 BUSINESS DAYS BEFORE THE THIRD WEDNESDAY OF THE CONTRACT MONTH (9:16 CT)"),
    "ZT": (last_bday, _prior_lbd, "PHYSICAL", "LAST TRADE: LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ZF": (last_bday, _prior_lbd, "PHYSICAL", "LAST TRADE: LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ZN": (lambda y, m: add_bdays(last_bday(y, m), -7), _prior_lbd, "PHYSICAL",
           "LAST TRADE: 7TH BUSINESS DAY BEFORE THE LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ZB": (lambda y, m: add_bdays(last_bday(y, m), -7), _prior_lbd, "PHYSICAL",
           "LAST TRADE: 7TH BUSINESS DAY BEFORE THE LAST BUSINESS DAY OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ZQ": (last_bday, None, "CASH", "LAST TRADE: LAST BUSINESS DAY OF THE CONTRACT MONTH (SETTLES TO THE MONTH'S AVERAGE EFFR)"),
    "ZC": (_grain_ltd, _prior_lbd, "PHYSICAL", "LAST TRADE: BUSINESS DAY BEFORE THE 15TH OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ZS": (_grain_ltd, _prior_lbd, "PHYSICAL", "LAST TRADE: BUSINESS DAY BEFORE THE 15TH OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
    "ZW": (_grain_ltd, _prior_lbd, "PHYSICAL", "LAST TRADE: BUSINESS DAY BEFORE THE 15TH OF THE CONTRACT MONTH; FIRST NOTICE: LAST BUSINESS DAY OF THE PRIOR MONTH"),
}


def contracts(root: str, today: date) -> list[dict]:
    """The contracts CT lists for `root`, each with its last trade and first notice dates. Expired contracts are dropped."""
    root = root.upper()
    if root not in RULES or root not in fp.ROOTS:
        raise ValueError(f"NO RULE FOR ROOT {root[:6]}. KNOWN: {' '.join(sorted(RULES))}")
    ltd_fn, fnd_fn, settle, _ = RULES[root]
    rows = []
    for sym, y, m in fp.contract_symbols(root, today.year, today.month):
        ltd = ltd_fn(y, m)
        if ltd < today:
            continue
        fnd = fnd_fn(y, m) if fnd_fn else None
        rows.append({"contract": sym.split(".")[0], "month": fp.label(y, m), "last_trade": ltd.isoformat(),
                     "first_notice": fnd.isoformat() if fnd else None, "days_left": (ltd - today).days,
                     "notice_days_left": (fnd - today).days if fnd else None, "settle": settle})
    return rows


# --- CDR ----------------------------------------------------------------------------------------------------------------------

#: code -> (name, time zone, sessions as "HH:MM-HH:MM" local). MUST equal frontend/src/markets/hours.ts (test_phase30 checks it).
HOURS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "NY": ("NYSE / NASDAQ", "America/New_York", ("09:30-16:00",)),
    "LN": ("LONDON STOCK EXCHANGE", "Europe/London", ("08:00-16:30",)),
    "IN": ("NSE / BSE", "Asia/Kolkata", ("09:15-15:30",)),
    "TK": ("TOKYO STOCK EXCHANGE", "Asia/Tokyo", ("09:00-11:30", "12:30-15:30")),
    "HK": ("HONG KONG EXCHANGE", "Asia/Hong_Kong", ("09:30-12:00", "13:00-16:00")),
}


def nyse_rows(year: int, today: date) -> list[dict]:
    hol = nyse_holidays.holidays(year)
    early = nyse_holidays.early_closes(year)
    rows = [{"date": d.isoformat(), "market": "NY", "what": "CLOSED", "name": n} for d, n in hol.items()]
    rows += [{"date": d.isoformat(), "market": "NY", "what": "EARLY CLOSE 13:00 ET", "name": n} for d, n in early.items()]
    return _mark(rows, today)


def nse_rows(year: int, today: date) -> list[dict]:
    return _mark([{"date": d.isoformat(), "market": "IN", "what": "CLOSED", "name": n} for d, n in nse_holidays.holidays(year).items()], today)


def _mark(rows: list[dict], today: date) -> list[dict]:
    for r in rows:
        r["days_away"] = (date.fromisoformat(r["date"]) - today).days
    return sorted(rows, key=lambda r: r["date"])
