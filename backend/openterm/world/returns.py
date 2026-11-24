"""TRA (total return) and BETA (regression of a security's returns on a benchmark's): the pure maths.

Phase 22 items 4 and 5. Everything here is plain Python on lists (no pandas / numpy: the server process never imports them, and
a 10-year daily series is only about 2,500 numbers). It takes the columnar bars that `/api/history` gives (`t`, `c`, `adj`, `tz`)
and returns plain dicts; the network side (fetching the bars, the envelope) is `returnssvc.py`.

Three ideas to know before reading the code:

* A "bar" is stamped with a moment in time (epoch seconds), but two securities are only comparable on the same TRADING DATE, and
  the date depends on the exchange: an NSE bar opens at 03:45 UTC, a New York bar at 14:30 UTC. So each bar is turned into a date
  in its own exchange's time zone (`Series.dates`) and two series are lined up on those dates (an "inner join": only dates both
  traded count).
* Prices come in two flavours. The raw close is only split-adjusted, so it ignores dividends. The adjusted close (`adj`, Yahoo's
  `adjclose`) also folds the dividends back in, so adj-end / adj-start - 1 is the TOTAL return (price change plus reinvested
  dividends). A source with no `adj` can only give the price return, and the answer says so (`basis`).
* A simple return is p[i] / p[i-1] - 1. Beta is the slope of the best-fit line of the security's returns (y) against the
  benchmark's returns (x): how many percent the security tends to move when the benchmark moves one percent.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..errors import DataError

ANNUAL_DAYS = 365.25  # calendar days in a year, for the compound annual growth rate (CAGR)
PERIODS_PER_YEAR = {"D": 252, "W": 52, "M": 12}  # trading days / weeks / months in a year, to scale an alpha up to a year
BLUME_RAW, BLUME_MEAN = 0.67, 0.33  # adjusted beta = 0.67 x raw + 0.33 (Blume: betas drift towards 1 over time)
MIN_RETURNS = 3  # a line needs 2 points; the standard error divides by (n - 2), so 3 is the least that gives one


# --------------------------------------------------------------------------------------------------------------------------
# Bars -> one close per trading date
# --------------------------------------------------------------------------------------------------------------------------
@dataclass
class Series:
    """One security's daily closes, one entry per trading date, ascending."""

    symbol: str
    dates: list[str]  # "YYYY-MM-DD" in the exchange's own time zone (ISO dates sort the same as calendar order)
    close: list[float]  # raw close (split-adjusted by the source, no dividends)
    adj: list[float | None]  # dividend-adjusted close, or None for a bar the source gave no value for
    has_adj: bool  # the source sent an adj column at all


def _zone(tz: str | None, symbol: str) -> ZoneInfo:
    """The exchange time zone of the bars (crypto sources say UTC; a source that names none is read as UTC)."""
    try:
        return ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as e:
        # Fail loudly: lining bars up on the wrong zone's dates would silently shift returns by a day.
        raise DataError("bad_request", f"{symbol}: UNKNOWN TIME ZONE {tz} ON THE SOURCE'S BARS") from e


def series_from_bars(symbol: str, bars: dict) -> Series:
    """Daily bars (the `data` of a `/api/history` answer) -> a `Series`. A bar without a positive close is skipped; when two bars
    fall on the same local date (a source repeating the last day) the later one wins."""
    zone = _zone(bars.get("tz"), symbol)
    t, c, adj = bars["t"], bars["c"], bars.get("adj")
    has_adj = adj is not None and len(adj) == len(t)
    by_date: dict[str, tuple[float, float | None]] = {}
    for i, ts in enumerate(t):
        close = c[i]
        if close is None or not math.isfinite(close) or close <= 0:
            continue
        a = adj[i] if has_adj else None
        if a is not None and (not math.isfinite(a) or a <= 0):
            a = None
        by_date[datetime.fromtimestamp(ts, zone).date().isoformat()] = (float(close), a)
    dates = sorted(by_date)
    return Series(symbol, dates, [by_date[d][0] for d in dates], [by_date[d][1] for d in dates], bool(has_adj))


def _is_price_index(symbol: str) -> bool:
    """An index (`^GSPC`, `^NSEI`) is a price level: its adjusted close is just the close, with no dividends in it, so calling that
    a total return would be wrong. Treated as price-only."""
    return symbol.startswith("^")


def total_basis(s: Series) -> bool:
    """True when this series can give a TOTAL return (it has an adjusted close and is not a price index)."""
    return s.has_adj and not _is_price_index(s.symbol)


# --------------------------------------------------------------------------------------------------------------------------
# TRA
# --------------------------------------------------------------------------------------------------------------------------
def _cagr(ret: float, first: str, last: str) -> float | None:
    """Compound annual growth rate from a total gain `ret` (0.25 = +25 %) over the calendar days between two dates."""
    days = (date.fromisoformat(last) - date.fromisoformat(first)).days
    if days <= 0:
        return None
    return (1 + ret) ** (ANNUAL_DAYS / days) - 1


def window_return(s: Series, start: str, end: str) -> dict | None:
    """Price and total return of `s` between the first bar on or after `start` and the last bar on or before `end`.

    Returns None when fewer than 2 bars fall in the window. `total` / `dividend` are None for a price-only series (no adjusted
    close, or an index), or when the source left a gap in the adjusted close exactly at the first or last bar.
    """
    i0 = bisect_left(s.dates, start)
    i1 = bisect_right(s.dates, end) - 1
    if i1 <= i0:
        return None
    price = s.close[i1] / s.close[i0] - 1
    total = None
    if total_basis(s):
        a0, a1 = s.adj[i0], s.adj[i1]
        if a0 is not None and a1 is not None:
            total = a1 / a0 - 1
    basis = "TOTAL" if total is not None else "PRICE"
    best = total if total is not None else price  # the return the annualised figure is built from
    return {
        "first": s.dates[i0], "last": s.dates[i1], "days": (date.fromisoformat(s.dates[i1]) - date.fromisoformat(s.dates[i0])).days,
        "price_return": price, "total_return": total, "dividend_part": None if total is None else total - price,
        "annualised": _cagr(best, s.dates[i0], s.dates[i1]), "basis": basis,
    }


def _pct(x: float | None) -> float | None:
    """A fraction as a percentage rounded to 4 decimals (0.123456 -> 12.3456); None stays None."""
    return None if x is None else round(x * 100, 4)


def _row(symbol: str, source: str, w: dict) -> dict:
    """One output row from a `window_return` answer (percentages, not fractions)."""
    return {
        "symbol": symbol, "source": source, "first": w["first"], "last": w["last"], "days": w["days"], "basis": w["basis"],
        "price_return_pct": _pct(w["price_return"]), "total_return_pct": _pct(w["total_return"]),
        "dividend_part_pct": _pct(w["dividend_part"]), "annualised_pct": _pct(w["annualised"]),
    }


def _price_only(s: Series, source: str) -> str:
    """The warning for a series that can only give a price return."""
    why = "A PRICE INDEX HAS NO DIVIDENDS IN IT" if _is_price_index(s.symbol) else f"NO DIVIDEND DATA FROM {source.upper()}"
    return f"{s.symbol}: PRICE ONLY: {why}"


def tra_table(rows: list[tuple[Series, str]], bench: tuple[Series, str]) -> tuple[list[dict], dict, list[str]]:
    """The TRA table: one row per security and the benchmark row, plus warnings.

    `rows` / `bench` are (series, source name). Each security is measured over ITS OWN first to last bar. The benchmark
    column and the excess are measured over the SAME dates (the benchmark's bars inside that window), so "excess" compares like
    with like even when a security has a shorter history than the benchmark.
    Excess = the security's return minus the benchmark's, in TOTAL terms when both have a total return and in PRICE terms
    otherwise (the row says which with `excess_basis`).
    """
    out: list[dict] = []
    warnings: list[str] = []
    for s, source in rows:
        w = window_return(s, s.dates[0], s.dates[-1]) if s.dates else None
        if w is None:
            out.append({"symbol": s.symbol, "source": source, "error": "FEWER THAN 2 DAILY BARS IN THIS RANGE"})
            continue
        row = _row(s.symbol, source, w)
        if w["basis"] == "PRICE":
            warnings.append(_price_only(s, source))
        bw = window_return(bench[0], w["first"], w["last"])
        if bw is None:
            row.update(bench_return_pct=None, excess_pct=None, excess_basis=None)
            warnings.append(f"{s.symbol}: NO {bench[0].symbol} BARS BETWEEN {w['first']} AND {w['last']}, SO NO EXCESS")
        else:
            both_total = w["total_return"] is not None and bw["total_return"] is not None
            mine, theirs = (w["total_return"], bw["total_return"]) if both_total else (w["price_return"], bw["price_return"])
            row.update(bench_return_pct=_pct(theirs), excess_pct=_pct(mine - theirs), excess_basis="TOTAL" if both_total else "PRICE")
        out.append(row)
    bs, bsource = bench
    bw = window_return(bs, bs.dates[0], bs.dates[-1]) if bs.dates else None
    if bw is None:
        raise DataError("not_found", f"{bs.symbol}: FEWER THAN 2 DAILY BARS IN THIS RANGE")
    bench_row = _row(bs.symbol, bsource, bw)
    if bw["basis"] == "PRICE":
        warnings.append(_price_only(bs, bsource))
    return out, bench_row, warnings


def cumulative_pair(a: Series, b: Series) -> dict | None:
    """Two lines for the TRA chart: `a` and `b` rebased to 100 on their first COMMON date, on the dates both traded.

    Each line uses the adjusted close when its series has a total basis (so the line is a total-return index) and the raw close
    otherwise; `basis_a` / `basis_b` say which. None when the two share fewer than 2 dates.
    """
    common = sorted(set(a.dates) & set(b.dates))
    if len(common) < 2:
        return None
    ia = {d: i for i, d in enumerate(a.dates)}
    ib = {d: i for i, d in enumerate(b.dates)}

    def line(s: Series, idx: dict[str, int]) -> tuple[list[float], str]:
        use_adj = total_basis(s) and all(s.adj[idx[d]] is not None for d in common)
        vals = [(s.adj[idx[d]] if use_adj else s.close[idx[d]]) for d in common]
        return [round(100 * v / vals[0], 4) for v in vals], "TOTAL" if use_adj else "PRICE"  # type: ignore[operator]

    la, basis_a = line(a, ia)
    lb, basis_b = line(b, ib)
    return {"dates": common, "a": la, "b": lb, "symbol_a": a.symbol, "symbol_b": b.symbol, "basis_a": basis_a, "basis_b": basis_b}


# --------------------------------------------------------------------------------------------------------------------------
# BETA
# --------------------------------------------------------------------------------------------------------------------------
def aligned_closes(sec: Series, bench: Series) -> tuple[list[str], list[float], list[float], str]:
    """Dates both traded, the two close columns on those dates, and the basis word.

    Adjusted closes are used when BOTH series have them (dividends belong in a return); otherwise both use raw closes, so the two
    columns are always measured the same way.
    """
    ia = {d: i for i, d in enumerate(sec.dates)}
    ib = {d: i for i, d in enumerate(bench.dates)}
    common = sorted(set(ia) & set(ib))
    use_adj = total_basis(sec) and total_basis(bench) and all(sec.adj[ia[d]] is not None and bench.adj[ib[d]] is not None for d in common)
    ys = [(sec.adj[ia[d]] if use_adj else sec.close[ia[d]]) for d in common]
    xs = [(bench.adj[ib[d]] if use_adj else bench.close[ib[d]]) for d in common]
    return common, ys, xs, "ADJUSTED CLOSES" if use_adj else "RAW CLOSES (NO DIVIDENDS)"  # type: ignore[return-value]


def _period_key(d: str, per: str) -> tuple:
    """Which week / month a date belongs to, so the LAST aligned date of each can stand for the period."""
    y = date.fromisoformat(d)
    if per == "W":
        iso = y.isocalendar()
        return (iso.year, iso.week)
    return (y.year, y.month)


def period_returns(dates: list[str], ys: list[float], xs: list[float], per: str) -> tuple[list[str], list[float], list[float]]:
    """Simple returns of both columns at the chosen frequency: D = every aligned date, W = the last date of each ISO week,
    M = the last date of each month. Returns (end date of each return, security returns, benchmark returns)."""
    if per != "D":
        keep: list[int] = []
        for i, d in enumerate(dates):
            if keep and _period_key(dates[keep[-1]], per) == _period_key(d, per):
                keep[-1] = i  # a later date in the same week / month replaces the earlier one
            else:
                keep.append(i)
        dates, ys, xs = [dates[i] for i in keep], [ys[i] for i in keep], [xs[i] for i in keep]
    return dates[1:], [ys[i] / ys[i - 1] - 1 for i in range(1, len(ys))], [xs[i] / xs[i - 1] - 1 for i in range(1, len(xs))]


def ols(x: list[float], y: list[float]) -> dict:
    """Ordinary least squares of y on x: the straight line y = alpha + beta * x that makes the squared misses smallest.

    beta = Sxy / Sxx (how x and y move together, over how much x moves on its own), alpha = mean(y) - beta * mean(x).
    R-squared = share of y's ups and downs the line explains (1 - leftover squared misses / total squared spread of y).
    se_beta = how uncertain the slope is: sqrt( (leftover / (n - 2)) / Sxx ). Raises DataError when the data cannot give a line.
    """
    n = len(x)
    if n != len(y) or n < MIN_RETURNS:
        raise DataError("bad_request", f"ONLY {n} OVERLAPPING RETURNS: A BETA NEEDS AT LEAST {MIN_RETURNS}. TRY A LONGER RANGE")
    mx, my = math.fsum(x) / n, math.fsum(y) / n
    sxx = math.fsum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        raise DataError("bad_request", "THE BENCHMARK DID NOT MOVE OVER THIS RANGE: NO BETA")
    sxy = math.fsum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    syy = math.fsum((b - my) ** 2 for b in y)
    beta = sxy / sxx
    alpha = my - beta * mx
    sse = math.fsum((b - alpha - beta * a) ** 2 for a, b in zip(x, y, strict=True))  # squared misses left over
    # A security that never moved has nothing to explain: its R-squared is undefined, not 1 and not 0.
    r2 = None if syy <= 0 else max(0.0, 1 - sse / syy)
    se = math.sqrt(max(0.0, sse) / (n - 2) / sxx)
    return {"n": n, "beta": beta, "alpha": alpha, "r2": r2, "se_beta": se}


def rolling_beta(x: list[float], y: list[float], win: int) -> list[float | None]:
    """Beta over each trailing window of `win` returns (entry i uses returns i-win+1..i), None until a window is full.

    Running sums keep this O(n): when the window slides one step, add the new return and drop the oldest instead of re-adding
    all `win` of them. Sxx = sum(x^2) - sum(x)^2 / win and Sxy = sum(xy) - sum(x) sum(y) / win are the usual one-pass forms.
    """
    out: list[float | None] = [None] * len(x)
    sx = sy = sxy = sxx = 0.0
    for i in range(len(x)):
        sx, sy, sxy, sxx = sx + x[i], sy + y[i], sxy + x[i] * y[i], sxx + x[i] * x[i]
        if i >= win:  # the window now has win + 1 entries: drop the oldest
            j = i - win
            sx, sy, sxy, sxx = sx - x[j], sy - y[j], sxy - x[j] * y[j], sxx - x[j] * x[j]
        if i >= win - 1:
            var = sxx - sx * sx / win
            out[i] = None if var <= 1e-18 else (sxy - sx * sy / win) / var
    return out


def beta_report(sec: Series, bench: Series, per: str, win: int) -> dict:
    """Everything BETA shows: the regression numbers, the scatter points and the rolling beta."""
    dates, ys, xs, basis = aligned_closes(sec, bench)
    ends, ry, rx = period_returns(dates, ys, xs, per)
    fit = ols(rx, ry)
    ppy = PERIODS_PER_YEAR[per]
    roll = rolling_beta(rx, ry, win)
    keep = [i for i, b in enumerate(roll) if b is not None]
    return {
        "per": per, "periods_per_year": ppy, "basis": basis, "first": dates[0], "last": dates[-1], "n": fit["n"],
        "beta": round(fit["beta"], 6), "adj_beta": round(BLUME_RAW * fit["beta"] + BLUME_MEAN, 6),
        "alpha_pct": round(fit["alpha"] * 100, 6), "alpha_annual_pct": round(fit["alpha"] * ppy * 100, 4),
        "r2": None if fit["r2"] is None else round(fit["r2"], 6), "se_beta": round(fit["se_beta"], 6),
        # Scatter points in percent (x = benchmark return, y = security return), rounded to keep the answer small.
        "scatter": {"x": [round(v * 100, 4) for v in rx], "y": [round(v * 100, 4) for v in ry]},
        "rolling": {"win": win, "dates": [ends[i] for i in keep], "beta": [round(roll[i], 4) for i in keep]},  # type: ignore[arg-type]
    }
