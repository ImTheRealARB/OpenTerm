"""Service functions behind TRADE (UN Comtrade) and USMAC (BLS, BEA, Census): `/api/world/trade` and `/api/world/usmac`.

Flow for every call: read the key from the key store NOW (so a key saved in APIKEYS works with no restart) -> no key means
HTTP 424 KEY REQUIRED before any network call -> the router calls the adapter (`providers/tradeus.py`) -> a pure parser turns the
answer into rows -> cached for hours (the free quotas are small: Comtrade 500 calls a day, BLS 500 queries a day).
A body the parser does not understand is an error shown to the user, never a guess.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from ..redact import redact
from ..service import DataError
from . import bea, bls, census, comtrade
from .seriesboard import KeyRejected, NoData, NotUnderstood

TRADE_TTL_S = 12 * 3600.0  # annual data, 500 calls a day
USMAC_TTL_S = 6 * 3600.0  # monthly or quarterly data, 500 queries a day


async def get_key(keys: Any, name: str, field: str) -> str:
    """The key's value, or DataError key_required (HTTP 424) naming the variable. The store may read the OS keyring, so a thread."""
    values = await asyncio.to_thread(keys.get, name)
    if not values or not values.get(field):
        raise DataError("key_required", "KEY REQUIRED", key=field)
    return values[field]


def _label(base: str, adapter_source: str, recorded: bool = False) -> str:
    """Fixture mode answers with test data: say so on the source line, like every other test data.

    `recorded` = the fixture is a real answer recorded earlier (BEA data tables, Comtrade India-USA), so it is not "invented"."""
    if ":fixture" not in adapter_source:
        return base
    return f"{base} · FIXTURE (RECORDED 2026-11-05, NOT LIVE)" if recorded else f"{base} · FIXTURE (DOC-SHAPED TEST DATA, NOT REAL)"


def _guard(field: str, fn: Callable[[], Any]) -> Any:
    """Run a pure parser. A key the source rejected inside a 200 body is KEY REQUIRED; any other surprise is PROVIDER DOWN with the reason."""
    try:
        return fn()
    except KeyRejected as e:
        raise DataError("key_required", redact(str(e)), key=field) from e
    except NoData as e:
        raise DataError("not_found", redact(str(e))) from e
    except NotUnderstood as e:
        raise DataError("unavailable", redact(f"ANSWER NOT UNDERSTOOD: {e}")) from e


async def _cached(svc: Any, cache_key: str, ttl: float, fetch: Callable[[], Any]) -> dict[str, Any]:
    async def inner() -> dict:
        data, failed = await fetch()
        return {"data": data, "fallback_from": failed, "source": data["source"]}

    return await svc._swr(cache_key, ttl, inner)


# --- TRADE: UN Comtrade ---
async def trade(svc: Any, keys: Any, reporter: str, partner: str, hs: str, n_years: int) -> dict[str, Any]:
    try:
        rep, par, cmd = comtrade.country(reporter), comtrade.country(partner or "WLD"), comtrade.commodity(hs)
        if not 1 <= n_years <= comtrade.MAX_YEARS:
            raise ValueError(f"ASK FOR 1 TO {comtrade.MAX_YEARS} YEARS")
        if rep[0] == par[0]:
            raise ValueError("REPORTER AND PARTNER ARE THE SAME COUNTRY")
        if rep[0] == "WLD":  # Comtrade answers an empty 200 for reporterCode 0; refuse here instead of spending a call of the 500/day quota
            raise ValueError("REPORTER MUST BE ONE COUNTRY. WLD (THE WORLD) CAN ONLY BE THE PARTNER")
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e
    key = await get_key(keys, "comtrade", "UN_COMTRADE_KEY")
    this_year = time.gmtime().tm_year
    years = list(range(this_year - n_years, this_year))  # the current year has no annual figures yet

    async def fetch() -> tuple[dict, list[str]]:
        params = comtrade.build_params(rep[1], par[1], cmd, years)
        out, failed = await svc.router.call("comtrade", lambda p: p.comtrade(key, comtrade.URL, params))
        data = _guard("UN_COMTRADE_KEY", lambda: comtrade.parse(out["body"], rep, par, cmd, years))
        data["source"] = _label(data["source"], out["source"])
        return data, failed

    return await _cached(svc, f"w:trade:{rep[0]}:{par[0]}:{cmd}:{years[0]}-{years[-1]}", TRADE_TTL_S, fetch)


# --- USMAC: BLS, BEA, Census ---
async def usmac(svc: Any, keys: Any, src: str, q: str, years: int) -> dict[str, Any]:
    src = src.strip().upper()
    words = q.strip().upper().split()
    if src == "BLS":
        return await _bls(svc, keys, " ".join(words), years)
    if src == "BEA":
        return await _bea(svc, keys, " ".join(words))
    if src == "CENSUS":
        return await _census(svc, keys, words)
    raise DataError("bad_request", f"SOURCE MUST BE BLS, BEA OR CENSUS, NOT {src[:12]}")


def _tag(data: dict, src: str) -> dict:
    data["src"] = src
    return data


async def _bls(svc: Any, keys: Any, q: str, years: int) -> dict[str, Any]:
    try:
        wanted = bls.parse_ids(q)
        if not 1 <= years <= 20:
            raise ValueError("YEARS MUST BE 1 TO 20")
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e
    key = await get_key(keys, "bls", "BLS_API_KEY")
    this_year = time.gmtime().tm_year

    async def fetch() -> tuple[dict, list[str]]:
        body = bls.build_body([sid for _, sid in wanted], this_year - years + 1, this_year, key)
        out, failed = await svc.router.call("bls", lambda p: p.bls(key, bls.URL, body))
        data = _guard("BLS_API_KEY", lambda: bls.parse(out["body"], wanted))
        data["source"] = _label(data["source"], out["source"])
        return _tag(data, "BLS"), failed

    return await _cached(svc, f"w:bls:{','.join(s for _, s in wanted)}:{years}", USMAC_TTL_S, fetch)


async def _bea(svc: Any, keys: Any, q: str) -> dict[str, Any]:
    try:
        aliases = bea.parse_aliases(q)
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e
    key = await get_key(keys, "bea", "BEA_API_KEY")
    this_year = time.gmtime().tm_year

    async def fetch() -> tuple[dict, list[str]]:
        groups: dict[Any, list[bea.Entry]] = {}
        for a in aliases:  # GDPG and PCEG share a table: one call serves both
            groups.setdefault(bea.call_key(bea.CATALOG[a]), []).append(bea.CATALOG[a])
        series: list[dict] = []
        failed: list[str] = []
        src = ""
        for entries in groups.values():
            params = bea.build_params(entries[0], this_year, key)
            out, f = await svc.router.call("bea", lambda p, params=params: p.bea(key, bea.URL, params))
            failed += f
            src = out["source"]
            for e in entries:
                series += _guard("BEA_API_KEY", lambda e=e, out=out: bea.parse(out["body"], e))
        return _tag({"series": series, "missing": [], "messages": [], "source": _label(bea.SOURCE, src, recorded=True),
                     "note": "BEA TABLES AS PUBLISHED (NIPA T10101, T10105; ITA; GDP BY INDUSTRY). LAST = NEWEST PERIOD WITH A VALUE."}, "BEA"), failed

    return await _cached(svc, f"w:bea:{','.join(aliases)}", USMAC_TTL_S, fetch)


async def _census(svc: Any, keys: Any, words: list[str]) -> dict[str, Any]:
    this_year = time.gmtime().tm_year
    try:
        if words and words[0] == "TRADE":
            mode, args = "TRADE", census.parse_trade(words[1:])
        else:
            mode, args = "RETAIL", census.parse_retail([w for w in words if w != "RETAIL"])
    except ValueError as e:
        raise DataError("bad_request", str(e)) from e
    key = await get_key(keys, "census", "CENSUS_API_KEY")

    async def fetch() -> tuple[dict, list[str]]:
        failed: list[str] = []
        if mode == "RETAIL":
            params = census.retail_params(args, f"{this_year - 2}-01", key)
            out, failed = await svc.router.call("census", lambda p: p.census(key, f"{census.BASE}/eits/marts", params))
            data = _guard("CENSUS_API_KEY", lambda: census.parse_retail_answer(out["body"], args))
        else:
            name, code, hs = args
            bodies = []
            for flow in ("X", "M"):
                path, params = census.trade_params(flow, code, hs, f"{this_year - 1}-01", key)
                out, f = await svc.router.call("census", lambda p, path=path, params=params: p.census(key, f"{census.BASE}/{path}", params))
                failed += f
                bodies.append(out["body"])
            data = _guard("CENSUS_API_KEY", lambda: census.parse_trade_answers(bodies[0], bodies[1], name, hs))
        data["source"] = _label(data["source"], out["source"])
        return _tag(data, "CENSUS"), failed

    return await _cached(svc, f"w:census:{mode}:{'-'.join(str(a) for a in (args if isinstance(args, (list, tuple)) else [args]))}", USMAC_TTL_S, fetch)
