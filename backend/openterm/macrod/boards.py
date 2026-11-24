"""What each Phase 30 board shows: the FRED series ids, ETFs, currencies and countries, in one place so scripts/record_phase30.py records
exactly what the service asks for. Every FRED id here was checked against fred.stlouisfed.org by that script (a 404 is dropped
from the list, never replaced by a guess).

`kind` (see world/seriesboard.py KINDS): "rate" = the value is already a percent (the change is in points), "level" = an index or
amount (the board shows a year-on-year percent where it says so).
"""

from __future__ import annotations

# --- WB: world government bond yields -----------------------------------------------------------------------------------------
# Monthly 10-year yields from the OECD's Main Economic Indicators via FRED (IRLTLT01<CC>M156N). Daily rows come from the US
# Treasury (FRED DGS*), the ECB AAA curve, the Bank of England par curve and Japan's MoF (the RATES curves).
WB_MONTHLY: tuple[tuple[str, str], ...] = (
    ("UNITED KINGDOM", "GB"), ("GERMANY", "DE"), ("FRANCE", "FR"), ("ITALY", "IT"), ("SPAIN", "ES"), ("NETHERLANDS", "NL"),
    ("SWITZERLAND", "CH"), ("SWEDEN", "SE"), ("JAPAN", "JP"), ("CANADA", "CA"), ("AUSTRALIA", "AU"), ("NEW ZEALAND", "NZ"),
    ("KOREA", "KR"), ("MEXICO", "MX"), ("SOUTH AFRICA", "ZA"),
    # INDIA: FRED has no IRLTLT01INM156N (404 on 2026-11-24)
)
WB_US = (("UNITED STATES", "DGS2", "DGS10"),)
WB_CURVES = (("EURO AREA AAA (ECB)", "curve_eur"), ("UNITED KINGDOM (BOE PAR)", "curve_gbp"), ("JAPAN (MOF)", "curve_jpy"))


def wb_id(cc: str) -> str:
    return f"IRLTLT01{cc}M156N"


# --- CRPR: credit spreads (ICE BofA option-adjusted spreads via FRED; FRED keeps only the last three years) ---------------------
CRPR: tuple[tuple[str, str, str], ...] = (
    ("BAMLC0A0CM", "US CORPORATE IG", "US IG"), ("BAMLC0A1CAAA", "US AAA", "US IG"), ("BAMLC0A2CAA", "US AA", "US IG"),
    ("BAMLC0A3CA", "US A", "US IG"), ("BAMLC0A4CBBB", "US BBB", "US IG"), ("BAMLH0A0HYM2", "US HIGH YIELD", "US HY"),
    ("BAMLH0A1HYBB", "US BB", "US HY"), ("BAMLH0A2HYB", "US B", "US HY"), ("BAMLH0A3HYC", "US CCC AND LOWER", "US HY"),
    ("BAMLHE00EHYIOAS", "EURO HIGH YIELD", "EURO"), ("BAMLEMCBPIOAS", "EM CORPORATE PLUS", "EM"),
    ("BAMLEMHBHYCRPIOAS", "EM HIGH YIELD", "EM"), ("BAMLEMIBHGCRPIOAS", "EM HIGH GRADE", "EM"),
)

# --- RE: housing board (FRED) ---------------------------------------------------------------------------------------------------
#: (id, label, unit, kind, yoy) yoy = also show the year-on-year percent of a level
RE: tuple[tuple[str, str, str, str, bool], ...] = (
    ("CSUSHPINSA", "CASE-SHILLER US NATIONAL HOME PRICE INDEX", "INDEX", "level", True),
    ("USSTHPI", "FHFA ALL-TRANSACTIONS HOUSE PRICE INDEX", "INDEX", "level", True),
    ("MSPUS", "MEDIAN SALES PRICE OF HOUSES SOLD", "USD", "level", True),
    ("HOUST", "HOUSING STARTS", "THOUS. SAAR", "level", False),
    ("PERMIT", "BUILDING PERMITS", "THOUS. SAAR", "level", False),
    ("COMPUTSA", "HOUSING COMPLETIONS", "THOUS. SAAR", "level", False),
    ("HSN1F", "NEW ONE-FAMILY HOUSES SOLD", "THOUS. SAAR", "level", False),
    ("MSACSR", "MONTHS' SUPPLY OF NEW HOUSES", "MONTHS", "rate", False),
    ("MORTGAGE30US", "30-YEAR FIXED MORTGAGE RATE", "%", "rate", False),
    ("MORTGAGE15US", "15-YEAR FIXED MORTGAGE RATE", "%", "rate", False),
    ("RRVRUSQ156N", "RENTAL VACANCY RATE", "%", "rate", False),
    ("RHORUSQ156N", "HOMEOWNERSHIP RATE", "%", "rate", False),
)

# --- BTMM: one-country monitor ---------------------------------------------------------------------------------------------------
#: field -> (label, kind, yoy). None = no free keyless series wired for that country (the board says so).
BTMM_FIELDS = (("policy", "POLICY RATE", "rate", False), ("y2", "2Y GOVT YIELD", "rate", False), ("y10", "10Y GOVT YIELD", "rate", False),
               ("fx", "FX", "level", False), ("index", "MAIN EQUITY INDEX", "level", False), ("cpi", "CPI INFLATION Y/Y", "level", True),
               ("gdp", "REAL GDP GROWTH", "rate", False))
#: A value is a FRED id, "curve:<capability>:<tenor>" (the RATES curves: daily) or "policy:<BANK>" (CENB's policy-rate source).
#: The OECD monthly series on FRED stopped for several countries (India policy rate and 10Y, Japan and UK policy rates: checked
#: 2026-11-24), so daily central-bank sources are used where the app has them.
BTMM: dict[str, dict[str, str | None]] = {
    "US": {"name": "UNITED STATES", "policy": "DFEDTARU", "y2": "DGS2", "y10": "DGS10", "fx": "DTWEXBGS", "index": "SP500",
           "cpi": "CPIAUCSL", "gdp": "A191RL1Q225SBEA", "fx_label": "BROAD DOLLAR INDEX", "gdp_label": "Q/Q SAAR"},
    "IN": {"name": "INDIA", "policy": None, "y2": None, "y10": None, "fx": "DEXINUS", "index": None,
           "cpi": "INDCPIALLMINMEI", "gdp": "NAEXKP01INQ657S", "fx_label": "INR PER USD", "gdp_label": "Q/Q"},
    "UK": {"name": "UNITED KINGDOM", "policy": "policy:BOE", "y2": None, "y10": "curve:curve_gbp:10Y", "fx": "DEXUSUK", "index": None,
           "cpi": "GBRCPIALLMINMEI", "gdp": "NAEXKP01GBQ657S", "fx_label": "USD PER GBP", "gdp_label": "Q/Q"},
    "EA": {"name": "EURO AREA", "policy": "ECBDFR", "y2": "curve:curve_eur:2Y", "y10": "curve:curve_eur:10Y", "fx": "DEXUSEU", "index": None,
           "cpi": "CP0000EZ19M086NEST", "gdp": "NAEXKP01EZQ657S", "fx_label": "USD PER EUR", "gdp_label": "Q/Q"},
    "JP": {"name": "JAPAN", "policy": None, "y2": "curve:curve_jpy:2Y", "y10": "curve:curve_jpy:10Y", "fx": "DEXJPUS", "index": "NIKKEI225",
           "cpi": "JPNCPIALLMINMEI", "gdp": "NAEXKP01JPQ657S", "fx_label": "JPY PER USD", "gdp_label": "Q/Q"},
}
#: main index quotes for countries whose index is not on FRED (Yahoo through the normal quote chain; may be missing in fixture mode)
BTMM_INDEX_QUOTES = {"IN": "^NSEI", "UK": "^FTSE", "EA": "^STOXX50E"}

# --- ECFC: forecasts ----------------------------------------------------------------------------------------------------------
ECFC_COUNTRIES = (("USA", "UNITED STATES"), ("IND", "INDIA"), ("GBR", "UNITED KINGDOM"), ("DEU", "GERMANY"), ("FRA", "FRANCE"),
                  ("ITA", "ITALY"), ("JPN", "JAPAN"), ("CHN", "CHINA"), ("CAN", "CANADA"), ("BRA", "BRAZIL"))
IMF_INDICATORS = (("NGDP_RPCH", "REAL GDP GROWTH %"), ("PCPIPCH", "INFLATION, AVERAGE CPI %"), ("LUR", "UNEMPLOYMENT RATE %"))
OECD_MEASURES = (("GDPV_ANNPCT", "REAL GDP GROWTH %"), ("CPI_YTYPCT", "CPI INFLATION %"), ("UNR", "UNEMPLOYMENT RATE %"),
                 ("IRL", "LONG-TERM INTEREST RATE %"))
#: FOMC Summary of Economic Projections via FRED: (median id, label, range-high id, range-low id)
SEP = (("GDPC1MD", "REAL GDP GROWTH (Q4/Q4)", "GDPC1RH", "GDPC1RL"), ("UNRATEMD", "UNEMPLOYMENT RATE (Q4)", "UNRATERH", "UNRATERL"),
       ("PCECTPIMD", "PCE INFLATION (Q4/Q4)", "PCECTPIRH", "PCECTPIRL"), ("JCXFEMD", "CORE PCE INFLATION (Q4/Q4)", "JCXFERH", "JCXFERL"),
       ("FEDTARMD", "FED FUNDS RATE (END OF YEAR)", "FEDTARRH", "FEDTARRL"))

# --- WCRS: currencies ranked against USD and INR (ECB reference rates via Frankfurter) -------------------------------------------
WCRS_CCYS = ("EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK", "CNY", "HKD", "SGD", "KRW", "INR", "IDR", "MYR",
             "PHP", "THB", "BRL", "MXN", "ZAR", "TRY", "PLN", "CZK", "HUF", "ILS", "ISK", "RON")
WCRS_PERIODS = (("1W", 7), ("1M", 30), ("3M", 91), ("6M", 182), ("YTD", 0), ("1Y", 365))

# --- WPE: world index valuation through country ETFs -------------------------------------------------------------------------
WPE_ETFS: tuple[tuple[str, str], ...] = (
    ("UNITED STATES (S&P 500)", "SPY"), ("UNITED STATES (NASDAQ-100)", "QQQ"), ("EUROZONE", "EZU"), ("UNITED KINGDOM", "EWU"),
    ("GERMANY", "EWG"), ("FRANCE", "EWQ"), ("SWITZERLAND", "EWL"), ("JAPAN", "EWJ"), ("INDIA", "INDA"), ("CHINA", "MCHI"),
    ("KOREA", "EWY"), ("TAIWAN", "EWT"), ("AUSTRALIA", "EWA"), ("CANADA", "EWC"), ("BRAZIL", "EWZ"), ("MEXICO", "EWW"),
    ("EMERGING MARKETS", "EEM"), ("WORLD EX-US", "VEU"),
)

# --- NRGF: EIA weekly series (API v2 `seriesid`, the old ids) --------------------------------------------------------------------
NRGF: tuple[tuple[str, str, str], ...] = (
    ("PET.WCESTUS1.W", "US CRUDE STOCKS EX-SPR", "MBBL"), ("PET.W_EPC0_SAX_YCUOK_MBBL.W", "CUSHING CRUDE STOCKS", "MBBL"),
    ("PET.WCSSTUS1.W", "STRATEGIC PETROLEUM RESERVE", "MBBL"), ("PET.WGTSTUS1.W", "TOTAL GASOLINE STOCKS", "MBBL"),
    ("PET.WDISTUS1.W", "DISTILLATE STOCKS", "MBBL"), ("PET.WPULEUS3.W", "REFINERY UTILISATION", "%"),
    ("PET.WCRFPUS2.W", "US CRUDE PRODUCTION", "MBBL/D"), ("NG.NW2_EPG0_SWO_R48_BCF.W", "NATURAL GAS IN STORAGE (LOWER 48)", "BCF"),
)

AGRI_CROPS = ("CORN", "SOYBEANS", "WHEAT")

ALL_FRED = sorted({*(wb_id(cc) for _, cc in WB_MONTHLY), "DGS2", "DGS10", *(c[0] for c in CRPR), *(r[0] for r in RE),
                   *(v for c in BTMM.values() for k, v in c.items() if k in {f[0] for f in BTMM_FIELDS} and v and ":" not in v),
                   *(x for s in SEP for x in (s[0], s[2], s[3]))})
