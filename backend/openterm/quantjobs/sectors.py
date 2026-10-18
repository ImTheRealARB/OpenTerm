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
