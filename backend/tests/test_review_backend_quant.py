"""Review sprint, backend-quant: one malformed row must not take down a whole parsed answer."""

from __future__ import annotations

from openterm.options import chain as oc
from openterm.rates import parse as rp

IDX = {"result": {"index_price": 90000}}
GOOD = {"instrument_name": "BTC-27NOV26-90000-C", "mark_iv": 50, "underlying_price": 90000}


def _book(*extra: dict) -> dict:
    return {"result": [*extra, GOOD]}


def test_deribit_row_without_underlying_price_is_skipped():
    out = oc.parse_deribit(_book({"instrument_name": "BTC-27NOV26-80000-C", "mark_iv": 50}), IDX, "BTC", "x")
    assert [c["strike"] for c in out["expiries"][0]["calls"]] == [90000.0]


def test_deribit_row_with_text_iv_is_skipped():
    out = oc.parse_deribit(_book({"instrument_name": "BTC-27NOV26-80000-C", "mark_iv": "n/a", "underlying_price": 1}), IDX, "BTC", "x")
    assert [c["strike"] for c in out["expiries"][0]["calls"]] == [90000.0]


def test_deribit_decimal_strike_with_d_separator_is_parsed_not_fatal():
    row = {"instrument_name": "XRP_USDC-27NOV26-2d5-C", "mark_iv": 50, "underlying_price": 3}
    out = oc.parse_deribit(_book(row), IDX, "BTC", "x")
    assert 2.5 in [c["strike"] for c in out["expiries"][0]["calls"]]


def test_mof_impossible_date_row_is_skipped_not_fatal():
    curve = rp.parse_mof("Date,1Y,2Y\n2026/2/30,1.0,2.0\n2026/2/27,1.1,2.1\n")
    assert curve["dates"] == ["2026-02-27"]
