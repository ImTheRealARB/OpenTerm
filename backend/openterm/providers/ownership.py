"""Yahoo quoteSummary ownership modules: institutional + fund holders (HDS), insider trades (OWN fallback).

A subclass of YahooProvider so it reuses the cookie + crumb flow, under its own name (`yahoo_own`) so its health
shows separately on SOURCES. Holder lists are Yahoo's aggregation of 13F filings (quarterly, delayed ~45 days).
"""

import re
from typing import Any

from .base import ProviderError
from .sec import HOLDERS, INSIDERS
from .yahoo import SEARCH_BASE, YahooProvider, _raw

# Yahoo's transaction text -> Form 4 code. Unknown wording keeps an empty code and shows the text.
_TEXT_CODES = (
    ("sale", "S"), ("purchase", "P"), ("buy", "P"), ("gift", "G"), ("award", "A"), ("grant", "A"),
    ("exercise", "M"), ("conversion", "M"), ("tax", "F"), ("withh", "F"),
)


def _date(v: Any) -> str | None:
    return v.get("fmt") if isinstance(v, dict) else None


def holders_from_summary(symbol: str, r: dict, source: str, as_of: float) -> dict:
    mh = r.get("majorHoldersBreakdown") or {}

    def rows(module: str) -> list[dict]:
        out = []
        for h in (r.get(module) or {}).get("ownershipList") or []:
            out.append({
                "holder": h.get("organization") or "",
                "pct_held": _raw(h, "pctHeld"),
                "shares": _raw(h, "position"),
                "value": _raw(h, "value"),
                "pct_change": _raw(h, "pctChange"),
                "report_date": _date(h.get("reportDate")),
            })
        return out

    out = {
        "symbol": symbol,
        "breakdown": {
            "insiders_pct": _raw(mh, "insidersPercentHeld"),
            "institutions_pct": _raw(mh, "institutionsPercentHeld"),
            "institutions_float_pct": _raw(mh, "institutionsFloatPercentHeld"),
            "institutions_count": _raw(mh, "institutionsCount"),
        },
        "institutions": rows("institutionOwnership"),
        "funds": rows("fundOwnership"),
        "source": source,
        "as_of": as_of,
    }
    if not out["institutions"] and not out["funds"] and all(v is None for v in out["breakdown"].values()):
        raise ProviderError("not_found", "no holder data")
    return out


def insiders_from_summary(symbol: str, r: dict, source: str, as_of: float) -> dict:
    trades = []
    for t in (r.get("insiderTransactions") or {}).get("transactions") or []:
        text = t.get("transactionText") or ""
        low = text.lower()
        code = next((c for k, c in _TEXT_CODES if k in low), "")
        shares, value = _raw(t, "shares"), _raw(t, "value")
        m = re.search(r"price ([\d.]+)", low)
        price = float(m.group(1)) if m else (value / shares if value and shares else None)
        trades.append({
            "owner": t.get("filerName") or "", "owner_cik": None, "relation": t.get("filerRelation") or "",
            "date": _date(t.get("startDate")), "code": code, "code_text": text or code,
            "acq_disp": "D" if code in ("S", "F", "G") else ("A" if code in ("P", "A", "M") else None),
            "shares": shares, "price": price or None, "value": value or None, "owned_after": None,
            "direct": t.get("ownership"), "security": None, "derivative": False,
            "accession": None, "filed": None, "url": None,
        })
    if not trades:
        raise ProviderError("not_found", "no insider transactions")
    trades.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"symbol": symbol, "cik": None, "name": None, "trades": trades, "filings_read": None, "failed": [],
            "source": source, "as_of": as_of}


class YahooOwnProvider(YahooProvider):
    name = "yahoo_own"
    label = "Yahoo Finance ownership (unofficial)"
    capabilities = frozenset({HOLDERS, INSIDERS})
    markets = "Institutional and fund holders (13F-derived), insider trades; mostly US listings"
    terms = "Unofficial quoteSummary modules; personal use. Holder lists come from quarterly 13F filings."

    async def _summary(self, symbol: str, modules: str) -> dict:
        for attempt in range(2):
            crumb = await self._get_crumb(refresh=attempt > 0)
            try:
                body = await self.get_json(
                    f"{SEARCH_BASE}/v10/finance/quoteSummary/{symbol}", {"modules": modules, "crumb": crumb}
                )
                break
            except ProviderError as e:
                if attempt == 0 and "401" in str(e):
                    continue  # crumb expired: fetch a new one once
                raise
        result = (body.get("quoteSummary") or {}).get("result")
        if not result:
            raise ProviderError("not_found", "no summary")
        return result[0]

    async def holders(self, symbol: str) -> dict:
        r = await self._summary(symbol, "institutionOwnership,fundOwnership,majorHoldersBreakdown")
        return holders_from_summary(symbol, r, self.source, self.now())

    async def insiders(self, symbol: str, store: Any = None) -> dict:
        r = await self._summary(symbol, "insiderTransactions")
        return insiders_from_summary(symbol, r, self.source, self.now())
