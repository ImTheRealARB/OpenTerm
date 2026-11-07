"""UKCO: UK Companies House lookup. A company number gives its profile, officers and filings; any other text is a name search.

Thin layer over the `companies_house` provider (providers/companies_house.py): it decides which of the two calls the text asks for,
caches the answer, and adds the label that says what the data is. Without COMPANIES_HOUSE_KEY the provider raises `key_required`
and the route answers 424 `KEY REQUIRED: set COMPANIES_HOUSE_KEY in APIKEYS`.
"""

from __future__ import annotations

from typing import Any

from ..errors import DataError
from ..providers import companies_house_parse as chp
from ..router import AllFailed

COMPANY_TTL_S = 3600.0  # a register entry changes when the company files something: an hour is fresh enough
SEARCH_TTL_S = 600.0
NOTE = "UK COMPANIES HOUSE REGISTER, AS FILED BY EACH COMPANY (NOT CHECKED BY OPENTERM). OFFICERS' BIRTH DATES AND HOME ADDRESSES ARE NOT SHOWN."


async def ukco(svc: Any, q: str) -> dict[str, Any]:
    text = " ".join((q or "").split())
    if len(text) < 2:
        raise DataError("bad_request", "GIVE A COMPANY NAME (2+ LETTERS) OR AN 8 CHARACTER COMPANY NUMBER")
    number = chp.as_number(text)

    async def fetch() -> dict:
        try:
            if number:
                out, failed = await svc.router.call("companies_house", lambda p: p.ch_company(number))
                data = {"mode": "COMPANY", "number": number, **out}
            else:
                out, failed = await svc.router.call("companies_house", lambda p: p.ch_search(text))
                data = {"mode": "SEARCH", "query": text, **out}
        except AllFailed as e:
            # The router's generic text for "not found" is NO DATA FOR SYMBOL, which is wrong for a company register. Say what was asked.
            if e.kind == "not_found":
                raise DataError("not_found", f"NO COMPANY WITH NUMBER {number}" if number else f"NO COMPANY NAME MATCHES {text.upper()[:40]}") from e
            raise
        return {"data": {**data, "note": NOTE}, "fallback_from": failed, "source": out["source"]}

    key = f"w:ukco:{number}" if number else f"w:ukco:q:{text.upper()}"
    return await svc.swr(key, COMPANY_TTL_S if number else SEARCH_TTL_S, fetch)
