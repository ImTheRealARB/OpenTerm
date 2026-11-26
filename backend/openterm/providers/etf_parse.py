"""Pure parsers for the ETF screener (FSRC): no network, no clock, nothing to mock in a test.

Two inputs, two functions:

  * `parse_symbol_file`  Nasdaq Trader's `nasdaqtraded.txt`, the daily list of every US-traded security. One line per security,
    fields split by `|`. We keep the lines flagged ETF = Y (and not a test issue). The file is the only free list of "all US
    ETFs", which is why FSRC starts here: Yahoo has no "list every ETF" endpoint.
  * `fund_from_summary`  one Yahoo `quoteSummary` answer (modules `fundProfile` + `summaryDetail`) -> the numbers FSRC shows.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderError

# Columns we need, found BY NAME in the header line so a re-ordered file still parses. A missing one means the file changed shape.
_NEEDED = ("Symbol", "Security Name", "Listing Exchange", "ETF", "Test Issue")

# Listing Exchange codes of the file -> a short exchange name (shown nowhere yet, kept so a row says where it lists).
EXCHANGES = {"N": "NYSE", "P": "NYSE ARCA", "A": "NYSE AMERICAN", "Q": "NASDAQ", "Z": "CBOE BZX", "V": "IEX", "F": "FINRA"}


def parse_symbol_file(text: str) -> tuple[list[dict[str, str]], str | None]:
    """(ETFs, file stamp). Each ETF is {"symbol", "name", "exchange"}; the stamp is the file's own "File Creation Time" footer.

    A line is an ETF when its ETF column is "Y" and its Test Issue column is "N" (test issues are exchange test tickers such as
    ZZZTE, never real funds). The footer line ("File Creation Time: ...") and blank lines are skipped. A header that lacks a
    column we need raises: a silently empty universe would look like "no ETFs exist".
    """
    lines = text.splitlines()  # the file uses CRLF
    if not lines:
        raise ProviderError("unavailable", "symbol file is empty")
    header = lines[0].split("|")
    try:
        col = {name: header.index(name) for name in _NEEDED}
    except ValueError as e:
        raise ProviderError("unavailable", f"symbol file layout changed: {e}") from e
    stamp: str | None = None
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            stamp = line.split(":", 1)[1].split("|")[0].strip()
            continue
        f = line.split("|")
        if len(f) <= max(col.values()):
            continue  # blank or short line
        if f[col["ETF"]] != "Y" or f[col["Test Issue"]] != "N":
            continue
        sym = f[col["Symbol"]].strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append({"symbol": sym, "name": " ".join(f[col["Security Name"]].split()), "exchange": EXCHANGES.get(f[col["Listing Exchange"]], "")})
    return out, stamp


def _raw(module: dict[str, Any] | None, key: str) -> float | None:
    """Yahoo wraps most numbers as {"raw": 1.5, "fmt": "1.50"}; an empty {} or a missing key means "no value"."""
    v = (module or {}).get(key)
    v = v.get("raw") if isinstance(v, dict) else v
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def fund_from_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    """What FSRC shows for one fund, or None when Yahoo has no fund data for it (an ETN, a brand new fund).

    {"fee": expense ratio in PERCENT (0.03 means 0.03%), "aum": total assets in dollars, "category": Morningstar-style category
    name, "family": fund company}. Any field Yahoo leaves empty is None, never a guess. Yahoo sends the expense ratio as a
    fraction (0.0003); we turn it into percent so `FEE<0.2` in the panel reads the way a person says it.
    """
    fp = result.get("fundProfile") or {}
    fees = fp.get("feesExpensesInvestment") or {}
    ratio = _raw(fees, "annualReportExpenseRatio")
    out = {
        # round() undoes Yahoo's float noise: 0.00029999999 is a 0.03% fund
        "fee": round(ratio * 100, 4) if ratio is not None else None,
        "aum": _raw(result.get("summaryDetail"), "totalAssets"),
        "category": (fp.get("categoryName") or "").strip() or None,
        "family": (fp.get("family") or "").strip() or None,
    }
    return out if any(v is not None for v in out.values()) else None
