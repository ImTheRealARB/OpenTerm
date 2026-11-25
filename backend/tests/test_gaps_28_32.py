"""Gaps closed after the Phase 28-32 build (2026-11-25): EQS formula columns, IBQ by SIC, BIO boards, EU ETS, M&A values.

Pure parsers are tested on recorded text; service paths use a stub (tests never touch the network).
"""

import asyncio
import json
import time
from datetime import date
from pathlib import Path

import pytest

from openterm.fund import service as fs
from openterm.fund import sic


class _Svc:
    """Just enough of DataService for Fund.fn_eqsfund: the screener universe and nothing else."""

    async def screener(self):
        return {"data": {"columns": ["symbol", "name", "mcap", "sector", "industry"], "sectors": ["", "Tech"], "industries": ["", "Semis"],
                         "rows": [["AAPL", "Apple", 3e12, 1, 1], ["NOSEC", "No Filer", 1e9, 1, 1], ["BRK/B", "Berkshire", 9e11, 1, 1]]}}


class _FundStub(fs.Fund):
    """Fund with the SEC frames and the ticker map replaced by small dicts."""

    def __init__(self, revenue_filers: int):
        super().__init__(_Svc())  # type: ignore[arg-type]
        self.n = revenue_filers

    @property
    def sec(self):  # type: ignore[override]
        class _Sec:
            async def tickers_by_cik(self_inner):
                return {1: ["AAPL"], 2: ["BRK-B"]}

        return _Sec()

    async def concept_year(self, concept: str, year: int) -> dict:
        data = {
            "revenue": {1: {"val": 1000.0}, 2: {"val": 500.0}},
            "net_income": {1: {"val": 250.0}, 2: {"val": 50.0}},
            "operating_income": {1: {"val": 300.0}},
            "equity": {1: {"val": 100.0}, 2: {"val": -5.0}},
            "liabilities": {1: {"val": 450.0}, 2: {"val": 20.0}},
        }[concept]
        if concept == "revenue" and year == 2023 - 1:
            return {1: {"val": 800.0}}
        pad = {1000 + i: {"val": 1.0} for i in range(self.n)} if concept == "revenue" else {}
        return {**data, **pad}


def test_eqsfund_percent_units_and_ticker_join():
    out = asyncio.run(_FundStub(0).fn_eqsfund(year="2023"))["data"]
    assert out["fields"] == ["MARGIN", "OPMARGIN", "ROE", "GROWTH", "DE"] and out["year"] == 2023
    # AAPL: margin 25%, op margin 30%, ROE 250%, growth 25%, liabilities / equity 4.5
    assert out["rows"]["AAPL"] == pytest.approx([25.0, 30.0, 250.0, 25.0, 4.5])
    # BRK/B in the screener joins BRK-B in the SEC map; negative equity gives no ROE / DE (None), growth has no prior year
    brk = out["rows"]["BRK/B"]
    assert brk[0] == pytest.approx(10.0) and brk[2] is None and brk[4] is None and brk[3] is None
    assert "NOSEC" not in out["rows"]  # a non-filer is absent, so a fundamentals filter can never pass it


def test_eqsfund_falls_back_one_year_when_most_filers_are_missing(monkeypatch):
    years: list[int] = []
    stub = _FundStub(0)
    orig = stub.concept_year

    async def spy(concept, year):
        years.append(year)
        return await orig(concept, year)

    monkeypatch.setattr(stub, "concept_year", spy)
    out = asyncio.run(stub.fn_eqsfund())["data"]  # no year typed and < 3,000 revenue filers: current year - 1 is "not filed yet"
    assert out["year"] == date.today().year - 2 and any("NOT FILED BY MOST COMPANIES" in n for n in out["notes"])


# --- SIC grouping for IBQ (recorded SEC pages, trimmed to Apple / Microsoft / Berkshire / Meta) -------------------------------------------



def _fx(name: str) -> str:
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))["text"]


def test_sic_list_and_company_pages_parse():
    table = sic.parse_sic_table(_fx("sec_sic_list"))
    assert table[3571]["title"] == "ELECTRONIC COMPUTERS" and table[7372]["title"] == "SERVICES-PREPACKAGED SOFTWARE"
    assert sic.parse_atom(_fx("sec_sic_3571")) == [{"cik": 320193, "sic": 3571, "name": "Apple Inc."}]
    assert sic.parse_atom(_fx("sec_sic_7372"))[0]["cik"] == 789019
    with pytest.raises(ValueError, match="NO SIC TABLE"):
        sic.parse_sic_table("<html>layout changed</html>")
    with pytest.raises(ValueError, match="DID NOT PARSE"):
        sic.parse_atom("<feed")


def test_sic_divisions():
    assert sic.division(3571) == ("D", "MANUFACTURING") and sic.division(100) == ("A", "AGRICULTURE, FORESTRY, FISHING")
    assert sic.division(6331)[0] == "H" and sic.division(7372)[0] == "I" and sic.division(9999)[0] == "J"
    assert sic.division(1900)[0] == "?"  # no major group 19 in the manual: said, not guessed


def test_ibq_by_sic_builds_the_map_then_groups(client):
    """First call starts the background build and says so; once it is done the same call returns the roll-up (fixtures: four filers)."""
    first = client.get("/api/fund/ibq", params={"by": "SIC", "year": "2024"}).json()
    assert first["data"]["title"].startswith("IBQ") and any("SIC MAP" in n for n in first["data"].get("notes", [])) or first["data"].get("sections")
    for _ in range(60):
        body = client.get("/api/fund/ibq", params={"by": "SIC", "year": "2024"}).json()
        if body["data"].get("sections"):
            break
        time.sleep(0.25)
    groups = {r["group"] for r in body["data"]["sections"][0]["rows"]}
    assert "3571 ELECTRONIC COMPUTERS" in groups and "7372 SERVICES-PREPACKAGED SOFTWARE" in groups
    div = client.get("/api/fund/ibq", params={"by": "DIV", "year": "2024"}).json()["data"]["sections"][0]["rows"]
    assert {"D MANUFACTURING", "H FINANCE, INSURANCE, REAL ESTATE", "I SERVICES"} <= {r["group"] for r in div}


# --- BIO boards from DEF 14A (recorded SEC full-text answer for "Timothy Cook", 2023-2025) ------------------------------------------------


def test_proxy_phrase_from_sec_owner_names():
    from openterm.filings import people

    assert people.proxy_phrase("COOK TIMOTHY D") == "Timothy Cook"
    assert people.proxy_phrase("O'BRIEN SEAN") == "Sean O'Brien"
    assert people.proxy_phrase("Vanguard Group Inc") is None and people.proxy_phrase("SOROS FUND MANAGEMENT LLC") is None
    assert people.proxy_phrase("Madonna") is None


def test_board_rows_group_proxies_by_company():
    from openterm.filings import fts, people

    hits = fts.parse_fts(json.loads((Path(__file__).parent / "fixtures" / "fts_bio_proxy_timothy_cook.json").read_text(encoding="utf-8"))["body"])["hits"]
    rows = people.board_rows(hits)
    assert rows and all(r["proxies"] >= 1 and r["cik"] for r in rows)
    assert [r["proxies"] for r in rows] == sorted((r["proxies"] for r in rows), reverse=True)
    assert len({r["cik"] for r in rows}) == len(rows)  # one row per company
    out = people.build_payload("COOK", [], 0, "SEC", {"phrase": "Timothy Cook", "rows": rows, "total": len(hits)})
    assert [s["id"] for s in out["sections"]] == ["filings", "boards"] and any("TEXT MATCH" in n for n in out["notes"])
    skipped = people.build_payload("X", [], 0, "SEC", {"phrase": None, "why": "THE OWNER IS AN ENTITY"})
    assert any(n.startswith("BOARDS NOT SEARCHED") for n in skipped["notes"]) and len(skipped["sections"]) == 1


# --- ETS: EU emissions trading (recorded Union Registry files, trimmed to the account holders containing "alcoa") ---------------------------


def _b64(name: str) -> bytes:
    import base64

    return base64.b64decode(json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))["b64"])


def test_ets_join_matches_holders_by_core_name_and_keeps_blanks_blank():
    from openterm.filings import ets

    ops = ets.parse_operators(_b64("eu_ets_operators_daily"))
    ver = ets.parse_verified(_b64("eu_ets_verified_2024"), 2024)
    rows = ets.installations(ops, ver, "Alcoa Corp")
    names = {r["installation"] for r in rows}
    assert any(n.startswith("Alcoa Mosj") for n in names) and len(rows) >= 4
    assert [r["tons"] for r in rows if r["tons"] is not None] == sorted((r["tons"] for r in rows if r["tons"] is not None), reverse=True)
    blank = [r for r in rows if r["tons"] is None]
    assert blank and all(r["tons"] != 0 for r in blank)  # -1 (blank) and 'Excluded' stay empty, never zero
    assert ets.installations(ops, ver, "Dow Inc") == []  # nothing in the trimmed file starts with DOW
    out = ets.build_payload("AA", "Alcoa Corp", 2024, rows, "EU")
    assert any("NEVER READ AS ZERO" in n for n in out["notes"]) and out["sections"][0]["id"] == "installations"


def test_ets_holder_rule_is_word_for_word_and_inputs_are_checked():
    from openterm.filings import ets

    assert ets.holder_matches("Alcoa Norway AS", "ALCOA") and not ets.holder_matches("Dowlais Group plc", "DOW") and not ets.holder_matches("X", "")
    with pytest.raises(ValueError, match="NEW SHAPE"):
        ets.parse_download_list({"not": "a list"})
    with pytest.raises(ValueError, match="NOT A GZIP"):
        ets.parse_operators(b"not gzip")
    with pytest.raises(ValueError, match="NO COLUMNS FOR 1999"):
        ets.parse_verified(_b64("eu_ets_verified_2024"), 1999)


def test_ets_route_in_fixture_mode(client):
    d = client.get("/api/filings/ets", params={"symbol": "AA", "year": 2024}).json()["data"]
    assert d["sections"][0]["rows"] and "EMISSIONS ONLY, NO SCORE" in d["notes"][0]
    bad = client.get("/api/filings/ets", params={"symbol": "AA", "year": 2023})
    assert bad.status_code >= 400  # only 2024 is recorded: another year is "not recorded", never invented
