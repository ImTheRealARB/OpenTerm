"""Phase 32: AI inside functions. Pure parts only (the model calls are covered by the existing AI FILING / agent tests)."""
from openterm.ai import filings
from openterm.ai.tools import BOARD_FNS, REGISTRY

# Shape of a real EDGAR `<accession>-index.html` document table (NVDA's results 8-K, 2026-11-17): the release's file name says nothing.
INDEX = """<table class="tableFile" summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1045810/000104581026000088/nvda-20261117.htm">nvda-20261117.htm</a></td><td>8-K</td><td>40000</td></tr>
<tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1045810/000104581026000088/q3fy27pr.htm">q3fy27pr.htm</a></td><td>EX-99.1</td><td>300000</td></tr>
<tr><td>3</td><td>CFO COMMENTARY</td><td><a href="/Archives/edgar/data/1045810/000104581026000088/q3fy27cfocommentary.htm">q3fy27cfocommentary.htm</a></td><td>EX-99.2</td><td>90000</td></tr>
</table>"""


def test_exhibit_991_is_found_by_its_type_column_not_its_name():
    assert filings.exhibit_991(INDEX) == "/Archives/edgar/data/1045810/000104581026000088/q3fy27pr.htm"
    assert filings.exhibit_991(INDEX.replace("EX-99.1", "EX-99.4")) is None


def test_only_item_2_02_8ks_are_earnings_releases():
    assert filings.is_earnings_8k({"form": "8-K", "items": "2.02,9.01"})
    assert not filings.is_earnings_8k({"form": "8-K", "items": "5.02"})
    assert not filings.is_earnings_8k({"form": "10-Q", "items": None})


def test_a_release_is_one_section_and_quotes_check_against_it():
    html = "<p>NVIDIA Announces Financial Results for Third Quarter Fiscal 2027</p><p>Revenue of $57.0 billion, up 62% from a year ago.</p>" \
           "<p>Outlook: Revenue is expected to be $65.0 billion, plus or minus 2%.</p>"
    p = filings.parse_filing(html, symbol="NVDA", form=filings.EARNINGS_FORM, filed="2026-11-17", accession="x", url="u", fetched_at=0.0)
    assert [s.label for s in p.sections] == [filings.RELEASE_LABEL]
    ok, where, _ = filings.check_quote("Revenue is expected to be $65.0 billion, plus or minus 2%", p.full_norm, p.sections)
    assert ok and where == filings.RELEASE_LABEL
    assert "earnings" in filings.PRESETS


def test_the_board_tool_offers_exactly_the_phase_30_boards():
    assert REGISTRY["board"].parameters["properties"]["fn"]["enum"] == list(BOARD_FNS)


def _fixture_bytes(name: str) -> bytes:
    import json
    from pathlib import Path

    rec = json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    return rec["text"].encode("utf-8")


def test_rss_1_0_feeds_parse_bis_publishes_this_way():
    from openterm.providers.news import parse_rss

    items = parse_rss(_fixture_bytes("res_bis"), "BIS working papers", "research_feeds")
    assert len(items) >= 10
    assert all(i.url.startswith("https://www.bis.org/") and i.published for i in items)


def test_res_filter_needs_every_word_and_respects_days():
    from datetime import date

    from openterm.macrod.service import res_filter

    rows = [{"date": "2026-11-20", "title": "Monetary policy tail events", "summary": "inflation expectations"},
            {"date": "2026-01-05", "title": "Bank liquidity", "summary": "monetary policy and capital"}]
    assert [r["title"] for r in res_filter(rows, "monetary POLICY", None, date(2026, 11, 24))] == ["Monetary policy tail events", "Bank liquidity"]
    assert len(res_filter(rows, "monetary inflation", None, date(2026, 11, 24))) == 1
    assert len(res_filter(rows, "", 30, date(2026, 11, 24))) == 1
