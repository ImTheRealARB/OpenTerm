"""SECF mutual fund rows: scheme lookup in AMFI's NAVAll.txt by name, ISIN or scheme code. The whole file is parsed once and cached for six hours
(`w:mfnav`); each search then filters the cached table in memory."""

from __future__ import annotations

import re
from typing import Any

from ..errors import DataError
from .india import search_amfi

TTL_S = 21600.0
LIMIT = 50
NOTE = "AMFI NAV: END-OF-DAY NET ASSET VALUE PER UNIT, PUBLISHED BY AMFI IN THE EVENING. NOT A MARKET PRICE."


async def lookup(svc: Any, q: str) -> dict[str, Any]:
    query = " ".join((q or "").split())
    if len(query) < 3 and not re.fullmatch(r"\d{4,7}", query):
        raise DataError("bad_request", "GIVE AT LEAST 3 LETTERS OF A FUND NAME, AN ISIN (INF...) OR A SCHEME CODE")

    async def fetch() -> dict:
        out, failed = await svc.router.call("mfnav", lambda p: p.navall())
        return {"data": out, "fallback_from": failed, "source": out["source"]}

    env = await svc.swr("w:mfnav", TTL_S, fetch)
    table = env["data"]
    items, total = search_amfi(table, query, LIMIT)
    return {**env, "data": {"query": query, "items": items, "total": total, "shown": len(items), "nav_date": table["nav_date"],
                            "schemes": len(table["rows"]), "note": NOTE}}
