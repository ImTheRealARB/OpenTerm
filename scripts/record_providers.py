"""Record REAL answers from the keyed market-data sources: Twelve Data, Alpha Vantage, Polygon (Massive) and Financial Modeling Prep.

Run from the repo root:  cd backend; uv run python ../scripts/record_providers.py [--only twelvedata,alphavantage,polygon,fmp]

What needs what:
  - the "bad key" answers of all four hosts need NO account: they are what each service says to a made-up key (keytest_*_401 style);
  - Twelve Data and Alpha Vantage publish a shared `demo` key that answers a few symbols (AAPL / IBM), so their success shapes are
    recorded for real with no account too. Set TWELVEDATA_API_KEY / ALPHAVANTAGE_API_KEY to record with your own key instead;
  - Polygon (Massive) and FMP have no demo key: with POLYGON_API_KEY / FMP_API_KEY set their success answers are recorded for real,
    without them those fixtures stay DOC-SHAPED (built from the docs and labelled "NOT A RECORDING" inside the file) and are skipped here.

A key never reaches a fixture: the key text is replaced by REDACTED in the body (Alpha Vantage echoes the key in its limit message).
Files: backend/tests/fixtures/<source>_real_*.json and keytest_<source>_*.json. Respect the free limits: the script sleeps between calls
(Twelve Data 8/min, Polygon 5/min, Alpha Vantage 25/day: about 9 calls here when a key is used).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

OUT = pathlib.Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"
MADE_UP = "madeupkey12345678"


@dataclass
class Call:
    name: str
    url: str
    params: dict = field(default_factory=dict)
    needs_key: bool = True  # False = a bad-key answer, recorded with MADE_UP in the place the key goes


def scrub(text: str, key: str) -> str:
    return text.replace(key, "REDACTED") if key and key != "demo" else text  # "demo" is public and part of the services' own sentences


def trim_reports(body: object) -> object:
    """Alpha Vantage statements come with 20 years of reports (150 KB): keep 5 annual and 8 quarterly ones."""
    if isinstance(body, dict) and "annualReports" in body:
        return {**body, "annualReports": body["annualReports"][:5], "quarterlyReports": body.get("quarterlyReports", [])[:8]}
    return body


def key_forms(key: str) -> set[str]:
    """Every way a key can be written in an answer: as is, URL-encoded, lower and upper case."""
    return {f for f in (key, urllib.parse.quote(key, safe=""), key.lower(), key.upper()) if f}


def leaks_key(text: str, key: str) -> bool:
    """True when `text` still holds the key. The public `demo` key is not a secret (it is part of the services' own sentences)."""
    return bool(key) and key != "demo" and any(f in text for f in key_forms(key))


def source_label(r: httpx.Response) -> str:
    """Where the answer came from, WITHOUT the query string (it holds the key for Alpha Vantage and FMP): scheme, host, path and the
    names (never values) of the query parameters that are not keys."""
    u = r.request.url
    names = sorted(n for n in dict(u.params) if n.lower() not in ("apikey", "api_key", "token"))
    return f"{u.scheme}://{u.host}{u.path}" + (f" (query: {', '.join(names)})" if names else "")


def save(name: str, r: httpx.Response, key: str, note: str) -> None:
    """Writes backend/tests/fixtures/<name>.json, labelled with the date and the source. REFUSES (exits, writes nothing) when the file
    would still contain the key after it was scrubbed."""
    try:
        body = json.loads(scrub(r.text, key))
    except ValueError:
        body = {"text": scrub(r.text[:400], key)}
    body = trim_reports(body)
    rec = {"status": r.status_code, "recorded": f"{time.strftime('%Y-%m-%d')}, REAL answer ({note})", "source": source_label(r), "body": body}
    text = json.dumps(rec, indent=1, ensure_ascii=False) + "\n"
    for secret in (key, MADE_UP):
        if leaks_key(text, secret):
            raise SystemExit(f"REFUSED: {name} still contains the API key after scrubbing; nothing was written")
    (OUT / f"{name}.json").write_text(text, encoding="utf-8")
    print(f"  {name}: HTTP {r.status_code}, {len(r.text)} bytes")


def twelvedata(c: httpx.Client) -> None:
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    use = key or "demo"
    print("Twelve Data", "(your key)" if key else "(shared demo key)")
    base = "https://api.twelvedata.com"
    hdr = {"Authorization": f"apikey {use}"}
    calls = [
        ("twelvedata_real_quote_aapl", "/quote", {"symbol": "AAPL"}),
        ("twelvedata_real_series_aapl_1day", "/time_series", {"symbol": "AAPL", "interval": "1day", "outputsize": "30", "order": "desc"}),
        ("twelvedata_real_series_aapl_5min", "/time_series", {"symbol": "AAPL", "interval": "5min", "outputsize": "60", "order": "desc", "timezone": "UTC"}),
        ("twelvedata_real_search_aapl", "/symbol_search", {"symbol": "AAPL", "outputsize": "5"}),
        ("twelvedata_real_unknown", "/quote", {"symbol": "ZZZZNOTREAL"}),
    ]
    for name, path, params in calls:
        if not key and name.endswith("_unknown"):
            continue  # the demo key answers 401 for any symbol it does not cover: only a personal key can show an unknown symbol
        save(name, c.get(base + path, params=params, headers=hdr), use, "key sent in the Authorization header")
        time.sleep(8)  # 8 credits a minute on the free plan
    save("keytest_twelvedata_401", c.get(base + "/quote", params={"symbol": "AAPL"}, headers={"Authorization": f"apikey {MADE_UP}"}),
         MADE_UP, "made-up key, no account")


def alphavantage(c: httpx.Client) -> None:
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    use = key or "demo"
    print("Alpha Vantage", "(your key)" if key else "(shared demo key: IBM only)")
    base = "https://www.alphavantage.co/query"
    calls = [
        ("alphavantage_real_quote_ibm", {"function": "GLOBAL_QUOTE", "symbol": "IBM"}),
        ("alphavantage_real_daily_ibm", {"function": "TIME_SERIES_DAILY", "symbol": "IBM", "outputsize": "compact"}),
        ("alphavantage_real_overview_ibm", {"function": "OVERVIEW", "symbol": "IBM"}),
        ("alphavantage_real_income_ibm", {"function": "INCOME_STATEMENT", "symbol": "IBM"}),
        ("alphavantage_real_balance_ibm", {"function": "BALANCE_SHEET", "symbol": "IBM"}),
        ("alphavantage_real_cashflow_ibm", {"function": "CASH_FLOW", "symbol": "IBM"}),
        ("alphavantage_real_intraday_ibm", {"function": "TIME_SERIES_INTRADAY", "symbol": "IBM", "interval": "5min"}),
    ]
    for name, params in calls:
        if not key and name.endswith("_daily_ibm"):
            continue  # the demo key answers "demo purposes only" for this call: only a personal key records it
        save(name, c.get(base, params={**params, "apikey": use}), use, "apikey query parameter")
        time.sleep(2)
    # Alpha Vantage does not validate keys: a made-up key is treated like an anonymous free key. For IBM it can even get data, so ask for
    # TSLA, where the answer is HTTP 200 with a limit text ("We have detected your API key as ... 25 requests per day"). The text echoes the key.
    save("keytest_alphavantage_bad_key", c.get(base, params={"function": "GLOBAL_QUOTE", "symbol": "TSLA", "apikey": MADE_UP}),
         MADE_UP, "made-up key, no account: Alpha Vantage answers 200 with the 25-a-day limit text")


def polygon(c: httpx.Client) -> None:
    key = os.environ.get("POLYGON_API_KEY", "")
    print("Polygon / Massive", "(your key)" if key else "(no key: success shapes stay doc-shaped)")
    base = "https://api.massive.com"
    save("keytest_polygon_401", c.get(base + "/v2/aggs/ticker/AAPL/prev", headers={"Authorization": f"Bearer {MADE_UP}"}), MADE_UP,
         "made-up key, no account")
    if not key:
        return
    hdr = {"Authorization": f"Bearer {key}"}
    today = time.strftime("%Y-%m-%d")
    start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 40 * 86400))
    calls = [
        ("polygon_real_prev_aapl", "/v2/aggs/ticker/AAPL/prev", {"adjusted": "true"}),
        ("polygon_real_aggs_aapl_1d", f"/v2/aggs/ticker/AAPL/range/1/day/{start}/{today}", {"adjusted": "true", "sort": "asc", "limit": "50000"}),
        ("polygon_real_aggs_aapl_5m", f"/v2/aggs/ticker/AAPL/range/5/minute/{start}/{today}", {"adjusted": "true", "sort": "asc", "limit": "300"}),
        ("polygon_real_tickers_search", "/v3/reference/tickers", {"search": "apple", "market": "stocks", "limit": "5"}),
        ("polygon_real_prev_unknown", "/v2/aggs/ticker/ZZZZNOTREAL/prev", {}),
        ("polygon_real_snapshot_aapl", "/v2/snapshot/locale/us/markets/stocks/tickers/AAPL", {}),
    ]
    for name, path, params in calls:
        time.sleep(13)  # 5 requests a minute on the free plan
        save(name, c.get(base + path, params=params, headers=hdr), key, "key sent as a Bearer header")


def fmp(c: httpx.Client) -> None:
    key = os.environ.get("FMP_API_KEY", "")
    print("FMP", "(your key)" if key else "(no key: success shapes stay doc-shaped)")
    base = "https://financialmodelingprep.com/stable"
    save("keytest_fmp_401", c.get(base + "/quote", params={"symbol": "AAPL", "apikey": MADE_UP}), MADE_UP, "made-up key, no account")
    if not key:
        return
    calls = [
        ("fmp_real_quote_aapl", "/quote", {"symbol": "AAPL"}),
        ("fmp_real_profile_aapl", "/profile", {"symbol": "AAPL"}),
        ("fmp_real_key_metrics_aapl", "/key-metrics", {"symbol": "AAPL", "limit": "1"}),
        ("fmp_real_income_aapl", "/income-statement", {"symbol": "AAPL", "limit": "5"}),
        ("fmp_real_balance_aapl", "/balance-sheet-statement", {"symbol": "AAPL", "limit": "5"}),
        ("fmp_real_cashflow_aapl", "/cash-flow-statement", {"symbol": "AAPL", "limit": "5"}),
        ("fmp_real_search_apple", "/search-symbol", {"query": "apple", "limit": "5"}),
        ("fmp_real_income_quarter_aapl", "/income-statement", {"symbol": "AAPL", "period": "quarter", "limit": "4"}),  # the paid-plan answer on a free key
        ("fmp_real_quote_non_us", "/quote", {"symbol": "RELIANCE.NS"}),
    ]
    for name, path, params in calls:
        save(name, c.get(base + path, params={**params, "apikey": key}), key, "apikey query parameter")
        time.sleep(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="twelvedata,alphavantage,polygon,fmp")
    args = ap.parse_args()
    steps = {"twelvedata": twelvedata, "alphavantage": alphavantage, "polygon": polygon, "fmp": fmp}
    with httpx.Client(timeout=30, headers={"User-Agent": "OpenTerm/0 (open-source terminal; fixture recording)"}) as c:
        for name in args.only.split(","):
            steps[name.strip()](c)


if __name__ == "__main__":
    main()
