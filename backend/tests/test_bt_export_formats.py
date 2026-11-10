"""BT EXPORT additions: MQL5 Expert Advisor, PDF report, XLSX workbook. Structure tests, no network, no MT5 compiler."""

import io
import re
import time
import zipfile

import pytest

from openterm.bt import export_report
from openterm.bt.export_mql5 import mql5_expert
from openterm.bt.rules import RuleError

LABEL = "HISTORICAL SIMULATION, NOT A FORECAST"


def _ea(rule, **kw):
    opts = {"short": False, "cash": 50_000, "fees_bps": 10, "symbols": ["AAPL"], "interval": "1D"} | kw
    return mql5_expert(rule, **opts)


def test_mql5_sample_rule_uses_standard_calls():
    ea = _ea("SMA20>SMA50")
    for text in (LABEL, "GENERATED", "UNTESTED ON A LIVE ACCOUNT", "#include <Trade/Trade.mqh>", "CTrade   trade;",
                 "iMA(_Symbol, TF, 20, 0, MODE_SMA, PRICE_CLOSE)", "iMA(_Symbol, TF, 50, 0, MODE_SMA, PRICE_CLOSE)",
                 "CopyBuffer(handle, 0, shift, 1, buf)", "GT(BufValue(h_sma20, 1), BufValue(h_sma50, 1))",
                 "int OnInit()", "void OnTick()", "trade.Buy(", "input bool            AllowShort = false;",
                 "PERIOD_D1", "IndicatorRelease(h_sma20)"):
        assert text in ea, text
    assert ea.count("{") == ea.count("}")


def test_mql5_rsi_ema_cross_and_other_terms():
    ea = _ea("EMA12>=EMA26 AND RSI14<30 OR HIGH20>LOW10 AND RET5<0.05 AND CLOSE>100 AND VOLUME>1000", interval="1W", short=True)
    for text in ("iRSI(_Symbol, TF, 14, PRICE_CLOSE)", "MODE_EMA", "GE(BufValue(h_ema12, 1), BufValue(h_ema26, 1))",
                 "LT(BufValue(h_rsi14, 1), 30)", "GT(HighestHigh(20, 1), LowestLow(10, 1))", "LT(Ret(5, 1), 0.05)",
                 "GT(iClose(_Symbol, TF, 1), 100)", "iVolume(_Symbol, TF, 1)", "PERIOD_W1", "AllowShort = true", "&&", "||"):
        assert text in ea, text
    x = _ea("SMA20 CROSS> SMA50")
    assert "bool     cross0 = false;" in x
    assert "if(CrossUp(BufValue(h_sma20, 1), BufValue(h_sma20, 2), BufValue(h_sma50, 1), BufValue(h_sma50, 2))) cross0 = true;" in x
    assert "else if(CrossDown(" in x and "bool signal = cross0;" in x
    d = _ea("SMA20 CROSS< SMA50")
    assert "if(CrossDown(BufValue(h_sma20, 1)" in d


@pytest.mark.parametrize("rule", ["SMA20>", "FOO>1", "SMA0>1", "CLOSE>>1", ""])
def test_mql5_refuses_what_the_parser_refuses(rule):
    with pytest.raises(RuleError):
        _ea(rule)


def _run(**over):
    day = 86400
    eq = [[1_700_000_000 + i * day, 100_000 + 50 * i - (700 if 10 < i < 18 else 0)] for i in range(40)]
    run = {
        "id": "abcdef0123456789", "rule": "SMA20>SMA50", "strategy": None, "symbols": ["AAPL"], "interval": "1D", "range": "10Y",
        "engine": "equity", "created_at": 1_700_000_000.0, "config": {"initial_cash": 100000, "fees_bps": 5},
        "labels": {"headline": LABEL, "fees_bps": 5, "slip_bps": 2, "costs": "TEST COSTS", "short": False, "prices": "ADJ",
                   "sources": [{"symbol": "AAPL", "name": "fixture", "as_of": "2024-01-01", "stale": False}]},
        "metrics": {"total_return": 0.12, "sharpe": 1.5, "max_drawdown": -0.1, "n_trades": 2, "nested": {"a": 1}},
        "equity": eq, "benchmark": [[t, v * 0.9] for t, v in eq],
        "trades": [{"symbol": "AAPL", "direction": 1, "entry_time": "2024-01-02", "exit_time": "2024-02-01", "entry_price": 10.0,
                    "exit_price": 11.0, "size": 5, "pnl": 5.0, "pnl_pct": 0.1, "commission": 0.1, "holding_bars": 20,
                    "exit_reason": "=HYPERLINK(\"http://x\")"},
                   {"symbol": "-cmd", "direction": -1, "entry_time": "2024-03-01", "exit_time": "2024-03-05", "entry_price": 11.0,
                    "exit_price": 12.0, "size": 5, "pnl": -5.0, "pnl_pct": -0.09, "commission": 0.1, "holding_bars": 4,
                    "exit_reason": "signal"}],
    }
    return run | over


def _pdf_pages(data):
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(data)).pages


def test_pdf_has_label_run_id_sections_and_pages():
    pages = _pdf_pages(export_report.run_pdf(_run()))
    assert len(pages) >= 1
    text = "\n".join(p.extract_text() for p in pages)
    for t in (LABEL, "abcdef0123456789", "Metrics", "Trades summary", "Equity curve", "Drawdown", "TEST COSTS",
              "slippage (bps)", "fees (bps)", "data source AAPL", "SMA20>SMA50", "total_return"):
        assert t in text, t
    assert all(LABEL in p.extract_text() for p in pages)  # the footer carries it on every page


def test_pdf_many_trades_paginates_and_survives_odd_text():
    run = _run(trades=_run()["trades"] * 60, rule=None, strategy="café 中文 strategy", equity=[], benchmark=[])
    pages = _pdf_pages(export_report.run_pdf(run))
    text = "\n".join(p.extract_text() for p in pages)
    assert len(pages) >= 2 and "NO EQUITY CURVE" in text and "more trades" in text


def _sheets(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    wb = z.read("xl/workbook.xml").decode()
    names = re.findall(r'<sheet name="([^"]+)"', wb)
    return z, names


def test_xlsx_sheets_and_formula_neutralisation():
    z, names = _sheets(export_report.run_xlsx(_run()))
    assert names == list(export_report.SHEETS)
    shared = z.read("xl/sharedStrings.xml").decode()
    assert LABEL in shared and "abcdef0123456789" in shared
    assert "'=HYPERLINK" in shared and "'-cmd" in shared  # leading apostrophe on formula-like text
    assert ">=HYPERLINK" not in shared and ">-cmd" not in shared
    for i in range(1, 5):
        assert "<f>" not in z.read(f"xl/worksheets/sheet{i}.xml").decode()
    eq = z.read("xl/worksheets/sheet2.xml").decode()
    assert eq.count("<row ") == 41  # header + 40 bars
    assert eq.count("<row ") == 41


def test_api_formats(client):
    def run_id(rule):
        r = client.post("/api/bt/run", json={"rule": rule, "symbols": ["AAPL"], "interval": "1D", "range": "10Y", "options": {}})
        end = time.monotonic() + 90
        while time.monotonic() < end:
            job = client.get(f"/api/jobs/{r.json()['id']}").json()
            if job["state"] in ("done", "error", "cancelled"):
                assert job["state"] == "done", job
                return job["result"]["run_id"]
            time.sleep(0.05)
        raise AssertionError("job did not finish")

    rid = run_id("SMA20>SMA50")
    mq = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "mql5"})
    assert mq.status_code == 200 and f'filename="BT_{rid}.mq5"' in mq.headers["content-disposition"] and "OnTick" in mq.text
    pdf = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "pdf"})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert LABEL in _pdf_pages(pdf.content)[0].extract_text()
    xl = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "xlsx"})
    assert _sheets(xl.content)[1] == list(export_report.SHEETS)
    assert client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "doc"}).status_code == 400
    assert client.get("/api/bt/runs/nope/export", params={"fmt": "pdf"}).status_code == 404


def test_mql5_refused_for_python_strategies_but_pdf_xlsx_work(client):
    code = ("import pandas as pd\n\nclass SignalEngine:\n    def generate(self, data_map):\n"
            "        return {s: (d['close'] > d['close'].rolling(20).mean()).astype(float) for s, d in data_map.items()}\n")
    client.put("/api/bt/strategies/mysma", json={"code": code})
    r = client.post("/api/bt/run", json={"strategy": "mysma", "symbols": ["AAPL"], "interval": "1D", "range": "10Y"})
    end = time.monotonic() + 90
    while True:
        job = client.get(f"/api/jobs/{r.json()['id']}").json()
        if job["state"] in ("done", "error", "cancelled") or time.monotonic() > end:
            break
        time.sleep(0.05)
    assert job["state"] == "done", job
    rid = job["result"]["run_id"]
    bad = client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "mql5"})
    assert bad.status_code == 400 and "MQL5 EXPORT NEEDS A RULE STRATEGY" in bad.json()["error"] and "RULE" in bad.json()["detail"]
    assert client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "pdf"}).content.startswith(b"%PDF")
    assert client.get(f"/api/bt/runs/{rid}/export", params={"fmt": "xlsx"}).content.startswith(b"PK")
