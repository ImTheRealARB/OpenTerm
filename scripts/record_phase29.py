"""Records the keyless Phase 29 filings fixtures (FTS, MA, LEGAL, BIO, RELS, ESG). No key is used, nothing secret is stored.

Run from backend/:  uv run python ../scripts/record_phase29.py [name ...]      (default: every recording)
Names: fts ma bio rss tickers figi epa

Writes backend/tests/fixtures/<name>.json as {"status", "body"} (JSON) or {"status", "text", "content_type"} (XML), like every other
recording. Big answers are trimmed and each trim is noted next to the line that makes it. A source that does not answer stops that
recording (nothing is invented). The SEC asks for a User-Agent with a contact: this script sends a placeholder one, which is fine
for a handful of requests (the app itself sends the owner's SEC_USER_AGENT).
CourtListener is NOT recorded here: it needs a key, so its fixture is doc-shaped and named `*_docshape*` (NOT A RECORDING).
"""

import json
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
SEC_UA = {"User-Agent": "OpenTerm-dev noreply@example.com", "Accept-Encoding": "gzip, deflate"}
FTS = "https://efts.sec.gov/LATEST/search-index"


def save_json(name: str, body) -> None:
    (OUT / f"{name}.json").write_text(json.dumps({"status": 200, "body": body}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


def save_text(name: str, text: str, content_type: str) -> None:
    (OUT / f"{name}.json").write_text(
        json.dumps({"status": 200, "text": text, "content_type": content_type}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


def fts(params: dict, keep: int) -> dict:
    """One full-text search answer, cut to the first `keep` hits (total and the hit shape stay real)."""
    for attempt in range(4):  # the SEC search answers an odd HTTP 500 now and then; the same request works a moment later
        r = httpx.get(FTS, params=params, headers=SEC_UA, timeout=40)
        if r.status_code < 500:
            break
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()
    body = r.json()
    body["hits"]["hits"] = body["hits"]["hits"][:keep]  # TRIM: first hits only
    body.pop("aggregations", None)  # TRIM: the filter counts are not used
    time.sleep(0.5)
    return body


def rec_fts() -> None:
    # FTS panel: a phrase in 10-K filings of 2024 (the fixture is served for every phrase, labelled by the panel as a replay).
    save_json("fts_going_concern_10k", fts({"q": '"going concern"', "forms": "10-K", "dateRange": "custom", "startdt": "2024-01-01", "enddt": "2024-12-31"}, 25))


def rec_ma() -> None:
    # MA with no symbol: tender offers, merger proxies, S-4s and 425s filed in the last quarter of 2024.
    save_json("fts_ma_market", fts({"forms": "SC TO-T,DEFM14A,S-4,425", "dateRange": "custom", "startdt": "2024-10-01", "enddt": "2024-12-31"}, 30))


def rec_bio() -> None:
    # BIO: Form 3 / 4 / 5 filings where CIK 1214156 (a reporting owner) appears. The owner is a director of more than one issuer.
    save_json("fts_bio_1214156", fts({"ciks": "0001214156", "forms": "3,4,5", "dateRange": "custom", "startdt": "2023-01-01", "enddt": "2025-12-31"}, 30))


def rec_rss() -> None:
    # LEGAL: the two current SEC enforcement feeds (the last 25 items each). The older /rss/litigation/*.xml files are frozen in 2023.
    for name, url in (("sec_litigation_releases_rss", "https://www.sec.gov/enforcement-litigation/litigation-releases/rss"),
                      ("sec_admin_proceedings_rss", "https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss")):
        r = httpx.get(url, headers=SEC_UA, timeout=40, follow_redirects=True)
        r.raise_for_status()
        save_text(name, r.text, r.headers.get("content-type", "application/rss+xml"))
        time.sleep(0.5)


# Tickers kept from company_tickers_exchange.json: issuers with more than one listed class, plus a few single-class ones.
KEEP_TICKERS = {"GOOGL", "GOOG", "BRK-A", "BRK-B", "UAA", "UA", "FOXA", "FOX", "NWSA", "NWS", "LEN", "LEN-B", "AAPL", "MSFT", "META", "NKE", "ALCOA", "AA"}


def rec_tickers() -> None:
    r = httpx.get("https://www.sec.gov/files/company_tickers_exchange.json", headers=SEC_UA, timeout=60)
    r.raise_for_status()
    body = r.json()
    rows = [row for row in body["data"] if row[2] in KEEP_TICKERS]  # TRIM: the listed tickers only (the real file has ~10,000 rows)
    save_json("sec_company_tickers_exchange", {"fields": body["fields"], "data": rows})


def rec_figi() -> None:
    # RELS: every listing of the ticker GOOGL (OpenFIGI, keyless).
    job = {"idType": "TICKER", "idValue": "GOOGL", "marketSecDes": "Equity"}
    r = httpx.post("https://api.openfigi.com/v3/mapping", json=[job], headers={"Content-Type": "application/json", "User-Agent": "OpenTerm"}, timeout=30)
    r.raise_for_status()
    answer = r.json()[0]
    answer["data"] = answer["data"][:20]  # TRIM: first 20 listings
    save_json("openfigi_ticker_googl", {"GOOGL": answer})


def rec_epa() -> None:
    # ESG: EPA GHGRP facilities whose parent company text contains ALCOA (reporting year 2023) joined to their emissions rows.
    url = "https://data.epa.gov/efservice/PUB_DIM_FACILITY/PARENT_COMPANY/CONTAINING/ALCOA/YEAR/2023/PUB_FACTS_SECTOR_GHG_EMISSION/rows/0:1999/JSON"
    r = httpx.get(url, headers={"User-Agent": "OpenTerm-dev"}, timeout=90)
    r.raise_for_status()
    keep = ("facility_id", "facility_name", "city", "state", "year", "parent_company", "sector_id", "subsector_id", "gas_id", "co2e_emission")
    rows = [{k: row.get(k) for k in keep} for row in r.json()]  # TRIM: only the columns the parser reads
    save_json("epa_ghgrp_alcoa_2023", rows)


STEPS = {"fts": rec_fts, "ma": rec_ma, "bio": rec_bio, "rss": rec_rss, "tickers": rec_tickers, "figi": rec_figi, "epa": rec_epa}

if __name__ == "__main__":
    for step in sys.argv[1:] or list(STEPS):
        STEPS[step]()
