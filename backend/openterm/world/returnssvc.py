"""Service functions behind TRA and BETA (`/api/world/tra`, `/api/world/beta`): fetch daily bars, run the pure maths in `returns.py`.

The bars come from `DataService.history` (so they use the source hierarchy, the cache, fixture mode and the IMPORT local bars like
every other panel). Nothing is cached here: the maths over a few thousand numbers costs a few milliseconds, and the bars
underneath are cached already.
"""

from __future__ import annotations

from typing import Any

from ..barfetch import fetch_bars
from ..errors import DataError
from . import returns as R

MAX_SYMBOLS = 12  # TRA rows; each one is a history request, paced by `barfetch`
DEFAULT_BENCH = "SPY"


def _upper(raw: str) -> str:
    return raw.strip().upper()


def _envelope(data: dict, envs: list[dict]) -> dict:
    """The standard answer shape (source, as_of, age_s, stale), summarising the history answers the numbers came from:
    the OLDEST fetch time, the longest age, stale if any input is stale."""
    sources = sorted({str(e.get("source") or "?") for e in envs})
    return {
        "data": data, "source": ", ".join(sources), "as_of": min(e["as_of"] for e in envs),
        "age_s": max(e.get("age_s", 0) for e in envs), "stale": any(e.get("stale") for e in envs), "fallback_from": [],
    }


async def tra(svc: Any, symbols: list[str], bench: str, range_: str) -> dict:
    """TRA: total return of each symbol over `range_` against `bench` (default SPY)."""
    syms = list(dict.fromkeys(_upper(s) for s in symbols if s.strip()))  # de-duplicated, order kept
    if not syms:
        raise DataError("bad_request", "USAGE: TRA SYM[,SYM...] [RANGE] [VS BENCHMARK]")
    if len(syms) > MAX_SYMBOLS:
        raise DataError("bad_request", f"AT MOST {MAX_SYMBOLS} SYMBOLS")
    bench = _upper(bench) or DEFAULT_BENCH
    wanted = [*syms, bench] if bench not in syms else syms
    ok, bad = await fetch_bars(svc, wanted, range_, tolerate=True)
    if bench in bad:  # nothing can be compared without it: say why, loudly
        e = bad[bench]
        raise DataError(e.kind, f"BENCHMARK {bench}: {e}", getattr(e, "detail", None))
    series = {s: R.series_from_bars(s, ok[s]["data"]) for s in ok}
    rows, bench_row, warnings = R.tra_table(
        [(series[s], str(ok[s]["source"])) for s in syms if s in series], (series[bench], str(ok[bench]["source"])),
    )
    for s in syms:  # a symbol with no data keeps its place in the table, with the reason
        if s in bad:
            rows.insert(syms.index(s), {"symbol": s, "source": None, "error": f"{bad[s]}"})
    first = next((series[s] for s in syms if s in series and series[s].dates), None)
    chart = R.cumulative_pair(first, series[bench]) if first is not None and first.symbol != bench else None
    data = {"range": range_.upper(), "benchmark": bench_row, "rows": rows, "warnings": warnings, "chart": chart}
    return _envelope(data, [ok[s] for s in ok])


async def beta(svc: Any, symbol: str, bench: str, range_: str, per: str, win: int) -> dict:
    """BETA: regression of `symbol`'s returns on `bench`'s, daily / weekly / monthly, plus a rolling beta of `win` returns."""
    symbol, bench, per = _upper(symbol), _upper(bench) or DEFAULT_BENCH, per.strip().upper() or "D"
    if per not in R.PERIODS_PER_YEAR:
        raise DataError("bad_request", f"BAD RETURN PERIOD {per}: USE D, W OR M")
    if not symbol:
        raise DataError("bad_request", "USAGE: BETA SYM [VS BENCHMARK] [RANGE] [D|W|M] [WIN=60]")
    ok, bad = await fetch_bars(svc, [symbol] if symbol == bench else [symbol, bench], range_, tolerate=True)
    for s in (symbol, bench):
        if s in bad:
            e = bad[s]
            raise DataError(e.kind, f"{'BENCHMARK ' if s == bench and s != symbol else ''}{s}: {e}", getattr(e, "detail", None))
    sec, bse = R.series_from_bars(symbol, ok[symbol]["data"]), R.series_from_bars(bench, ok[bench]["data"])
    data = {"symbol": symbol, "benchmark": bench, "range": range_.upper(), **R.beta_report(sec, bse, per, win),
            "sources": {symbol: ok[symbol]["source"], bench: ok[bench]["source"]}}
    return _envelope(data, list(ok.values()))
