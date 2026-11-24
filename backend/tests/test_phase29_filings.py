"""Phase 29 filings functions (FTS, MA, LEGAL, BIO, RELS, ESG): the pure parsers and table builders, fed with the recorded fixtures.
No network, no app. The routes and providers are covered by the fixture-mode smoke in the e2e suite."""

import json
from datetime import date
from pathlib import Path

import pytest

from openterm.filings import esg, fts, legal, ma, people, rels

FIX = Path(__file__).parent / "fixtures"


def load(name: str):
    rec = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    return rec["text"] if "text" in rec else rec["body"]


# --- FTS ---------------------------------------------------------------------------------------------------------------------------


def test_fts_params_and_errors():
    p = fts.build_params('  "going concern" ', "10-K", "2024-01-01", "", 320193, today=date(2025, 2, 3))
    assert p == {"q": '"going concern"', "forms": "10-K", "ciks": "0000320193", "dateRange": "custom", "startdt": "2024-01-01", "enddt": "2025-02-03"}
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        fts.build_params("x", start="01/02/2024")
    with pytest.raises(ValueError, match="GIVE WORDS"):
        fts.build_params()


def test_fts_display_names_and_hits():
    assert fts.split_display("Apple Inc.  (AAPL)  (CIK 0000320193)") == {"name": "Apple Inc.", "tickers": ["AAPL"], "cik": 320193}
    assert fts.split_display("COOK TIMOTHY D  (CIK 0001214156)") == {"name": "COOK TIMOTHY D", "tickers": [], "cik": 1214156}
    out = fts.parse_fts(load("fts_going_concern_10k"))
    assert out["total"] > len(out["hits"]) > 0
    h = out["hits"][0]
    assert h["url"].startswith("https://www.sec.gov/Archives/edgar/data/") and h["index_url"].endswith("-index.htm")
    with pytest.raises(ValueError, match="UNKNOWN SHAPE"):
        fts.parse_fts({"error": "x"})


# --- MA ----------------------------------------------------------------------------------------------------------------------------


def test_ma_deal_forms():
    assert ma.is_deal("8-K", "1.01,9.01") and ma.is_deal("8-K/A", "2.01") and not ma.is_deal("8-K", "2.02,9.01")
    assert ma.is_deal("SC TO-T/A", None) and ma.is_deal("DEFM14A", "") and not ma.is_deal("10-K", None)
    assert ma.what("8-K", "1.01,9.01") == "8-K: 1.01 Material agreement"


def test_ma_rows_from_the_market_search_leave_value_empty():
    rows = ma.rows_from_fts(fts.parse_fts(load("fts_ma_market"))["hits"])
    assert rows and all(r["form"].split("/")[0] in {"SC TO-T", "DEFM14A", "S-4", "425"} for r in rows)
    table = ma.build_payload(None, "MA", rows, "x", "ALL")
    assert table["sections"][0]["note"] == ma.VALUE_NOTE and all(r["value"] is None for r in table["sections"][0]["rows"])


# --- LEGAL -------------------------------------------------------------------------------------------------------------------------


def test_legal_name_matching():
    assert legal.core_name("LENNAR CORP /NEW/") == "LENNAR" and legal.core_name("Meta Platforms, Inc.") == "META PLATFORMS"
    assert legal.name_matches("Alcoa Corp", "Alcoa Inc. and John Doe") and not legal.name_matches("Alcoa Corp", "Alcoholics Anonymous LLC")
    assert not legal.name_matches("X Corp", "X Holdings")  # a name of 1 character matches nothing


def test_legal_rss_with_a_bare_ampersand():
    # The SEC's admin feed prints "Coburn & Meredith, Inc." unescaped (a real recording): the parser must still read it.
    items = legal.parse_rss(load("sec_admin_proceedings_rss"), "ADMIN")
    assert any("Coburn & Meredith" in i["title"] for i in items)
    assert all(i["date"] for i in items)
    with pytest.raises(ValueError, match="NOT XML"):
        legal.parse_rss("<html>nope", "ADMIN")


def test_legal_dockets_doc_shape():
    dockets = legal.parse_dockets(load("courtlistener_dockets_docshape"))
    rows = legal.court_rows("Exampleco Inc", dockets)
    assert len(rows) == 2 and rows[0]["url"].startswith("https://www.courtlistener.com/docket/") and rows[0]["match"] == "NAME MATCH"
    assert legal.court_rows("Someone Else Corp", dockets) == []


# --- BIO ---------------------------------------------------------------------------------------------------------------------------


def test_bio_target_and_roles():
    assert people.parse_target("1214156") == (1214156, "") and people.parse_target('"COOK TIMOTHY"') == (None, "COOK TIMOTHY")
    hits = fts.parse_fts(load("fts_bio_1214156"))["hits"]
    rows = people.rows_from_fts(hits, 1214156, "")
    assert {r["owner"] for r in rows} == {"COOK TIMOTHY D"} and {"Apple Inc.", "NIKE, Inc."} <= {r["issuer"] for r in rows}
    # asked by name: the owner is the filer whose name holds every word; with no match the owner stays unidentified
    assert people.split_roles(hits[0]["names"], None, "cook timothy")[0] == ["COOK TIMOTHY D"]
    assert people.split_roles(hits[0]["names"], None, "jobs steve")[0] == []


# --- RELS --------------------------------------------------------------------------------------------------------------------------


def test_rels_share_classes():
    rows = rels.parse_exchange_file(load("sec_company_tickers_exchange"))
    assert [r["ticker"] for r in rels.siblings(rows, 1652044)] == ["GOOGL", "GOOG"]
    with pytest.raises(ValueError, match="UNKNOWN"):
        rels.parse_exchange_file({"data": []})


# --- ESG ---------------------------------------------------------------------------------------------------------------------------


def test_esg_stated_share_and_totals():
    assert esg.stated_share("ALCOA CORP (60%); ALCOA CORP (60%)", "Alcoa Corp") == 60.0  # a repeated entry counts once
    assert esg.stated_share("COUNTY OF BLOUNT TENNESSEE (40%); CITY OF ALCOA TENNESSEE (60%)", "Alcoa Corp") is None  # "CITY OF ALCOA" is not ALCOA
    rows = esg.facilities(load("epa_ghgrp_alcoa_2023"), "Alcoa Corp")
    assert len(rows) == 8 and rows[0]["co2e"] >= (rows[-1]["co2e"] or 0) and all(r["match"] == "NAME MATCH" for r in rows)
    assert all(r["weighted"] is None or r["weighted"] <= r["co2e"] for r in rows)
