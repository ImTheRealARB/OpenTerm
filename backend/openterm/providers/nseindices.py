"""NSE Indices (keyless): the constituent lists of NIFTY 50 and NIFTY 500, for SCAN and MRR universes (Phase 27).

NSE Indices publishes each index's members as a small CSV (Company Name, Industry, Symbol, Series, ISIN Code). Its terms need a
licence to REDISTRIBUTE the lists, so OpenTerm downloads them on the user's own computer when a scan asks and never ships
them: the test fixtures are doc-shaped (invented rows, labelled NOT A RECORDING). The CSV has no index weights, so NIFTY
movers show returns without contributions. Parsing lives in `scanner/universe.py` (`nifty_members`).
"""

from __future__ import annotations

from typing import ClassVar

from .base import Provider, ProviderError

NIFTY_LIST = "nifty_constituents"
BASE = "https://www.niftyindices.com/IndexConstituent/"
FILES = ("ind_nifty50list.csv", "ind_nifty500list.csv")


class NseIndicesProvider(Provider):
    name = "nseindices"
    label = "NSE Indices (NIFTY constituent lists)"
    capabilities = frozenset({NIFTY_LIST})
    markets = "Members of NIFTY 50 and NIFTY 500 (symbols only, no weights)"
    terms = ("Free public CSV files from niftyindices.com, fetched on this computer only; redistribution needs NSE Indices' "
             "licence, so the lists are never shipped with OpenTerm.")
    rate = (1.0, 2)
    max_wait = 5.0
    timeout = 20.0
    # A plain browser-like agent: the site answers 403 to some library defaults.
    headers: ClassVar[dict[str, str]] = {"User-Agent": "Mozilla/5.0 (OpenTerm)", "Accept": "text/csv,*/*"}

    async def constituents(self, file: str) -> str:
        """The CSV text of one list (`ind_nifty50list.csv` or `ind_nifty500list.csv`)."""
        if file not in FILES:
            raise ProviderError("bad_request", f"UNKNOWN NSE INDICES LIST {file[:40]}")
        raw = await self.get_bytes(BASE + file)
        text = raw.decode("utf-8-sig", errors="replace")
        if "symbol" not in text[:400].lower():
            raise ProviderError("unavailable", "NSE INDICES DID NOT SEND A CONSTITUENT CSV (A BOT CHECK OR A CHANGED PAGE)")
        return text

    async def probe(self) -> None:
        await self.constituents(FILES[0])
