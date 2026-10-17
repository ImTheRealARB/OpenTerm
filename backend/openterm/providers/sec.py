"""SEC EDGAR (data.sec.gov / www.sec.gov): XBRL company facts (FA), filings (FIL), Form 4 insider trades (OWN).

SEC fair access: declare a User-Agent with a contact (env SEC_USER_AGENT) and stay under 10 requests/s.
Without SEC_USER_AGENT a generic agent is sent; SEC may answer 403, and the error says how to fix it.
Parsing lives in sec_parse.py (pure, unit-tested).
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .. import __version__
from ..config import get_settings
from .base import Provider, ProviderError
from .sec_parse import form4_xml_url, parse_companyfacts, parse_form4, parse_submissions

FUNDAMENTALS = "fundamentals"
FILINGS = "filings"
INSIDERS = "insiders"
HOLDERS = "holders"

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
TICKERS_TTL_S = 86400.0
SUBS_MEMO_S = 120.0
FORM4_LIMIT = 20
US_ONLY = "SEC DATA COVERS US FILERS ONLY"
UA_HINT = "set SEC_USER_AGENT in .env, e.g. 'Your Name you@example.com'"
_PLACEHOLDER_UA = "contact@example.com"  # the pre-Phase-6 default; treated as unset


def default_user_agent() -> str:
    return f"OpenTerm/{__version__} (set SEC_USER_AGENT)"


def sec_ticker(symbol: str) -> str | None:
    """Yahoo-style symbol -> SEC ticker form, or None when the symbol cannot be a US filer.
    Class shares are BRK-B on SEC (BRK.B and BRK-B both map); exchange suffixes (.NS .L ...), indices,
    FX, futures and crypto pairs are not SEC filers."""
    s = symbol.strip().upper()
    if not s or s.startswith("^") or "=" in s:
        return None
    m = re.fullmatch(r"([A-Z][A-Z0-9]{0,6})(?:[.-]([A-Z]{1,2}))?", s)
    if not m:
        return None
    base, cls = m.groups()
    if cls and "." in s and len(cls) == 2:
        return None  # exchange suffix such as .NS .BO .HK .TO
    return f"{base}-{cls}" if cls else base


class AccessionStore(Protocol):
    """Parsed Form 4s by accession. Filings never change, so entries never expire."""

    async def get(self, accession: str) -> list[dict] | None: ...

    def put(self, accession: str, trades: list[dict]) -> None: ...


class SecProvider(Provider):
    name = "sec"
    label = "SEC EDGAR"
    capabilities = frozenset({FUNDAMENTALS, FILINGS, INSIDERS})
    markets = "US SEC filers only: XBRL financials (10-K/10-Q), filings index, Form 4 insider trades"
    rate = (8.0, 8)  # SEC fair access allows 10/s in total; stay under it
    timeout = 15.0  # company facts for large filers are 4-5 MB
    max_wait = 3.0  # OWN fetches up to 20 Form 4s at once; they queue on the bucket instead of failing

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        ua = (get_settings().sec_user_agent or "").strip()
        self.ua_set = bool(ua) and _PLACEHOLDER_UA not in ua
        self.user_agent = ua if self.ua_set else default_user_agent()
        self.headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        self.terms = "Public domain US government data, no key. Fair access: max 10 requests/s, declared User-Agent." + (
            "" if self.ua_set else f" USER-AGENT NOT SET: {UA_HINT}."
        )
        self._ciks: dict[str, int] = {}
        self._ciks_at = 0.0
        self._ciks_lock = asyncio.Lock()
        self._subs: dict[int, tuple[float, dict]] = {}

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities and (symbol is None or sec_ticker(symbol) is not None)

    async def _request(self, url, params, timeout):
        try:
            return await super()._request(url, params, timeout)
        except ProviderError as e:
            if str(e).startswith("403"):
                hint = UA_HINT if not self.ua_set else "SEC refused this User-Agent or rate"
                raise ProviderError("unavailable", f"403 from SEC: {hint}") from e
            raise

    async def _json(self, url: str) -> Any:
        return await self.get_json(url)

    async def cik(self, symbol: str) -> int:
        t = sec_ticker(symbol)
        if t is None:
            raise ProviderError("unsupported", US_ONLY)
        async with self._ciks_lock:
            if not self._ciks or time.time() - self._ciks_at > TICKERS_TTL_S:
                body = await self._json(TICKERS_URL)
                rows = body.values() if isinstance(body, dict) else []
                self._ciks = {str(r["ticker"]).upper(): int(r["cik_str"]) for r in rows if r.get("ticker")}
                self._ciks_at = time.time()
        cik = self._ciks.get(t) or self._ciks.get(t.replace("-", "."))
        if cik is None:
            raise ProviderError("not_found", f"no SEC filer with ticker {t}")
        return cik

    async def submissions(self, cik: int) -> dict:
        hit = self._subs.get(cik)
        if hit and time.time() - hit[0] < SUBS_MEMO_S:
            return hit[1]
        body = await self._json(SUBS_URL.format(cik=cik))
        if not isinstance(body, dict) or "filings" not in body:
            raise ProviderError("not_found", "no submissions")
        parsed = parse_submissions(body)
        self._subs[cik] = (time.time(), parsed)
        return parsed

    async def fundamentals(self, symbol: str) -> dict:
        cik = await self.cik(symbol)
        body = await self._json(FACTS_URL.format(cik=cik))
        try:
            out = parse_companyfacts(body if isinstance(body, dict) else {})
        except ValueError as e:
            raise ProviderError("not_found", str(e)) from e
        return {**out, "symbol": symbol, "cik": cik, "source": self.source, "as_of": self.now()}

    async def filings(self, symbol: str) -> dict:
        cik = await self.cik(symbol)
        return {**await self.submissions(cik), "symbol": symbol, "source": self.source, "as_of": self.now()}

    async def insiders(self, symbol: str, store: AccessionStore | None = None) -> dict:
        cik = await self.cik(symbol)
        subs = await self.submissions(cik)
        refs = [f for f in subs["filings"] if f["form"] in ("4", "4/A") and f["primary_doc"]][:FORM4_LIMIT]

        async def one(f: dict) -> list[dict]:
            if store is not None:
                hit = await store.get(f["accession"])
                if hit is not None:
                    return hit
            url = form4_xml_url(cik, f["accession"], f["primary_doc"])
            try:
                trades = parse_form4(await self.get_bytes(url), f["accession"], f["filed"], f["url"])
            except ValueError as e:
                raise ProviderError("unavailable", str(e)) from e
            if store is not None:
                store.put(f["accession"], trades)
            return trades

        results = await asyncio.gather(*(one(f) for f in refs), return_exceptions=True)
        trades, failed = [], []
        for f, r in zip(refs, results):
            if isinstance(r, BaseException):
                failed.append(f["accession"])
            else:
                trades.extend(r)
        if refs and len(failed) == len(refs):
            err = next(r for r in results if isinstance(r, BaseException))
            raise err if isinstance(err, ProviderError) else ProviderError("unavailable", str(err))
        trades.sort(key=lambda t: (t["date"] or "", t["filed"] or ""), reverse=True)
        return {
            "symbol": symbol, "cik": cik, "name": subs["name"], "trades": trades, "filings_read": len(refs) - len(failed),
            "failed": failed, "source": self.source, "as_of": self.now(),
        }

    async def probe(self) -> None:
        await self._json(SUBS_URL.format(cik=320193))


def store_from(get: Callable[[str], Awaitable[Any]], put: Callable[[str, Any], None], prefix: str = "f4:") -> AccessionStore:
    """Adapts the service cache (key/value with stored_at) into an AccessionStore."""

    class _Store:
        async def get(self, accession: str) -> list[dict] | None:
            entry = await get(prefix + accession)
            return entry[0] if entry is not None else None

        def put(self, accession: str, trades: list[dict]) -> None:
            put(prefix + accession, trades)

    return _Store()

