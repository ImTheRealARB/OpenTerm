"""SEC EDGAR, the Phase 29 side: full-text search (FTS, MA, BIO), the enforcement RSS feeds (LEGAL) and the ticker-by-exchange file (RELS, ESG, LEGAL).

It is a subclass of `SecProvider` so it sends the same declared User-Agent (env SEC_USER_AGENT), gets the same 403 hint and stays a separate source
on SOURCES (its own rate bucket: SEC's fair-access limit is 10 requests a second in total, and this adapter makes a handful of calls per command).
Hits from the full-text search are the SEC's own words about its own data: INFO only, never a price.

Capabilities (each one is a line in `hierarchy.DEFAULT_ORDER`):
  sec_fts        efts.sec.gov full-text search: `fts(params)`
  sec_rss        www.sec.gov enforcement feeds: `litigation()`
  sec_tickers_x  company_tickers_exchange.json: `issuer(symbol)`, `related(symbol)`
  sec_doc        one SEC filing document read as text (MA deal values): `document_text(url)`
  sec_sic        the SIC code list page and the EDGAR company browser filtered by one SIC code (IBQ BY=SIC): `sic_table()`, `sic_members(code)`
"""

from __future__ import annotations

import time
from typing import Any

from ..filings import fts as F
from ..filings import legal as L
from ..filings import ma_value as MV
from ..filings import rels as R
from ..fund import sic as S
from .base import ProviderError
from .sec import SecProvider, sec_ticker

FTS = "sec_fts"
RSS = "sec_rss"
TICKERS_X = "sec_tickers_x"
SIC = "sec_sic"
DOC = "sec_doc"
SIC_LIST_URL = "https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list"
SIC_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SIC_PAGE = 100  # the most entries the company browser returns per page
SIC_MAX_PAGES = 30  # 3,000 companies per code; the biggest codes (drugs, software, blank checks) stay under that
TICKERS_X_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FEEDS = (
    ("LITIGATION", "https://www.sec.gov/enforcement-litigation/litigation-releases/rss"),
    ("ADMIN", "https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss"),
)
TICKERS_X_TTL_S = 86400.0


class SecFilingsProvider(SecProvider):
    name = "sec_filings"
    label = "SEC EDGAR full-text search and enforcement feeds"
    capabilities = frozenset({FTS, RSS, TICKERS_X, SIC, DOC})
    markets = "US SEC filings text search (2001 on), SEC litigation releases and administrative proceedings (latest 25 each), ticker-by-exchange file"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._xrows: list[dict[str, Any]] = []
        self._xat = 0.0

    async def fts(self, params: dict[str, str]) -> dict[str, Any]:
        """One search page (up to 100 hits, newest first): {total, hits, source, as_of}. The SEC answers an odd HTTP 500 now and then: it
        surfaces as PROVIDER DOWN and the same command works on retry (nothing is retried silently)."""
        body = await self.get_json(F.ENDPOINT, params)
        try:
            out = F.parse_fts(body)
        except ValueError as e:
            raise ProviderError("unavailable", str(e)) from e
        return {**out, "source": self.source, "as_of": self.now()}

    async def litigation(self) -> dict[str, Any]:
        """Both enforcement feeds, parsed: {items: [{kind, title, date, ref, url}], source, as_of}."""
        items: list[dict[str, Any]] = []
        for kind, url in FEEDS:
            try:
                items.extend(L.parse_rss(await self.get_bytes(url), kind))
            except ValueError as e:
                raise ProviderError("unavailable", f"{kind}: {e}") from e
        return {"items": items, "source": self.source, "as_of": self.now()}

    async def _exchange_rows(self) -> list[dict[str, Any]]:
        if not self._xrows or time.time() - self._xat > TICKERS_X_TTL_S:
            try:
                self._xrows = R.parse_exchange_file(await self.get_json(TICKERS_X_URL))
            except ValueError as e:
                raise ProviderError("unavailable", str(e)) from e
            self._xat = time.time()
        return self._xrows

    async def issuer(self, symbol: str) -> dict[str, Any]:
        """{cik, name, ticker} for a US ticker, read from the exchange file (so it also knows each extra share class)."""
        want = sec_ticker(symbol)
        if want is None:
            raise ProviderError("unsupported", "SEC DATA COVERS US FILERS ONLY")
        for row in await self._exchange_rows():
            if str(row["ticker"]).upper() in (want, want.replace("-", ".")):
                return {"cik": int(row["cik"]), "name": row["name"], "ticker": row["ticker"], "source": self.source, "as_of": self.now()}
        raise ProviderError("not_found", f"no SEC filer with ticker {want}")

    async def tickers_for(self, ciks: list[int]) -> dict[int, str]:
        """{cik: first listed ticker} for the CIKs the file knows (an owner or an unlisted filer is simply absent)."""
        want = set(ciks)
        out: dict[int, str] = {}
        for row in await self._exchange_rows():
            cik = int(row["cik"])
            if cik in want and cik not in out:
                out[cik] = row["ticker"]
        return out

    async def related(self, symbol: str) -> dict[str, Any]:
        """The issuer plus every ticker filed under its CIK."""
        who = await self.issuer(symbol)
        return {**who, "rows": R.siblings(await self._exchange_rows(), who["cik"])}

    async def document_text(self, url: str) -> dict[str, Any]:
        """One filing document (`www.sec.gov/Archives/edgar/data/...` only) as plain text, cut at `MAV.MAX_TEXT` characters: {text, url, source, as_of}."""
        try:
            MV.check_url(url)
        except ValueError as e:
            raise ProviderError("bad_request", str(e)) from e
        return {"text": MV.to_text(await self.get_bytes(url)), "url": url, "source": self.source, "as_of": self.now()}

    async def sic_table(self) -> dict[int, dict[str, str]]:
        """{SIC code: {title, office}} from the SEC's own list page."""
        try:
            return S.parse_sic_table((await self.get_bytes(SIC_LIST_URL)).decode("utf-8", "replace"))
        except ValueError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def sic_members(self, code: int) -> dict[str, Any]:
        """Every company the EDGAR browser lists under one SIC code (10-K filers, alphabetical): {ciks, truncated, source, as_of}.
        Pages of 100 are read until a short page; more than SIC_MAX_PAGES pages sets `truncated` (said on screen, never hidden)."""
        found: dict[int, str] = {}
        truncated = False
        for page in range(SIC_MAX_PAGES + 1):
            if page == SIC_MAX_PAGES:
                truncated = True
                break
            params = {"action": "getcompany", "SIC": str(code), "type": "10-K", "owner": "exclude", "output": "atom",
                      "count": str(SIC_PAGE), "start": str(page * SIC_PAGE)}
            try:
                rows = S.parse_atom(await self.get_bytes(SIC_BROWSE_URL, params))
            except ValueError as e:
                raise ProviderError("unavailable", str(e)) from e
            found.update({r["cik"]: r["name"] for r in rows if r["sic"] == code})
            if len(rows) < SIC_PAGE:
                break
        return {"code": code, "ciks": sorted(found), "truncated": truncated, "source": self.source, "as_of": self.now()}

    async def probe(self) -> None:
        await self.fts(F.build_params(forms="10-K", start="2024-01-01", end="2024-01-31"))
