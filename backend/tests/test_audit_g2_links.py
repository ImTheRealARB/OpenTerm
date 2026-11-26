"""Audit H-14: one CSV formula neutraliser (`openterm/csvsafe.py`) shared by BT EXPORT and the Excel bridge."""

from __future__ import annotations

import pytest

from openterm.bt.export import run_csv
from openterm.csvsafe import neutralize
from openterm.query_routes import _csv

# Cells that spreadsheets run as formulas. The old rule looked one character past +/- and let these through.
EVIL = ["+1+cmd|' /C calc'!A0", "-1+2", "-2+HYPERLINK(1)", "+.5+cmd", "=1+1", "@SUM(A1)", "\tx", "\rx", "+cmd", "-cmd"]
# Strict plain numbers (a percent figure too) stay numeric: negative P&L must not turn into text.
NUMBERS = ["-1", "+1", "-1.5", "+3.4%", "-.5", "1e5", "-1.2E-3", "5."]


@pytest.mark.parametrize("cell", EVIL)
def test_formula_cells_get_a_quote(cell):
    assert neutralize(cell) == "'" + cell


@pytest.mark.parametrize("cell", NUMBERS + ["AAPL", "", "Apple, Inc."])
def test_plain_cells_stay(cell):
    assert neutralize(cell) == cell


def test_real_numbers_and_none_are_never_touched():
    assert neutralize(-5) == -5
    assert neutralize(-0.25) == -0.25
    assert neutralize(True) is True
    assert neutralize(None) is None


def test_bt_export_uses_it():
    run = {"trades": [{"symbol": "-1+cmd|x", "pnl": -12.5, "exit_reason": "+1+2"}], "equity": [], "metrics": {}}
    text = run_csv(run, "trades")
    assert "'-1+cmd|x" in text and "'+1+2" in text
    assert "-12.5" in text and "'-12.5" not in text


def test_excel_bridge_csv_neutralises_upstream_strings():
    # The QRY / history CSV carries provider text (names, labels): it is the injection path.
    body = _csv([["name", "last"], ["=HYPERLINK(\"http://x\")", -3.5], ["-1+2", "+4"]], "t").body.decode()
    assert "'=HYPERLINK" in body
    assert "'-1+2" in body
    assert ",-3.5" in body  # a real negative number is not quoted
    assert ",+4" in body  # a plain numeric string stays
