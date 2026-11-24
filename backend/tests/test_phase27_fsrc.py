"""FSRC (ETF screener): the pure parts only (owner's minimal test bar). No network, no app: the symbol-file parser and the fund-profile
parser run on REAL recorded answers (scripts/record_fsrc.py), and the engine's "send only the new rows" feed is checked on a hand-set state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openterm.etf_screen import FundScreener
from openterm.providers.base import ProviderError
from openterm.providers.etf_parse import fund_from_summary, parse_symbol_file

FIXTURES = Path(__file__).parent / "fixtures"


def _symbol_text() -> str:
    return json.loads((FIXTURES / "nasdaqtrader_etf_trimmed.json").read_text(encoding="utf-8"))["text"]


def test_symbol_file_keeps_etfs_and_skips_stocks_and_test_issues():
    etfs, stamp = parse_symbol_file(_symbol_text())
    symbols = [e["symbol"] for e in etfs]
    # the recording has 34 lines: 30 real ETFs, two stocks (A, AA) and the two exchange TEST ETFs (ZZZTE, ZZZTT)
    assert len(symbols) == 30 and symbols[0] == "SPY" and "AIQU" in symbols
    assert not {"A", "AA", "ZZZTE", "ZZZTT"} & set(symbols)
    assert stamp == "1124202603:04"  # the file's own "File Creation Time" footer
    assert next(e for e in etfs if e["symbol"] == "QQQ")["name"] == "Invesco QQQ Trust, Series 1"


def test_symbol_file_with_a_missing_column_fails_loudly():
    with pytest.raises(ProviderError, match="layout changed"):
        parse_symbol_file("Symbol|Security Name\r\nSPY|SPDR\r\n")  # no ETF / Test Issue columns: never read as "no ETFs"


def test_fund_profile_turns_yahoo_fraction_into_percent_and_keeps_missing_as_none():
    bodies = json.loads((FIXTURES / "yahoo_fundprofile_etf.json").read_text(encoding="utf-8"))["body"]

    def result(sym: str) -> dict:
        return bodies[sym]["quoteSummary"]["result"][0]

    spy = fund_from_summary(result("SPY"))
    # Yahoo says 0.000945 (a fraction); FSRC shows percent so `FEE<0.2` reads like a person says it
    assert spy == {"fee": 0.0945, "aum": spy["aum"], "category": "Large Blend", "family": "State Street Investment Management"}
    assert spy["aum"] > 1e11
    assert fund_from_summary(result("AIQU")) is None  # an ETN Yahoo has no fund profile for: no row, never blanks passed off as data


def _engine() -> FundScreener:
    e = FundScreener(None, None)
    e.names = {"AAA": "Alpha ETF", "BBB": "Beta ETF", "CCC": "Gamma ETF"}
    for sym, fee in (("AAA", 0.1), ("BBB", 0.2)):
        e.rows[sym] = [fee, 1e9, "Large Blend", "Fam", 1000.0]
        e.log.append(sym)
    return e


def test_snapshot_sends_only_rows_added_since_the_last_poll():
    e = _engine()
    first = e.snapshot(None, 0)  # a client with no run id gets everything and is told to start over
    assert first["reset"] and [r[0] for r in first["rows"]] == ["AAA", "BBB"] and first["seq"] == 2
    e.rows["CCC"] = [0.3, 2e9, "Technology", "Fam", 1001.0]
    e.log += ["CCC", "AAA"]  # CCC arrives, AAA is fetched again a day later
    nxt = e.snapshot(first["run"], first["seq"])
    assert not nxt["reset"] and [r[0] for r in nxt["rows"]] == ["CCC", "AAA"] and nxt["loaded"] == 3
    # a position past the end (the server restarted and the log is shorter) or another run id: start over with everything
    assert e.snapshot(first["run"], 99)["reset"] and e.snapshot("someone-else", 2)["reset"]
