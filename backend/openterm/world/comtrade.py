"""UN Comtrade (trade flows between two countries, by HS product): request builder and response parser. Pure code.

Endpoint: GET https://comtradeapi.un.org/data/v1/get/C/A/HS      (C = goods, A = annual, HS = Harmonized System)
    ?reporterCode=842&partnerCode=156&period=2021,2022,2023&cmdCode=TOTAL&flowCode=X,M&partner2Code=0&customsCode=C00&motCode=0&includeDesc=true
    header Ocp-Apim-Subscription-Key: <key>
Answer: {"elapsedTime": 0.4, "count": 6, "data": [{"refYear": 2023, "period": "2023", "reporterCode": 842, "reporterISO": "USA",
         "reporterDesc": "USA", "flowCode": "X", "flowDesc": "Export", "partnerCode": 156, "partnerISO": "CHN", "partnerDesc": "China",
         "partner2Code": 0, "customsCode": "C00", "motCode": 0, "cmdCode": "TOTAL", "cmdDesc": "All Commodities",
         "qty": ..., "netWgt": ..., "cifvalue": ..., "fobvalue": ..., "primaryValue": 1.5e11, "isAggregate": true}], "error": ""}
URL shape and the free-tier use checked against https://uncomtrade.org/docs/un-comtrade-api/ (2026-11-05). CHECKED LIVE the same day
with a real key (fixtures `comtrade_real_ind_usa_*`): the field list above is right, and India's own report of trade with the USA
(139.8 bn USD in 2025, 118.4 bn in 2024) matches the published figures. A call for reporterCode=0 (the world) answers an empty 200,
so `usdata.trade` refuses WLD as a reporter before spending a call. The free key also has a per-minute limit: 7 calls in a row
were fine, the 8th answered 429. The parser fails loudly on a missing field. The trade value is `primaryValue` in US dollars (exports are FOB, imports CIF as the reporter files them). Free key:
500 calls a day, 100,000 records a call.
"""

from __future__ import annotations

from typing import Any

from .seriesboard import NoData, NotUnderstood, num

URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
SOURCE = "UN COMTRADE (UN STATISTICS DIVISION), ANNUAL, AS REPORTED BY THE REPORTING COUNTRY"
MAX_YEARS = 12

# ISO3 -> (Comtrade numeric code, name). Comtrade's own codes: the USA is 842, Taiwan is "Other Asia, nes" (490).
COUNTRIES: dict[str, tuple[int, str]] = {
    "WLD": (0, "World"), "USA": (842, "USA"), "CHN": (156, "China"), "IND": (699, "India"), "DEU": (276, "Germany"),
    "JPN": (392, "Japan"), "GBR": (826, "United Kingdom"), "FRA": (251, "France"), "ITA": (380, "Italy"),
    "KOR": (410, "Rep. of Korea"), "CAN": (124, "Canada"), "MEX": (484, "Mexico"), "BRA": (76, "Brazil"),
    "RUS": (643, "Russian Federation"), "AUS": (36, "Australia"), "IDN": (360, "Indonesia"), "SAU": (682, "Saudi Arabia"),
    "ARE": (784, "United Arab Emirates"), "TUR": (792, "Turkiye"), "NLD": (528, "Netherlands"), "ESP": (724, "Spain"),
    "CHE": (756, "Switzerland"), "SGP": (702, "Singapore"), "VNM": (704, "Viet Nam"), "THA": (764, "Thailand"),
    "MYS": (458, "Malaysia"), "ZAF": (710, "South Africa"), "ARG": (32, "Argentina"), "BGD": (50, "Bangladesh"),
    "PAK": (586, "Pakistan"), "EGY": (818, "Egypt"), "NGA": (566, "Nigeria"), "ISR": (376, "Israel"), "POL": (616, "Poland"),
    "SWE": (752, "Sweden"), "NOR": (579, "Norway"), "BEL": (56, "Belgium"), "TWN": (490, "Other Asia, nes (Taiwan)"),
    "HKG": (344, "China, Hong Kong SAR"), "PHL": (608, "Philippines"), "CHL": (152, "Chile"), "COL": (170, "Colombia"),
}
ALIASES = {"US": "USA", "UK": "GBR", "UAE": "ARE", "KOREA": "KOR", "WORLD": "WLD", "ALL": "WLD", "CHINA": "CHN", "INDIA": "IND",
           "GERMANY": "DEU", "JAPAN": "JPN", "FRANCE": "FRA", "ITALY": "ITA", "CANADA": "CAN", "MEXICO": "MEX", "BRAZIL": "BRA",
           "RUSSIA": "RUS", "AUSTRALIA": "AUS", "TAIWAN": "TWN", "VIETNAM": "VNM", "TURKEY": "TUR", "SPAIN": "ESP"}


def country(text: str) -> tuple[str, int, str]:
    """'china', 'CHN' or '156' -> ('CHN', 156, 'China'). Unknown words raise ValueError listing what is accepted."""
    t = text.strip().upper()
    t = ALIASES.get(t, t)
    if t in COUNTRIES:
        return t, COUNTRIES[t][0], COUNTRIES[t][1]
    if t.isdigit():
        for iso, (code, name) in COUNTRIES.items():
            if code == int(t):
                return iso, code, name
    raise ValueError(f"UNKNOWN COUNTRY {text[:20].upper()}. USE A 3-LETTER CODE: {' '.join(COUNTRIES)}")


def commodity(text: str) -> str:
    """TOTAL or an HS code of 2, 4 or 6 digits (a chapter, heading or subheading)."""
    t = text.strip().upper()
    if t in ("", "TOTAL", "ALL"):
        return "TOTAL"
    if t.isdigit() and len(t) in (2, 4, 6):
        return t
    raise ValueError(f"HS CODE MUST BE TOTAL OR 2, 4 OR 6 DIGITS (FOR EXAMPLE 85, 8517, 851713), NOT {text[:10].upper()}")


def build_params(reporter: int, partner: int, cmd: str, years: list[int]) -> dict[str, str]:
    if not years or len(years) > MAX_YEARS:
        raise ValueError(f"ASK FOR 1 TO {MAX_YEARS} YEARS")
    return {"reporterCode": str(reporter), "partnerCode": str(partner), "period": ",".join(str(y) for y in years), "cmdCode": cmd,
            "flowCode": "X,M", "partner2Code": "0", "customsCode": "C00", "motCode": "0", "includeDesc": "true"}


def parse(body: Any, reporter: tuple[str, int, str], partner: tuple[str, int, str], cmd: str, years: list[int]) -> dict[str, Any]:
    """One row per year with exports, imports, total and balance in US dollars. A flow Comtrade did not return stays None."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise NotUnderstood("COMTRADE ANSWER HAS NO data LIST")
    if body.get("error"):
        raise NotUnderstood(f"COMTRADE ERROR: {str(body['error'])[:160]}")
    flows: dict[tuple[int, str], float | None] = {}
    desc = ""
    for r in body["data"]:
        if not isinstance(r, dict):
            raise NotUnderstood("COMTRADE ROW IS NOT AN OBJECT")
        # Keep only the all-modes, all-customs, all-second-partner totals: other breakdown rows would double count.
        if (r.get("partner2Code") or 0) != 0 or (r.get("customsCode") or "C00") != "C00" or (r.get("motCode") or 0) != 0:
            continue
        for f in ("refYear", "flowCode", "primaryValue", "cmdCode"):
            if f not in r:
                raise NotUnderstood(f"COMTRADE ROW HAS NO {f} FIELD")
        if r["flowCode"] not in ("X", "M"):
            continue
        if str(r["cmdCode"]).upper() != cmd:
            continue
        k = (int(r["refYear"]), r["flowCode"])
        if k in flows:
            raise NotUnderstood(f"COMTRADE REPEATS {k[0]} {k[1]}")
        flows[k] = num(r["primaryValue"])
        desc = desc or str(r.get("cmdDesc") or "")
    rows = []
    for y in sorted(years, reverse=True):
        x, m = flows.get((y, "X")), flows.get((y, "M"))
        if x is None and m is None:
            continue
        rows.append({"year": y, "exports": x, "imports": m, "total": (x + m) if x is not None and m is not None else None,
                     "balance": (x - m) if x is not None and m is not None else None})
    if not rows:
        raise NoData(f"COMTRADE HAS NO {reporter[0]} TO {partner[0]} DATA FOR {cmd} IN {years[0]}-{years[-1]} (NOT REPORTED OR NOT YET PUBLISHED)")
    return {"reporter": {"iso": reporter[0], "name": reporter[2]}, "partner": {"iso": partner[0], "name": partner[2]},
            "cmd": cmd, "cmd_desc": desc or ("All Commodities" if cmd == "TOTAL" else f"HS {cmd}"), "unit": "USD", "rows": rows,
            "source": SOURCE,
            "note": "EXPORTS AND IMPORTS ARE EACH COUNTRY'S OWN REPORT (REPORTER'S VIEW), NOT MIRROR DATA. A YEAR IS BLANK WHEN THE REPORTER HAS NOT FILED IT YET. "
                    "BALANCE = EXPORTS MINUS IMPORTS."}
