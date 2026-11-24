"""Phase 31: the QRY parser and its pure helpers (filter, sort, resample, field search), the notebook example copier and the Excel
workbook writer. No network, no app; the routes are covered by the fixture-mode smoke in the e2e suite."""

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from openterm.macrod import xlsx
from openterm.query import lang as L
from openterm.query import notebook

TODAY = date(2026, 11, 24)
ROOT = Path(__file__).resolve().parents[2]


def test_parse_snapshot_query():
    q = L.parse("QRY last, pe, mcap FOR MEMB:SPY WHERE pe<20 AND sector=Technology SORT mcap ASC LIMIT 50", TODAY)
    assert q.fields == ["last", "pe", "mcap"] and q.universe == "MEMB:SPY" and not q.series
    assert [(c.field, c.op, c.value) for c in q.where] == [("pe", "<", 20.0), ("sector", "=", "TECHNOLOGY")]
    assert q.sort == "mcap" and q.desc is False and q.limit == 50
    assert L.parse("qry divy FOR AAPL,MSFT WHERE divy>3%", TODAY).where[0].value == pytest.approx(0.03)
    assert L.parse("divy FOR SPX WHERE divy>3", TODAY).where[0].value == pytest.approx(0.03)  # a ratio field reads "3" as 3%
    assert L.parse("last FOR AAPL,MSFT", TODAY).universe == "LIST:AAPL,MSFT"
    assert L.parse("last FOR NIFTY50", TODAY).universe == "NIFTY50"


def test_parse_dates_query():
    q = L.parse("QRY close FOR AAPL,FRED:DGS10 DATES -1Y..0 FREQ M", TODAY)
    assert q.series and q.dates == (date(2025, 11, 24), TODAY) and q.freq == "M" and q.universe == "LIST:AAPL,FRED:DGS10"
    assert L.parse("close FOR AAPL DATES 2024-01-31..2024-06-30", TODAY).dates == (date(2024, 1, 31), date(2024, 6, 30))


@pytest.mark.parametrize(("text", "msg"), [
    ("QRY bogus FOR AAPL", "UNKNOWN FIELD"),
    ("QRY last", "FOR IS MISSING"),
    ("QRY close FOR AAPL", "NEED DATES"),
    ("QRY pe FOR AAPL DATES -1Y..0", "WITH DATES USE HISTORY FIELDS"),
    ("QRY last FOR AAPL WHERE pe", "NO COMPARISON"),
    ("QRY last FOR AAPL WHERE pe<cheap", "NOT A NUMBER"),
    ("QRY close FOR AAPL DATES 0..-1Y", "START MUST BE BEFORE"),
    ("QRY last FOR AAPL LIMIT 5000", "LIMIT"),
])
def test_parse_errors_are_plain_words(text, msg):
    with pytest.raises(L.QueryError, match=msg):
        L.parse(text, TODAY)


def test_filter_sort_and_missing_values():
    rows = [{"symbol": "A", "pe": 10.0, "sector": "TECHNOLOGY"}, {"symbol": "B", "pe": None, "sector": "Energy"}, {"symbol": "C", "pe": 30.0}]
    conds = L.parse("pe FOR X,Y WHERE pe<20", TODAY).where
    assert [r["symbol"] for r in rows if L.passes(r, conds)] == ["A"]  # None fails: never read as zero
    assert [r["symbol"] for r in rows if L.passes(r, L.parse("pe FOR X WHERE sector=energy", TODAY).where)] == ["B"]
    assert [r["symbol"] for r in L.sort_rows(rows, "pe", True)] == ["C", "A", "B"]  # the missing value goes last


def test_resample_takes_the_last_value_per_period():
    pts = [("2026-01-02", 1.0), ("2026-01-30", 2.0), ("2026-02-02", 3.0), ("2026-02-27", None), ("2026-02-26", 4.0)]
    assert L.resample(sorted(pts), "M") == [("2026-01-30", 2.0), ("2026-02-26", 4.0)]
    assert L.resample(pts, "D") == pts


def test_field_catalog_search():
    assert {f.name for f in L.search_fields("valuation")} >= {"pe", "pb", "ps"}
    assert all(f.source and f.unit and f.freq for f in L.FIELDS.values())


def test_notebook_examples_copy_once(tmp_path):
    assert notebook.copy_examples(tmp_path) == sorted(p.name for p in notebook.EXAMPLES.glob("*.ipynb"))
    for p in tmp_path.glob("*.ipynb"):
        assert json.loads(p.read_text(encoding="utf-8"))["nbformat"] == 4
    (tmp_path / "01_quotes_and_history.ipynb").write_text("{}", encoding="utf-8")
    assert notebook.copy_examples(tmp_path) == []  # an existing file (the user's edits) is never overwritten
    assert (tmp_path / "01_quotes_and_history.ipynb").read_text(encoding="utf-8") == "{}"


def test_excel_workbook_writer_round_trips(tmp_path):
    spec = importlib.util.spec_from_file_location("mkxl", ROOT / "scripts" / "make_excel_workbook.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "x.xlsx"
    mod.write(out, mod.build(8123))
    data = out.read_bytes()
    assert xlsx.sheet_names(data) == ["Quotes", "Query", "History", "Read me"]
    assert xlsx.read_sheet(data, "Quotes")[1][0] == "AAPL"
    assert b"127.0.0.1:8123/api/xl/last" in __import__("zipfile").ZipFile(out).read("xl/worksheets/sheet1.xml")
