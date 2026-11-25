"""Gaps closed after the Phase 28-32 build (2026-11-25): EQS formula columns, IBQ by SIC, BIO boards, EU ETS, M&A values.

Pure parsers are tested on recorded text; service paths use a stub (tests never touch the network).
"""

import asyncio
from datetime import date

import pytest

from openterm.fund import service as fs


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
