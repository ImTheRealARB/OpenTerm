"""Service functions behind USASP, FEDREG, FEC and CONGRESS (`/api/world/usasp`, `/fedreg`, `/fec`, `/congress`).

Each one: parse the user's words (pure parsers in `usaspending.py`, `fedreg.py`, `fec.py`, `congress.py`), ask the router for the provider that owns the
capability, cache the answer in the shared stale-while-revalidate cache (`svc.swr`: a repeat costs the free upstream nothing) and wrap it with the label
that says what the data is. Without FEC_API_KEY / CONGRESS_API_KEY the provider raises `key_required` and the route answers 424
`KEY REQUIRED: set FEC_API_KEY in APIKEYS`; nothing is invented to fill the gap.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..errors import DataError
from ..router import AllFailed
from . import congress, fec, fedreg, usaspending
from .usgov import UsGovError

USASP_TTL_S = 3600.0  # awards are reported with a lag of days: an hour is fresh
FEDREG_TTL_S = 600.0  # the Register publishes once per business day
FEC_TTL_S = 1800.0
CONGRESS_TTL_S = 900.0


def _bad(e: UsGovError) -> DataError:
    return DataError(e.kind, str(e))


async def usasp(svc: Any, q: str) -> dict[str, Any]:
    """`q` empty or AGENCY = top awarding agencies; `AGENCY:<exact agency name>` = that agency's top contract recipients; other words = recipients and awards."""
    text = " ".join((q or "").split())
    window = usaspending.fiscal_window(date.today())
    if text.upper().startswith("AGENCY:") and text[7:].strip():
        agency = text[7:].strip()

        async def fetch_detail() -> dict:
            rows, failed = await svc.router.call("usaspending", lambda p: p.usasp_agency_recipients(agency, window))
            return {"data": usaspending.agency_detail_payload(agency, window, rows), "fallback_from": failed, "source": usaspending.SOURCE}

        return await svc.swr(f"w:usasp:ag:{agency.upper()}:{window['end_date']}", USASP_TTL_S, fetch_detail)
    try:
        kind, words = usaspending.norm_query(text)
    except UsGovError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        if kind == "agency":
            rows, failed = await svc.router.call("usaspending", lambda p: p.usasp_agencies(window))
            data = usaspending.agency_payload(window, rows)
        else:
            out, failed = await svc.router.call("usaspending", lambda p: p.usasp_keyword(words, window))
            data = usaspending.keyword_payload(words, window, out["recipients"], out["awards"], out["notes"])
        return {"data": data, "fallback_from": failed, "source": usaspending.SOURCE}

    return await svc.swr(f"w:usasp:{kind}:{words.upper()}:{window['end_date']}", USASP_TTL_S, fetch)


async def fedreg_search(svc: Any, q: str) -> dict[str, Any]:
    try:
        type_code, words = fedreg.parse_query(q)
    except UsGovError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        out, failed = await svc.router.call("federal_register", lambda p: p.fedreg_search(type_code, words))
        return {"data": out, "fallback_from": failed, "source": fedreg.SOURCE}

    return await svc.swr(f"w:fedreg:{type_code}:{words.lower()}", FEDREG_TTL_S, fetch)


def _source(svc: Any, name: str) -> str:
    """The provider's own source label (it says DOC-SHAPED in fixture mode)."""
    return svc.router.providers[name].source


async def fec_view(svc: Any, q: str) -> dict[str, Any]:
    try:
        kind, text = fec.norm_query(q)
    except UsGovError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        try:
            if kind == "search":
                out, failed = await svc.router.call("openfec", lambda p: p.fec_search(text))
                data = fec.search_payload(text, out["candidates"], out["committees"], out["notes"])
            else:
                out, failed = await svc.router.call("openfec", lambda p: p.fec_entity(kind.upper(), text))
                data = fec.entity_payload(kind.upper(), text, out["name"], out["cycles"])
        except AllFailed as e:
            if e.kind == "not_found":  # the router's own text says NO DATA FOR SYMBOL, which is wrong here
                raise DataError("not_found", f"NO FEC {kind.upper()} WITH ID {text}") from e
            raise
        return {"data": data, "fallback_from": failed, "source": _source(svc, "openfec")}

    return await svc.swr(f"w:fec:{kind}:{text.upper()}", FEC_TTL_S, fetch)


async def congress_view(svc: Any, q: str) -> dict[str, Any]:
    try:
        kind, arg = congress.parse_query(q, date.today())
    except UsGovError as e:
        raise _bad(e) from e

    async def fetch() -> dict:
        try:
            if kind == "bill":
                session, typ, number = arg
                bill, failed = await svc.router.call("congress_gov", lambda p: p.cg_bill(session, typ, number))
                data = bill
            elif kind == "latest":
                rows, failed = await svc.router.call("congress_gov", lambda p: p.cg_list(congress.LATEST_SHOWN))
                data = congress.list_payload("LATEST", "", len(rows), rows)
            else:
                rows, failed = await svc.router.call("congress_gov", lambda p: p.cg_list(congress.LIST_LIMIT))
                data = congress.list_payload("TITLE FILTER", " ".join(arg), len(rows), congress.filter_words(rows, arg))
        except AllFailed as e:
            if e.kind == "not_found" and kind == "bill":
                raise DataError("not_found", f"NO BILL {congress.bill_ref(*arg)} IN CONGRESS.GOV") from e
            raise
        return {"data": data, "fallback_from": failed, "source": _source(svc, "congressgov")}

    key = f"w:congress:bill:{arg}" if kind == "bill" else f"w:congress:{kind}:{' '.join(arg) if arg else ''}"
    return await svc.swr(key, CONGRESS_TTL_S, fetch)
