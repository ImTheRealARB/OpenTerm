"""Sector tables shared by the server (builds job params) and the PORT ATTR job. Pure Python, no heavy imports.

Canonical sector names are the Nasdaq screener's own (the `sector` column); each maps to the SPDR Select Sector ETF that stands in for it.
Yahoo's `topHoldings.sectorWeightings` keys map onto the same names. The mapping is approximate (Nasdaq and Yahoo do not use GICS the same
way); PORT ATTR says so in its notes.
"""

UNCLASSIFIED = "Unclassified"

SPDR = {
    "Technology": "XLK", "Finance": "XLF", "Health Care": "XLV", "Consumer Discretionary": "XLY", "Consumer Staples": "XLP",
    "Energy": "XLE", "Industrials": "XLI", "Basic Materials": "XLB", "Utilities": "XLU", "Real Estate": "XLRE",
    "Telecommunications": "XLC",
}

YAHOO_TO_SECTOR = {
    "technology": "Technology", "financial_services": "Finance", "healthcare": "Health Care",
    "consumer_cyclical": "Consumer Discretionary", "consumer_defensive": "Consumer Staples", "energy": "Energy",
    "industrials": "Industrials", "basic_materials": "Basic Materials", "utilities": "Utilities", "realestate": "Real Estate",
    "communication_services": "Telecommunications",
}


def from_yahoo_name(display: str | None) -> str:
    """A Yahoo sector DISPLAY name ("Financial Services", the screener's labels) as the canonical (Nasdaq) name; "" when blank or unknown.

    Yahoo spells the same sectors two ways: display names here, `snake_case` keys in `sectorWeightings` (YAHOO_TO_SECTOR)."""
    key = (display or "").strip().lower().replace(" ", "_")
    return YAHOO_TO_SECTOR.get("realestate" if key == "real_estate" else key, "")


# TradingView's scanner uses its own 20 sectors (FactSet's RBICS-style names). Each maps onto the nearest canonical (Nasdaq)
# sector; like the Yahoo map this is approximate, and a few industries are moved by name below where the sector alone lands
# them in the wrong place (REITs sit under TradingView's "Finance", oilfield services under "Industrial Services").
TRADINGVIEW_TO_SECTOR = {
    "Electronic Technology": "Technology", "Technology Services": "Technology",
    "Finance": "Finance",
    "Health Technology": "Health Care", "Health Services": "Health Care",
    "Consumer Durables": "Consumer Discretionary", "Consumer Services": "Consumer Discretionary",
    "Retail Trade": "Consumer Discretionary",
    "Consumer Non-Durables": "Consumer Staples",
    "Energy Minerals": "Energy",
    "Producer Manufacturing": "Industrials", "Industrial Services": "Industrials", "Transportation": "Industrials",
    "Commercial Services": "Industrials", "Distribution Services": "Industrials",
    "Non-Energy Minerals": "Basic Materials", "Process Industries": "Basic Materials",
    "Utilities": "Utilities",
    "Communications": "Telecommunications",
    "Miscellaneous": "Miscellaneous",  # funds and trusts; Nasdaq has the same catch-all
}
TRADINGVIEW_INDUSTRY_TO_SECTOR = {
    "Real Estate Investment Trusts": "Real Estate", "Real Estate Development": "Real Estate",
    "Oilfield Services/Equipment": "Energy", "Contract Drilling": "Energy", "Oil & Gas Pipelines": "Energy",
    "Food Retail": "Consumer Staples", "Drugstore Chains": "Consumer Staples",
}


def from_tradingview(sector: str | None, industry: str | None) -> str:
    """A TradingView sector (and industry) as the canonical (Nasdaq) name; "" when blank or unknown, never a guess."""
    return TRADINGVIEW_INDUSTRY_TO_SECTOR.get((industry or "").strip()) or TRADINGVIEW_TO_SECTOR.get((sector or "").strip(), "")


def canonical(screener_sector: str | None) -> str:
    """A screener sector name as a SPDR-mapped sector, else Unclassified (Miscellaneous, blank, unknown)."""
    s = (screener_sector or "").strip()
    return s if s in SPDR else UNCLASSIFIED


def bench_weights(yahoo_sectors: list[dict]) -> dict[str, float] | None:
    """Yahoo `sectors` ([{sector, weight}]) as canonical sector -> weight, normalised to sum 1 (Yahoo rounds). None when empty."""
    out: dict[str, float] = {}
    for s in yahoo_sectors:
        name = YAHOO_TO_SECTOR.get(s.get("sector"))
        w = s.get("weight")
        if name and isinstance(w, int | float) and w > 0:
            out[name] = out.get(name, 0.0) + float(w)
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total > 0 else None
