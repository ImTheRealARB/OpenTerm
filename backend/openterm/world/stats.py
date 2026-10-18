"""World statistics (ECST, WECO): indicator catalogue, country resolution and pure parsers for World Bank API v2 and DBnomics (pure; no network)."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..providers.base import ProviderError


@dataclass(frozen=True)
class Indicator:
    alias: str
    wb: str
    label: str
    unit: str
    imf: str | None  # IMF WEO subject code, for the DBnomics fallback
    imf_scale: float = 1.0  # WEO value x scale = the World Bank unit


INDICATORS: dict[str, Indicator] = {i.alias: i for i in (
    Indicator("GDP", "NY.GDP.MKTP.CD", "GDP, current US$", "US$", "NGDPD", 1e9),
    Indicator("GDPG", "NY.GDP.MKTP.KD.ZG", "GDP growth, annual %", "%", "NGDP_RPCH"),
    Indicator("GDPPC", "NY.GDP.PCAP.CD", "GDP per capita, current US$", "US$", "NGDPDPC"),
    Indicator("CPI", "FP.CPI.TOTL.ZG", "Inflation, consumer prices, annual %", "%", "PCPIPCH"),
    Indicator("UNEMP", "SL.UEM.TOTL.ZS", "Unemployment, % of labour force", "%", "LUR"),
    Indicator("POP", "SP.POP.TOTL", "Population, total", "people", "LP", 1e6),
    Indicator("DEBT", "GC.DOD.TOTL.GD.ZS", "Central government debt, % of GDP", "% of GDP", "GGXWDG_NGDP"),
    Indicator("CA", "BN.CAB.XOKA.GD.ZS", "Current account balance, % of GDP", "% of GDP", "BCA_NGDPD"),
    Indicator("TRADE", "NE.TRD.GNFS.ZS", "Trade, % of GDP", "% of GDP", None),
)}
INDICATORS["GDPGROWTH"] = INDICATORS["GDPG"]
INDICATORS["INFLATION"] = INDICATORS["CPI"]
INDICATORS["UNEMPLOYMENT"] = INDICATORS["UNEMP"]

G20 = {
    "ARG": "Argentina", "AUS": "Australia", "BRA": "Brazil", "CAN": "Canada", "CHN": "China", "FRA": "France", "DEU": "Germany", "IND": "India",
    "IDN": "Indonesia", "ITA": "Italy", "JPN": "Japan", "KOR": "South Korea", "MEX": "Mexico", "RUS": "Russia", "SAU": "Saudi Arabia",
    "ZAF": "South Africa", "TUR": "Turkey", "GBR": "United Kingdom", "USA": "United States",
}
WECO_COLUMNS = ("GDPG", "CPI", "UNEMP", "DEBT", "CA")  # growth, inflation, unemployment, debt / GDP, current account

_ISO2 = {"AR": "ARG", "AU": "AUS", "BR": "BRA", "CA": "CAN", "CN": "CHN", "FR": "FRA", "DE": "DEU", "IN": "IND", "ID": "IDN", "IT": "ITA", "JP": "JPN",
         "KR": "KOR", "MX": "MEX", "RU": "RUS", "SA": "SAU", "ZA": "ZAF", "TR": "TUR", "GB": "GBR", "US": "USA", "ES": "ESP", "NL": "NLD", "CH": "CHE",
         "SE": "SWE", "NO": "NOR", "PL": "POL", "SG": "SGP", "HK": "HKG", "EG": "EGY", "NG": "NGA", "TH": "THA", "VN": "VNM", "MY": "MYS",
         "PH": "PHL", "PK": "PAK", "BD": "BGD", "IL": "ISR", "AE": "ARE", "CL": "CHL", "CO": "COL", "PE": "PER", "NZ": "NZL", "IE": "IRL",
         "PT": "PRT", "GR": "GRC", "AT": "AUT", "BE": "BEL", "DK": "DNK", "FI": "FIN", "CZ": "CZE", "HU": "HUN", "UA": "UKR", "EU": "EUU"}
_NAMES = {"UK": "GBR", "ENGLAND": "GBR", "BRITAIN": "GBR", "USA": "USA", "AMERICA": "USA", "KOREA": "KOR", "SOUTHKOREA": "KOR", "UAE": "ARE",
          "EU": "EUU", "EURO": "EMU", "EUROZONE": "EMU", "WORLD": "WLD", "HONGKONG": "HKG", "SAUDI": "SAU", "SOUTHAFRICA": "ZAF",
          **{re.sub(r"[^A-Z]", "", n.upper()): c for c, n in G20.items()}}


def resolve_country(text: str) -> str:
    """ISO3 code for an ISO3 / ISO2 code or a common name; ValueError when it is none of those."""
    t = re.sub(r"[^A-Za-z]", "", text or "").upper()
    if not t:
        raise ValueError("GIVE A COUNTRY: ISO CODE OR NAME, E.G. USA, IN, GERMANY")
    if t in _NAMES:
        return _NAMES[t]
    if len(t) == 3:
        return t
    if len(t) == 2 and t in _ISO2:
        return _ISO2[t]
    raise ValueError(f"UNKNOWN COUNTRY: {text[:24]} (USE THE 3-LETTER ISO CODE)")


DBN_REF = re.compile(r"^DBN:([A-Za-z0-9_\-]+)/([A-Za-z0-9_.\-:]+)/([A-Za-z0-9_.\-/]+)$", re.IGNORECASE)


def parse_dbn_ref(text: str) -> tuple[str, str, str] | None:
    """`DBN:<provider>/<dataset>/<series>` -> (provider, dataset, series)."""
    m = DBN_REF.match(text.strip())
    return (m.group(1).upper(), m.group(2), m.group(3)) if m else None


def _epoch(year: int, month: int = 12, day: int | None = None) -> int:
    d = day or calendar.monthrange(year, month)[1]
    return int(datetime(year, month, d, tzinfo=UTC).timestamp())


def period_epoch(period: str) -> int:
    """`2025`, `2025-03`, `2025-Q2`, `2025-03-31` as the epoch second of its period end."""
    p = period.strip()
    m = re.match(r"^(\d{4})$", p)
    if m:
        return _epoch(int(m.group(1)))
    m = re.match(r"^(\d{4})-?Q([1-4])$", p, re.IGNORECASE)
    if m:
        return _epoch(int(m.group(1)), int(m.group(2)) * 3)
    m = re.match(r"^(\d{4})-(\d{2})$", p)
    if m:
        return _epoch(int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", p)
    if m:
        return _epoch(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise ValueError(f"UNKNOWN PERIOD FORMAT: {p[:16]}")


def _wb_check(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list) and len(body) == 1 and isinstance(body[0], dict) and "message" in body[0]:
        raise ProviderError("not_found", "WORLD BANK: " + str(body[0]["message"][0].get("value", "NO SUCH COUNTRY OR INDICATOR"))[:120])
    if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
        raise ProviderError("not_found", "WORLD BANK: NO DATA")
    return body[1]


def parse_wb_series(body: Any, ind: Indicator, iso3: str) -> dict[str, Any]:
    """World Bank v2 country/indicator answer -> ascending annual series; empty years are dropped, never filled."""
    rows = _wb_check(body)
    pts = sorted((int(r["date"]), float(r["value"])) for r in rows if r.get("value") is not None and str(r.get("date", "")).isdigit())
    if not pts:
        raise ProviderError("not_found", f"WORLD BANK HAS NO {ind.alias} VALUES FOR {iso3}")
    head = body[0] if isinstance(body[0], dict) else {}
    name = rows[0].get("country", {}).get("value") or iso3
    return {"country": iso3, "country_name": name, "indicator": ind.alias, "label": ind.label, "unit": ind.unit, "freq": "ANNUAL",
            "t": [_epoch(y) for y, _ in pts], "v": [v for _, v in pts], "periods": [str(y) for y, _ in pts],
            "last_period": str(pts[-1][0]), "last_value": pts[-1][1], "updated": head.get("lastupdated"), "source": "worldbank"}


def parse_dbn_series(body: Any, label: str | None = None, unit: str = "", scale: float = 1.0, country: str = "", ind_alias: str = "") -> dict[str, Any]:
    """DBnomics `series/<provider>/<dataset>/<series>?observations=1` answer -> series; 'NA' observations are dropped."""
    docs = ((body or {}).get("series") or {}).get("docs") if isinstance(body, dict) else None
    if not docs:
        raise ProviderError("not_found", "DBNOMICS: SERIES NOT FOUND")
    doc = docs[0]
    pts = []
    for per, val in zip(doc.get("period", []), doc.get("value", []), strict=False):
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            pts.append((per, period_epoch(per), float(val) * scale))
    if not pts:
        raise ProviderError("not_found", "DBNOMICS: SERIES HAS NO VALUES")
    pts.sort(key=lambda x: x[1])
    return {"country": country, "country_name": country, "indicator": ind_alias, "label": label or doc.get("series_name") or doc.get("series_code", ""),
            "unit": unit, "freq": str(doc.get("@frequency", "")).upper() or "ANNUAL", "t": [p[1] for p in pts], "v": [p[2] for p in pts],
            "periods": [p[0] for p in pts], "last_period": pts[-1][0], "last_value": pts[-1][2], "updated": doc.get("indexed_at"),
            "source": f"dbnomics {doc.get('provider_code', '')}/{doc.get('dataset_code', '')}".strip(), "dataset": doc.get("dataset_name")}


def parse_wb_latest(body: Any) -> dict[str, dict[str, Any]]:
    """World Bank `mrnev=1` answer for many countries -> {iso3: {"v", "year"}}; each country keeps ITS OWN most recent year."""
    out: dict[str, dict[str, Any]] = {}
    for r in _wb_check(body):
        if r.get("value") is not None and str(r.get("date", "")).isdigit():
            out[r["countryiso3code"]] = {"v": float(r["value"]), "year": int(r["date"])}
    return out


def weco_rows(latest: dict[str, dict[str, dict[str, Any]]], now_year: int) -> list[dict[str, Any]]:
    """One row per G20 country: a cell is {v, year, stale} or None. Years are never mixed or aligned: `year` is that cell's own data year."""
    rows = []
    for iso, name in G20.items():
        cells = {}
        for col in WECO_COLUMNS:
            c = latest.get(col, {}).get(iso)
            cells[col] = None if c is None else {**c, "stale": now_year - c["year"] > 2}
        rows.append({"iso3": iso, "name": name, "cells": cells})
    return rows


def parse_wb_countries(body: Any) -> dict[str, str]:
    return {r["id"]: r["name"] for r in _wb_check(body) if r.get("id") and r.get("name")}
