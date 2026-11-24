"""Phase 30 sources (macro, rates and commodities depth). Thin adapters: fetch, hand the bytes to `macrod/parse.py`, map trouble to
`ProviderError`. Keyless unless marked. The URL builders are module functions so scripts/record_phase30.py records exactly what the
adapters ask for.

  nyfed       MMR    NY Fed markets API: SOFR, TGCR, BGCR (secured), EFFR, OBFR (unsecured)
  ecb_estr    MMR    ECB data portal: euro short-term rate
  boe_sonia   MMR    Bank of England IADB: SONIA
  atlfed      NOWC   Atlanta Fed GDPNow workbook (about 11 MB: cached for hours)
  philfed     ECFC   Philadelphia Fed Survey of Professional Forecasters median workbooks
  imf_dm      ECFC   IMF DataMapper (World Economic Outlook projections)
  oecd_eo     ECFC   OECD Economic Outlook (SDMX CSV)
  fed_web     FOMC   federalreserve.gov statement pages
  td_secs     TSYS   TreasuryDirect securities (auctioned and upcoming)
  wasde       AGRI   USDA WASDE via the Cornell library copy (usda.gov refused automated requests when checked)
  eia         NRGF   EIA API v2 (free key EIA_API_KEY; doc-shaped fixture)
  nass        AGRI   USDA NASS QuickStats (free key NASS_API_KEY; doc-shaped fixture)
WPE uses the Yahoo fund modules through YahooFundsProvider (providers/etf.py), WCRS uses Frankfurter (providers/frankfurter.py).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from ..macrod import parse as P
from .base import Provider, ProviderError
from .keyed import KeyedProvider

UA = "OpenTerm/1.0 (personal research)"

NYFED_BASE = "https://markets.newyorkfed.org/api/rates"
NYFED_TYPES = (("secured", "sofr"), ("secured", "tgcr"), ("secured", "bgcr"), ("unsecured", "effr"), ("unsecured", "obfr"))
ESTR_URL = "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT"
BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
GDPNOW_URL = "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/gdpnow/GDPTrackingModelDataAndForecasts.xlsx"
SPF_BASE = "https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/survey-of-professional-forecasters/data-files/files/"
IMF_DM = "https://www.imf.org/external/datamapper/api/v1"
OECD_EO = "https://sdmx.oecd.org/public/rest/data/OECD.ECO.MAD,DSD_EO@DF_EO,"
FED_PR = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{d}a.htm"
TD_BASE = "https://www.treasurydirect.gov/TA_WS/securities"
WASDE_PAGE = "https://usda.library.cornell.edu/concern/publications/3t945q76s"
EIA_SERIES = "https://api.eia.gov/v2/seriesid/{sid}"
NASS_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

RATE_DAYS = 60  # observations per money-market rate (about three months of business days)


def nyfed_url(group: str, kind: str, n: int = RATE_DAYS) -> str:
    return f"{NYFED_BASE}/{group}/{kind}/last/{n}.json"


def boe_params(code: str, days: int = 100) -> dict[str, str]:
    start = (datetime.now(UTC).date() - timedelta(days=days)).strftime("%d/%b/%Y")
    return {"csv.x": "yes", "Datefrom": start, "Dateto": "now", "SeriesCodes": code, "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N"}


def imf_url(indicator: str, countries: tuple[str, ...]) -> str:
    return f"{IMF_DM}/{indicator}/{'/'.join(countries)}"


def oecd_url(countries: tuple[str, ...], measures: tuple[str, ...]) -> str:
    return f"{OECD_EO}/{'+'.join(countries)}.{'+'.join(measures)}.A"


class _Base(Provider):
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA}
    rate = (2.0, 6)
    max_wait = 4.0
    timeout = 30.0

    def _text(self, raw: bytes) -> str:
        return raw.decode("utf-8-sig", "replace")

    def _parsed(self, fn, *a):
        try:
            return fn(*a)
        except P.ParseError as e:
            raise ProviderError("unavailable", str(e)) from e


class NyFedProvider(_Base):
    name = "nyfed"
    label = "Federal Reserve Bank of New York reference rates"
    capabilities = frozenset({"nyfed_rates"})
    markets = "SOFR, TGCR, BGCR (secured overnight), EFFR, OBFR (unsecured overnight), with percentiles and volumes"
    terms = "Public API, no key. Federal Reserve Bank of New York; cite the bank."

    async def nyfed_rates(self) -> dict:
        got = await asyncio.gather(*(self.get_json(nyfed_url(g, k)) for g, k in NYFED_TYPES), return_exceptions=True)
        out, failed = {}, []
        for (_, k), g in zip(NYFED_TYPES, got, strict=True):
            if isinstance(g, ProviderError):
                failed.append(f"{k.upper()} ({g.kind})")
            elif isinstance(g, BaseException):
                raise g
            else:
                out[k.upper()] = self._parsed(P.nyfed, g)
        if not out:
            raise ProviderError("unavailable", "NO NY FED RATE ANSWERED: " + ", ".join(failed))
        return {"rates": out, "failed": failed, "source": self.source}

    async def probe(self) -> None:
        await self.get_json(nyfed_url("secured", "sofr", 1))


class EcbEstrProvider(_Base):
    name = "ecb_estr"
    label = "ECB euro short-term rate (ESTR)"
    capabilities = frozenset({"estr"})
    markets = "Euro short-term rate, daily"
    terms = "ECB data portal, no key. Source: European Central Bank."

    async def estr(self) -> dict:
        raw = await self.get_bytes(ESTR_URL, {"format": "csvdata", "lastNObservations": str(RATE_DAYS)})
        return {"points": self._parsed(P.ecb_csv, self._text(raw)), "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes(ESTR_URL, {"format": "csvdata", "lastNObservations": "1"})


class BoeSoniaProvider(_Base):
    name = "boe_sonia"
    label = "Bank of England SONIA (IADB)"
    capabilities = frozenset({"sonia"})
    markets = "Sterling overnight index average, daily"
    terms = "Bank of England Interactive Database, no key. Source: Bank of England."

    async def sonia(self) -> dict:
        raw = await self.get_bytes(BOE_URL, boe_params("IUDSOIA"))
        return {"points": self._parsed(P.boe_csv, self._text(raw), "IUDSOIA"), "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes(BOE_URL, boe_params("IUDSOIA", 10))


class AtlFedProvider(_Base):
    name = "atlfed"
    label = "Federal Reserve Bank of Atlanta GDPNow"
    capabilities = frozenset({"gdpnow"})
    markets = "GDPNow nowcast of US real GDP growth: the current quarter's path by release, past quarters' first and final nowcasts"
    terms = "Public workbook, no key (about 11 MB). GDPNow is a model estimate, not an official forecast of the Atlanta Fed."
    timeout = 90.0
    rate = (0.2, 2)

    async def gdpnow(self) -> dict:
        data = await self.get_bytes(GDPNOW_URL)
        return {**self._parsed(P.gdpnow, data), "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes("https://www.atlantafed.org/research-and-data/data/gdpnow")


class PhilFedProvider(_Base):
    name = "philfed"
    label = "Philadelphia Fed Survey of Professional Forecasters"
    capabilities = frozenset({"spf"})
    markets = "Median forecasts of US real GDP growth, CPI inflation, unemployment and the 10-year Treasury yield (quarterly survey)"
    terms = "Public files, no key. Source: Federal Reserve Bank of Philadelphia."

    async def spf(self) -> dict:
        keys = list(P.SPF_FILES)
        got = await asyncio.gather(*(self.get_bytes(SPF_BASE + P.SPF_FILES[k][0]) for k in keys), return_exceptions=True)
        out, failed = {}, []
        for k, g in zip(keys, got, strict=True):
            if isinstance(g, ProviderError):
                failed.append(f"{k} ({g.kind})")
            elif isinstance(g, BaseException):
                raise g
            else:
                out[k] = self._parsed(P.spf, g)
        if not out:
            raise ProviderError("unavailable", "NO SPF FILE ANSWERED: " + ", ".join(failed))
        return {"vars": out, "failed": failed, "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes(SPF_BASE + P.SPF_FILES["RGDP"][0])


class ImfDmProvider(_Base):
    name = "imf_dm"
    label = "IMF DataMapper (World Economic Outlook)"
    capabilities = frozenset({"imf_weo"})
    markets = "WEO real GDP growth, inflation and unemployment by country, history and IMF projections"
    terms = "Public API, no key. Source: International Monetary Fund, World Economic Outlook."
    timeout = 40.0

    async def imf_weo(self, indicators: tuple[str, ...], countries: tuple[str, ...]) -> dict:
        got = await asyncio.gather(*(self.get_json(imf_url(i, countries)) for i in indicators))
        return {"values": {i: self._parsed(P.imf_datamapper, g, i) for i, g in zip(indicators, got, strict=True)}, "source": self.source}

    async def probe(self) -> None:
        await self.get_json(imf_url("NGDP_RPCH", ("USA",)))


class OecdEoProvider(_Base):
    name = "oecd_eo"
    label = "OECD Economic Outlook (SDMX)"
    capabilities = frozenset({"oecd_eo"})
    markets = "OECD Economic Outlook projections: real GDP growth, CPI inflation, unemployment, long-term rate"
    terms = "OECD data API, no key; OECD terms (attribution). Source: OECD Economic Outlook."
    timeout = 40.0

    async def oecd_eo(self, countries: tuple[str, ...], measures: tuple[str, ...], start: int) -> dict:
        raw = await self.get_bytes(oecd_url(countries, measures), {"startPeriod": str(start), "format": "csvfile"})
        return {"values": self._parsed(P.oecd_csv, self._text(raw)), "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes(oecd_url(("USA",), ("UNR",)), {"startPeriod": "2025", "format": "csvfile"})


class FedWebProvider(_Base):
    name = "fed_web"
    label = "federalreserve.gov FOMC statements"
    capabilities = frozenset({"fomc_statement"})
    markets = "FOMC post-meeting statements (press release pages)"
    terms = "Public pages, no key. Source: Board of Governors of the Federal Reserve System."
    rate = (1.0, 3)

    async def fomc_statement(self, day: str) -> dict:
        """`day` is the decision date YYYY-MM-DD."""
        url = FED_PR.format(d=day.replace("-", ""))
        page = self._text(await self.get_bytes(url))
        return {"date": day, "url": url, "paragraphs": self._parsed(P.fomc_statement, page), "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")


class TdSecuritiesProvider(_Base):
    name = "td_secs"
    label = "TreasuryDirect securities (auctioned and upcoming)"
    capabilities = frozenset({"tsy_securities"})
    markets = "US Treasury bills, notes, bonds, TIPS and FRNs: CUSIP, coupon, maturity, auction results"
    terms = "Public API, no key. Source: US Department of the Treasury, Bureau of the Fiscal Service."

    async def tsy_securities(self, days: int) -> dict:
        done, up = await asyncio.gather(self.get_json(f"{TD_BASE}/auctioned", {"format": "json", "days": str(days)}),
                                        self.get_json(f"{TD_BASE}/upcoming", {"format": "json"}))
        return {"auctioned": self._parsed(P.td_securities, done), "upcoming": self._parsed(P.td_securities, up), "source": self.source}

    async def probe(self) -> None:
        await self.get_json(f"{TD_BASE}/upcoming", {"format": "json"})


class WasdeProvider(_Base):
    name = "wasde"
    label = "USDA WASDE (Cornell library copy)"
    capabilities = frozenset({"wasde"})
    markets = "World Agricultural Supply and Demand Estimates: US wheat, corn and soybean supply and use (monthly)"
    terms = "Public files, no key. Source: USDA World Agricultural Outlook Board, via Cornell University's Mann Library archive."
    timeout = 60.0
    rate = (0.5, 2)

    async def wasde(self) -> dict:
        page = self._text(await self.get_bytes(WASDE_PAGE, {"locale": "en"}))
        links = self._parsed(P.wasde_links, page)
        latest = next((r for r in links if "xml" in r), None)
        if latest is None:
            raise ProviderError("not_found", "NO WASDE XML FILE LISTED")
        xml = self._text(await self.get_bytes(latest["xml"]))
        return {**self._parsed(P.wasde, xml), "links": links[:6], "file": latest["xml"], "source": self.source}

    async def probe(self) -> None:
        await self.get_bytes(WASDE_PAGE, {"locale": "en"})


class EiaProvider(KeyedProvider):
    """EIA API v2, free key. DOC-SHAPED: written from the API v2 documentation (the `seriesid` route keeps the old series ids) and never
    run against a live key; the fixtures are `eia_docshape_*` (NOT A RECORDING). Record a real answer with the first key."""
    name = "eia"
    label = "US Energy Information Administration API v2 (free key)"
    capabilities = frozenset({"eia_series"})
    markets = "Weekly petroleum status report (crude, Cushing, gasoline, distillate, refinery utilisation, SPR) and weekly gas storage"
    terms = "Free key (EIA_API_KEY). US government data; the key goes in the query string, so it is redacted from every log line."
    key_name = "EIA_API_KEY"
    hide_without_key = False
    msg_refused = "EIA refused the key ({code})"
    rate = (3.0, 6)
    max_wait = 4.0
    timeout = 30.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.fixture:
            self.source = "eia (doc-shaped fixture, NOT A RECORDING)"

    def auth_params(self) -> dict[str, str]:
        return {"api_key": self._key}

    async def eia_series(self, sid: str, n: int = 104) -> dict:
        body = await self.get_json(EIA_SERIES.format(sid=sid), {"length": str(n)})
        try:
            return {**P.eia_series(body), "id": sid, "source": self.source}
        except P.ParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        await self.eia_series("PET.WCESTUS1.W", 1)


class NassProvider(KeyedProvider):
    """USDA NASS QuickStats, free key. DOC-SHAPED: from the QuickStats API documentation, never run with a live key
    (fixture `nass_docshape_*`, NOT A RECORDING)."""
    name = "nass"
    label = "USDA NASS QuickStats (free key)"
    capabilities = frozenset({"nass_crop"})
    markets = "Weekly crop progress and condition for US corn, soybeans and wheat"
    terms = "Free key (NASS_API_KEY). US government data; the key goes in the query string, so it is redacted from every log line."
    key_name = "NASS_API_KEY"
    hide_without_key = False
    msg_refused = "NASS refused the key ({code})"
    rate = (2.0, 4)
    max_wait = 4.0
    timeout = 40.0
    headers: ClassVar[dict[str, str]] = {"User-Agent": UA}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.fixture:
            self.source = "nass (doc-shaped fixture, NOT A RECORDING)"

    def auth_params(self) -> dict[str, str]:
        return {"key": self._key}

    async def nass_crop(self, commodity: str, year: int) -> dict:
        params: dict[str, Any] = {"source_desc": "SURVEY", "sector_desc": "CROPS", "commodity_desc": commodity,
                                  "statisticcat_desc": "CONDITION", "agg_level_desc": "NATIONAL", "year": str(year), "format": "JSON"}
        body = await self.get_json(NASS_URL, params)
        try:
            return {"rows": P.nass(body), "source": self.source}
        except P.ParseError as e:
            raise ProviderError("unavailable", str(e)) from e

    async def probe(self) -> None:
        await self.nass_crop("CORN", datetime.now(UTC).year)
