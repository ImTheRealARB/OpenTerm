"""Phase 22: symbol math (parser, printer, aligner) and IMPORT intraday CSV. Minimal bar: the pure parts plus one API round trip."""

import math

import pytest

from openterm import symmath
from openterm.bt import csvimport
from openterm.symmath import Bin, Frame, Num, Sym, SymMathError, align, apply, parse_formula, render


# --- parser and the minus rule ------------------------------------------------------------------
@pytest.mark.parametrize("text", ["AAPL", "BRK-B", "BTC-USD", "BAJAJ-AUTO.NS", " aapl "])
def test_one_symbol_is_not_a_formula(text):
    assert parse_formula(text) is None


def test_minus_rule_and_precedence():
    assert parse_formula("GLD-SLV") == Bin("-", Sym("GLD"), Sym("SLV"))
    assert parse_formula("ES=F-NQ=F") == Bin("-", Sym("ES=F"), Sym("NQ=F"))
    assert parse_formula("BTC-USD - ETH-USD") == Bin("-", Sym("BTC-USD"), Sym("ETH-USD"))
    # * binds tighter than -, so 2*GLD-SLV is (2*GLD) - SLV
    assert parse_formula("2*GLD-SLV") == Bin("-", Bin("*", Num(2.0), Sym("GLD")), Sym("SLV"))


def test_render_round_trips():
    for text in ("2*GLD-SLV", "AAPL/(MSFT+GOOG)", "A-(B-C)", "-(AAPL+MSFT)/2", "BRK-B/BTC-USD"):
        tree = parse_formula(text)
        assert parse_formula(render(tree)) == tree


@pytest.mark.parametrize("text", ["AAPL/", "(AAPL", "2*3", "AAPL MSFT/2", "A/B/C/D/E/F/G+H"])
def test_bad_formulas_raise(text):
    with pytest.raises(SymMathError):
        parse_formula(text)


# --- aligner and evaluator ----------------------------------------------------------------------
def _frame(days: list[int], close: list[float]) -> Frame:
    t = [d * 86_400 for d in days]
    return Frame(t, close, close, close, close, "UTC")


def test_inner_join_counts_dropped_bars_and_divides_per_bar():
    a = _frame([1, 2, 3, 4], [10.0, 20.0, 30.0, 40.0])
    b = _frame([2, 3, 4, 5], [2.0, 0.0, 4.0, 5.0])
    al = align({"A": a, "B": b}, "1d")
    assert al.t == [2 * 86_400, 3 * 86_400, 4 * 86_400]
    assert al.dropped_join == 2  # day 1 (only A) and day 5 (only B)
    out = apply(parse_formula("A/B"), al)
    assert out.c == [10.0, 10.0] and out.dropped_zero == 1  # day 3 divides by zero: dropped and counted, never shown as inf
    assert all(math.isfinite(x) for x in out.h)


def test_no_common_bars_is_an_error():
    with pytest.raises(SymMathError, match="NO COMMON BARS"):
        align({"A": _frame([1, 2], [1.0, 1.0]), "B": _frame([5, 6], [1.0, 1.0])}, "1d")


def test_history_formula_over_the_api(client):
    r = client.get("/api/history", params={"symbol": "SYN0001/SYN0002", "range": "1Y"}).json()
    assert r["source"] == "formula" and r["formula"]["text"] == "SYN0001/SYN0002"
    assert [leg["symbol"] for leg in r["formula"]["legs"]] == ["SYN0001", "SYN0002"]
    assert len(r["data"]["t"]) > 100 and r["data"]["symbol"] == "SYN0001/SYN0002"
    bad = client.get("/api/history", params={"symbol": "SYN0001/", "range": "1Y"})
    assert bad.status_code == 400


def test_stored_synthetic(client):
    put = client.post("/api/bt/synth", json={"name": "pair", "formula": "syn0001 / syn0002"}).json()
    assert put["name"] == "PAIR" and put["formula"] == "SYN0001/SYN0002"
    r = client.get("/api/history", params={"symbol": "PAIR", "range": "1Y"}).json()
    assert r["data"]["symbol"] == "PAIR" and r["formula"]["name"] == "PAIR"
    assert client.post("/api/bt/synth", json={"name": "LOOP", "formula": "PAIR*2"}).status_code == 400  # one level deep only
    assert client.delete("/api/bt/synth/PAIR").json() == {"deleted": "PAIR"}


# --- IMPORT intraday ----------------------------------------------------------------------------
INTRADAY = """date,open,high,low,close,volume
2026-01-02T09:30:00-05:00,10,11,9,10.5,100
2026-01-02T09:35:00-05:00,10.5,11,10,10.8,120
2026-01-02T09:40:00-05:00,10.8,12,10.7,11.9,90
2026-01-05T09:30:00-05:00,12,12.5,11.5,12.1,80
"""


def test_intraday_csv_reads_spacing_and_zone():
    cols = csvimport.parse_bars(INTRADAY)
    assert cols["iv"] == "5m" and cols["step"] == 300
    assert cols["t"][0] == 1767364200  # 2026-01-02 14:30 UTC
    naive = INTRADAY.replace("-05:00", "")
    with pytest.raises(csvimport.CsvError, match="HAS NO ZONE"):
        csvimport.parse_bars(naive)
    assert csvimport.parse_bars(naive, "america/new_york")["t"] == cols["t"]  # zone name matched ignoring case


def test_intraday_mixed_spacing_is_refused_and_daily_files_are_unchanged():
    mixed = INTRADAY.replace("09:40:00", "09:42:00")
    with pytest.raises(csvimport.CsvError, match="MIXED BAR SPACING"):
        csvimport.parse_bars(mixed)
    daily = csvimport.parse_bars("date,open,high,low,close\n2026-01-02 16:00,1,1,1,1\n2026-01-05 16:00,2,2,2,2\n")
    assert "iv" not in daily and daily["d"] == ["2026-01-02", "2026-01-05"]


def test_symmath_has_no_heavy_imports():
    assert "pandas" not in symmath.__dict__ and "numpy" not in symmath.__dict__


# --- watchlist flags and sections ---------------------------------------------------------------
def test_watchlist_meta_round_trip(client):
    client.put("/api/watchlists/P22", json={"symbols": ["AAPL", "JPM"]})
    meta = {"flags": {"AAPL": "RED"}, "sections": [{"before": "JPM", "title": "Banks"}]}
    assert client.put("/api/watchlists/P22/meta", json=meta).json()["meta"] == meta
    assert client.get("/api/watchlists/P22").json()["meta"] == meta
    bad = client.put("/api/watchlists/P22/meta", json={"flags": {"MSFT": "RED"}, "sections": []})
    assert bad.status_code == 400 and "MSFT" in bad.json()["error"]  # a symbol that is not in the list
    assert client.put("/api/watchlists/P22/meta", json={"flags": {"AAPL": "PINK"}, "sections": []}).status_code == 400
