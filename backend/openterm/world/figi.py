"""SECF identifier lookup: classify the words of a query, ask OpenFIGI only for those with a good check digit, merge in order."""

from __future__ import annotations

import time
from typing import Any

from ..errors import DataError
from ..secf.ids import classify, split_query

MAX_IDS = 25
TTL_S = 86400.0
NOTE = "OPENFIGI: IDENTIFIER MAPPING, NOT A PRICE SOURCE. EXCHANGE CODES ARE OPENFIGI'S OWN."


async def lookup(svc: Any, q: str) -> dict[str, Any]:
    words = split_query(q)
    if not words:
        raise DataError("bad_request", "GIVE AN ISIN, CUSIP, SEDOL OR FIGI (FIGI:<ID>)")
    if len(words) > MAX_IDS:
        raise DataError("bad_request", f"AT MOST {MAX_IDS} IDENTIFIERS A LOOKUP")
    idents = []
    for w in words:
        ident = classify(w)
        if ident is None:
            raise DataError("bad_request", f"NOT AN ISIN, CUSIP, SEDOL OR FIGI: {w[:24]}")
        idents.append(ident)
    good = [i for i in idents if i.valid]
    mapped: dict[tuple[str, str], dict[str, Any]] = {}
    env: dict[str, Any] = {"source": "openfigi (no request sent)", "as_of": time.time(), "age_s": 0.0, "stale": False, "fallback_from": []}
    if good:
        async def fetch() -> dict:
            out, failed = await svc.router.call("figi", lambda p: p.figi(good))
            return {"data": out, "fallback_from": failed, "source": out["source"]}

        env = await svc.swr("w:figi:" + ",".join(f"{i.kind}:{i.value}" for i in good), TTL_S, fetch)
        mapped = {(it["kind"], it["id"]): it for it in env["data"]["items"]}
    items = [
        mapped.get((i.kind, i.value)) if i.valid
        else {"kind": i.kind, "id": i.value, "status": "BAD CHECK DIGIT", "message": f"{i.kind} CHECK DIGIT FAILS: TYPO?", "listings": []}
        for i in idents
    ]
    return {**env, "data": {"items": items, "note": NOTE}}
