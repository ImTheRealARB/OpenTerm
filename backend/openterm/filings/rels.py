"""RELS: the other listed instruments of one issuer (share classes). Pure.

Two sources, never merged: (1) SEC `company_tickers_exchange.json` lists every ticker the issuer's CIK trades under (GOOG and GOOGL,
BRK-A and BRK-B) with the exchange; (2) OpenFIGI lists the exchanges and depositary receipts that carry ONE ticker. Each row names its source.
"""

from __future__ import annotations

from typing import Any

from ..research.table import col, head, payload, section

SEC_LABEL = "SEC company_tickers_exchange"
FIGI_LABEL = "OpenFIGI"


def parse_exchange_file(body: Any) -> list[dict[str, Any]]:
    """{"fields": ["cik","name","ticker","exchange"], "data": [[...], ...]} -> list of dicts. Raises ValueError for another shape."""
    if not isinstance(body, dict) or not isinstance(body.get("fields"), list) or not isinstance(body.get("data"), list):
        raise ValueError("SEC TICKER FILE HAS AN UNKNOWN SHAPE")  # noqa: TRY004 (callers catch ValueError for every bad shape)
    fields = body["fields"]
    if not {"cik", "name", "ticker", "exchange"} <= set(fields):
        raise ValueError("SEC TICKER FILE HAS UNKNOWN COLUMNS")
    return [dict(zip(fields, row, strict=False)) for row in body["data"]]


def siblings(rows: list[dict[str, Any]], cik: int) -> list[dict[str, Any]]:
    """Every ticker of one CIK, in the file's order."""
    return [{"ticker": r["ticker"], "exchange": r["exchange"], "name": r["name"], "type": "SHARE CLASS (SAME CIK)", "source": SEC_LABEL}
            for r in rows if int(r["cik"]) == cik]


def figi_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Listings out of `secf.ids.parse_mapping` items (one item per looked-up ticker)."""
    out = []
    for it in items:
        for li in it["listings"]:
            out.append({"ticker": li["ticker"], "exchange": li["exch_code"], "name": li["name"], "type": li["security_type"],
                        "figi": li["figi"], "source": FIGI_LABEL})
    return out


def build_payload(symbol: str, company: str, sec_rows: list[dict[str, Any]], figi: list[dict[str, Any]] | None, figi_note: str | None,
                  source: str) -> dict:
    cols = [col("ticker", "Ticker", "text"), col("exchange", "Exchange", "text"), col("name", "Name", "text", 36), col("type", "Type", "text", 24),
            col("source", "Source", "text", 28)]
    figi_cols = [*cols[:4], col("figi", "FIGI", "text", 14), cols[4]]
    return payload(
        symbol, f"RELS {symbol}", [head("ISSUER", company), head("SAME-CIK TICKERS", str(len(sec_rows))),
                                    head("OPENFIGI LISTINGS", str(len(figi)) if figi is not None else "-")],
        [section("classes", "Share classes (SEC)", cols, sec_rows, "ONE ROW PER TICKER THE SEC FILES UNDER THIS CIK"),
         section("listings", f"Listings of {symbol} (OpenFIGI)", figi_cols, figi or [], figi_note)],
        notes=["OPENFIGI EXCHANGE CODES ARE ITS OWN (US = COMPOSITE, UN = NYSE, UW = NASDAQ GLOBAL SELECT ...), NOT MIC CODES"],
        source=source,
    )
