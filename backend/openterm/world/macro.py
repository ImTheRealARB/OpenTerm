"""Service functions behind ECST, WECO and CENB (`/api/world/stats|weco|cenb`): router calls, caching, labels."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from ..router import AllFailed
from ..service import DataError
from . import cenb, dbsearch, stats

STATS_TTL_S = 6 * 3600.0
RATES_TTL_S = 1800.0
SEARCH_TTL_S = 3600.0  # DBSRCH: the catalogue of a statistics mirror changes slowly


def indicator(text: str) -> stats.Indicator:
    ind = stats.INDICATORS.get(text.strip().upper())
    if ind is None:
        raise DataError("bad_request", f"UNKNOWN INDICATOR {text[:20].upper()}. USE: {' '.join(dict.fromkeys(i.alias for i in stats.INDICATORS.values()))} OR DBN:<provider>/<dataset>/<series>")
    return ind


async def ecst(svc: Any, country: str, ind_text: str) -> dict[str, Any]:
    dbn = stats.parse_dbn_ref(ind_text)
    if dbn:
        async def fetch() -> dict:
            out, failed = await svc.router.call("worldstats_dbn", lambda p: p.worldstats_dbn(*dbn))
            return {"data": out, "fallback_from": failed, "source": out["source"]}

        return await svc._swr("w:dbn:" + "/".join(dbn), STATS_TTL_S, fetch)
    ind = indicator(ind_text)
    try:
        iso = stats.resolve_country(country)
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e

    async def fetch2() -> dict:
        out, failed = await svc.router.call("worldstats", lambda p: p.worldstats(iso, ind))
        return {"data": out, "fallback_from": failed, "source": out["source"]}

    return await svc._swr(f"w:st:{iso}:{ind.alias}", STATS_TTL_S, fetch2)


async def weco(svc: Any) -> dict[str, Any]:
    cols = [stats.INDICATORS[c] for c in stats.WECO_COLUMNS]

    async def fetch() -> dict:
        async def one(ind: stats.Indicator):
            out, _ = await svc.router.call("worldstats_latest", lambda p: p.worldstats_latest(list(stats.G20), ind))
            return out

        got = await asyncio.gather(*(one(i) for i in cols), return_exceptions=True)
        latest: dict[str, dict] = {}
        failed: list[str] = []
        for ind, g in zip(cols, got, strict=True):
            if isinstance(g, AllFailed):
                failed.append(ind.alias)
            elif isinstance(g, BaseException):
                raise g
            else:
                latest[ind.alias] = g
        if not latest:
            raise got[0]  # every column failed: surface the first reason through the usual DataError path
        rows = stats.weco_rows(latest, datetime.now(UTC).year)
        return {"data": {"rows": rows, "columns": [{"alias": i.alias, "label": i.label, "unit": i.unit} for i in cols], "failed": failed,
                         "note": "EACH CELL IS THE COUNTRY'S MOST RECENT VALUE WITH ITS OWN DATA YEAR; YEARS ARE NOT ALIGNED ACROSS COUNTRIES",
                         "source": "worldbank"}, "fallback_from": [], "source": "worldbank"}

    return await svc._swr("w:weco", STATS_TTL_S, fetch)


async def cenb_table(svc: Any) -> dict[str, Any]:
    async def rates_fetch() -> dict:
        out, failed = await svc.router.call("policy_rates", lambda p: p.policy_rates())
        return {"data": out, "fallback_from": failed, "source": "policy_rates"}

    rates_env, fomc = await asyncio.gather(svc._swr("w:rates", RATES_TTL_S, rates_fetch), svc.derivs.fomc_dates(), return_exceptions=True)
    notes = []
    if isinstance(rates_env, BaseException):
        if not isinstance(rates_env, (AllFailed, DataError)):
            raise rates_env
        rates_env, rates = None, {}
        notes.append("POLICY RATES UNAVAILABLE (ALL SOURCES FAILED)")
    else:
        rates = rates_env["data"]
    if isinstance(fomc, BaseException):
        if not isinstance(fomc, (AllFailed, DataError)):
            raise fomc
        fomc = None
        notes.append("FOMC: STALE (federalreserve.gov DID NOT ANSWER)")
    today = datetime.now(UTC).date()
    data = cenb.build(rates, fomc, today)
    data["notes"] = notes
    return {"data": data, "source": "fed / ecb / boe / boc rates + dated calendar table",
            "as_of": rates_env["as_of"] if rates_env else time.time(), "age_s": rates_env["age_s"] if rates_env else 0.0,
            "stale": bool(rates_env and rates_env["stale"]), "fallback_from": rates_env["fallback_from"] if rates_env else []}


async def dbsearch_svc(svc: Any, q: str, dataset: str, offset: int) -> dict[str, Any]:
    """DBSRCH: datasets for the words, or (with `dataset=<provider>/<code>`) the matching series of that one dataset. Parsers live in `dbsearch.py`."""
    ref = None
    if dataset.strip():
        ref = dbsearch.parse_dataset_ref(dataset)
        if ref is None:
            raise DataError("bad_request", "DATASET MUST LOOK LIKE <PROVIDER>/<DATASET>, E.G. ECB/CSEC")
    try:
        words = dbsearch.norm_query(q, required=ref is None)  # datasets need words; the series of one dataset may be listed without any
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e

    async def fetch() -> dict:
        if ref:
            out, failed = await svc.router.call("worldstats_search", lambda p: p.search_series(ref[0], ref[1], words, offset))
            source = f"dbnomics · {ref[0]}/{ref[1]} series"
        else:
            out, failed = await svc.router.call("worldstats_search", lambda p: p.search_datasets(words, offset))
            source = "dbnomics · dataset search"
        out["source"] = source
        return {"data": out, "fallback_from": failed, "source": source}

    return await svc._swr(f"w:dbs:{ref[0] + '/' + ref[1] if ref else '*'}:{offset}:{words.lower()}", SEARCH_TTL_S, fetch)
