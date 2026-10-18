"""SEC N-PORT fund holdings (ETF, MEMB) and 13F-HR information tables (MGR), on the SEC EDGAR adapter's session, rate limit
and User-Agent. Parsing lives in research/fund_parse.py (pure, unit-tested)."""

from __future__ import annotations

import re
import time

from ..research import fund_parse as fp
from .base import ProviderError
from .sec import TICKERS_TTL_S, TICKERS_URL, SecProvider
from .sec_parse import archive_base

ETF_HOLDINGS = "etf_holdings"
MANAGER_13F = "manager_13f"
MF_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SERIES_ATOM = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series}&type=NPORT-P&dateb=&owner=include&count=5&output=atom"


class SecNportProvider(SecProvider):
    name = "sec_nport"
    label = "SEC N-PORT fund holdings"
    capabilities = frozenset({ETF_HOLDINGS})
    markets = "US-registered ETFs and funds: full portfolio holdings, quarterly with a 60-day public lag"
    timeout = 25.0  # large index funds file multi-megabyte XML

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._mf: tuple[float, dict[str, tuple[int, str]]] | None = None
        self._names: tuple[float, dict[str, list[str]]] | None = None

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities

    async def _series(self, symbol: str) -> tuple[int, str | None]:
        s = symbol.upper()
        if s in fp.UIT_CIKS:
            return fp.UIT_CIKS[s], None
        if self._mf is None or time.time() - self._mf[0] > TICKERS_TTL_S:
            body = await self._json(MF_URL)
            cols = body.get("fields") or []
            ci, si, yi = cols.index("cik"), cols.index("seriesId"), cols.index("symbol")
            self._mf = (time.time(), {str(r[yi]).upper(): (int(r[ci]), str(r[si])) for r in body.get("data") or []})
        hit = self._mf[1].get(s)
        if hit is None:
            raise ProviderError("not_found", f"{s} is not a fund ticker SEC lists")
        return hit

    async def _latest(self, cik: int, series: str | None) -> tuple[str, str | None]:
        if series is None:
            subs = await self.submissions(cik)
            for f in subs["filings"]:
                if f["form"] == "NPORT-P":
                    return f["accession"], f["filed"]
            raise ProviderError("not_found", "no NPORT-P filing in the recent filings feed")
        text = (await self.get_bytes(SERIES_ATOM.format(series=series))).decode("utf-8", "replace")
        m = re.search(r"<accession-number>([\d-]+)</accession-number>", text)
        if not m:
            raise ProviderError("not_found", f"no NPORT-P filing for series {series}")
        d = re.search(r"<filing-date>([\d-]+)</filing-date>", text)
        return m.group(1), d.group(1) if d else None

    async def _name_index(self) -> dict[str, list[str]]:
        if self._names is None or time.time() - self._names[0] > TICKERS_TTL_S:
            self._names = (time.time(), fp.name_index(await self._json(TICKERS_URL)))
        return self._names[1]

    async def holdings(self, symbol: str) -> dict:
        cik, series = await self._series(symbol)
        acc, filed = await self._latest(cik, series)
        xml = await self.get_bytes(f"{archive_base(cik, acc)}/primary_doc.xml")
        try:
            out = fp.parse_nport(xml)
        except ValueError as e:
            raise ProviderError("unavailable", str(e)) from e
        try:
            fp.match_tickers(out["holdings"], await self._name_index())
        except ProviderError:
            pass  # tickers are a convenience; the holdings stand without them
        return {**out, "symbol": symbol, "accession": acc, "filed": filed, "source": self.source, "as_of": self.now()}


class Sec13fProvider(SecProvider):
    name = "sec_13f"
    label = "SEC 13F-HR holdings reports"
    capabilities = frozenset({MANAGER_13F})
    markets = "US institutional managers above $100M: long equity positions, quarterly, filed up to 45 days after quarter end"
    timeout = 25.0

    def supports(self, capability: str, symbol: str | None = None) -> bool:
        return capability in self.capabilities

    async def manager(self, key: str) -> dict:
        cik = fp.manager_cik(key)
        subs = await self.submissions(cik)
        filings = [f for f in subs["filings"] if f["form"] == "13F-HR"][:2]
        if not filings:
            raise ProviderError("not_found", f"no 13F-HR in the recent filings of CIK {cik}")
        quarters = []
        for f in filings:
            base = archive_base(cik, f["accession"])
            index = await self._json(f"{base}/index.json")
            names = [i["name"] for i in (index.get("directory") or {}).get("item") or [] if i["name"].lower().endswith(".xml")]
            table = next((n for n in names if n != "primary_doc.xml"), None)
            if table is None:
                raise ProviderError("unavailable", f"no information table in {f['accession']}")
            try:
                positions = fp.parse_13f_table(await self.get_bytes(f"{base}/{table}"), f["filed"])
                meta = fp.parse_13f_primary(await self.get_bytes(f"{base}/primary_doc.xml"))
            except ValueError as e:
                raise ProviderError("unavailable", str(e)) from e
            quarters.append({**meta, "positions": len(positions), "filed": f["filed"], "accession": f["accession"],
                             "url": f["url"], "table": positions})
        return {"cik": cik, "name": subs["name"], "now": quarters[0], "before": quarters[1] if len(quarters) > 1 else None,
                "source": self.source, "as_of": self.now()}
