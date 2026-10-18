"""Phase 13 step 5: N-PORT and 13F parsing, ticker matching by name, quarter-over-quarter diff."""

import pytest

from openterm.providers.base import ProviderError
from openterm.research import fund_parse as fp

TICKERS = {"0": {"title": "Apple Inc.", "ticker": "AAPL"}, "1": {"title": "Alphabet Inc.", "ticker": "GOOGL"},
           "2": {"title": "Alphabet Inc.", "ticker": "GOOG"}, "3": {"title": "MICROSOFT CORP", "ticker": "MSFT"}}


def test_norm_name_drops_company_suffixes_and_punctuation():
    assert fp.norm_name("Apple Inc.") == fp.norm_name("APPLE INC") == "apple"
    assert fp.norm_name("Johnson & Johnson") == "johnson and johnson"
    assert fp.norm_name("Microsoft Corp") == fp.norm_name("MICROSOFT CORPORATION")
    assert fp.norm_name(None) == ""


def test_a_ticker_is_filled_only_when_the_name_has_exactly_one():
    idx = fp.name_index(TICKERS)
    holdings = [{"name": "Apple Inc", "symbol": None}, {"name": "Alphabet Inc Class A", "symbol": None},
                {"name": "Unknown Widgets Ltd", "symbol": None}, {"name": "Microsoft Corp", "symbol": None}]
    assert fp.match_tickers(holdings, idx) == 2
    assert [h["symbol"] for h in holdings] == ["AAPL", None, None, "MSFT"]  # Alphabet has two share classes: left blank


NPORT = """<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><formData>
<genInfo><regName>Test Trust</regName><seriesName>N/A</seriesName><repPdDate>2026-06-30</repPdDate></genInfo>
<fundInfo><netAssets>1000.0</netAssets></fundInfo>
<invstOrSecs>
<invstOrSec><name>Small Co</name><cusip>111</cusip><balance>10</balance><valUSD>100</valUSD><pctVal>10.0</pctVal><invCountry>US</invCountry></invstOrSec>
<invstOrSec><name>Big Co</name><cusip>222</cusip><balance>90</balance><valUSD>900</valUSD><pctVal>90.0</pctVal><identifiers><isin value="US2222222222"/></identifiers></invstOrSec>
</invstOrSecs></formData></edgarSubmission>"""


def test_parse_nport_reads_percent_as_a_ratio_and_sorts_by_weight():
    out = fp.parse_nport(NPORT)
    assert out["reg_name"] == "Test Trust" and out["period_end"] == "2026-06-30" and out["net_assets"] == 1000.0
    rows = fp.holding_rows(out["holdings"])
    assert [r["name"] for r in rows] == ["Big Co", "Small Co"] and rows[0]["weight"] == pytest.approx(0.9)
    assert out["holdings"][1]["isin"] == "US2222222222"
    with pytest.raises(ValueError):
        fp.parse_nport("<other/>")
    with pytest.raises(ValueError):
        fp.parse_nport("not xml at all <")


def table(*rows):
    body = "".join(
        f"<infoTable><nameOfIssuer>{n}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>{c}</cusip><value>{v}</value>"
        f"<shrsOrPrnAmt><sshPrnamt>{s}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>{pc}</infoTable>"
        for n, c, v, s, pc in rows)
    return f'<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">{body}</informationTable>'


def test_13f_value_is_dollars_after_2023_and_thousands_before():
    xml = table(("A CO", "1", 5, 100, ""))
    assert fp.parse_13f_table(xml, "2026-08-14")[0]["value"] == 5.0
    assert fp.parse_13f_table(xml, "2022-08-14")[0]["value"] == 5000.0
    with pytest.raises(ValueError):
        fp.parse_13f_table("<informationTable/>")


def test_diff_classifies_by_share_count_and_adds_duplicate_lines():
    now = fp.parse_13f_table(table(("KEEP", "1", 10, 50, ""), ("KEEP", "1", 10, 50, ""), ("UP", "2", 30, 200, ""), ("DOWN", "3", 5, 10, ""),
                                   ("NEWCO", "4", 40, 400, ""), ("SAME", "5", 1, 7, ""), ("OPT", "6", 9, 90, "<putCall>Put</putCall>")))
    before = fp.parse_13f_table(table(("KEEP", "1", 20, 100, ""), ("UP", "2", 20, 100, ""), ("DOWN", "3", 9, 20, ""),
                                      ("GONE", "7", 60, 600, ""), ("SAME", "5", 1, 7, ""), ("OPT", "6", 9, 90, "")))
    rows = {(r["cusip"], r["put_call"]): r for r in fp.diff_13f(now, before)}
    assert rows[("1", None)]["status"] == "UNCHANGED"  # 50 + 50 = 100 shares, as before
    assert rows[("2", None)]["status"] == "ADDED" and rows[("2", None)]["shares_change_pct"] == pytest.approx(1.0)
    assert rows[("3", None)]["status"] == "TRIMMED" and rows[("3", None)]["shares_change"] == -10
    assert rows[("4", None)]["status"] == "NEW" and rows[("4", None)]["shares_before"] is None
    assert rows[("7", None)]["status"] == "EXITED" and rows[("7", None)]["value_change"] == -60
    assert rows[("6", "Put")]["status"] == "NEW" and rows[("6", None)]["status"] == "EXITED"  # keyed on (CUSIP, put/call)
    ordered = [abs(r["value_change"]) for r in fp.diff_13f(now, before)]
    assert ordered == sorted(ordered, reverse=True)
    assert {r["status"] for r in fp.diff_13f(now, None)} == {"HELD"}


def test_manager_lookup_accepts_names_spacing_and_numbers_but_not_guesses():
    assert fp.manager_cik("berkshire") == 1067983 and fp.manager_cik("Two Sigma") == 1179392 and fp.manager_cik("1067983") == 1067983
    with pytest.raises(ProviderError) as e:
        fp.manager_cik("Nobody Capital")
    assert e.value.kind == "not_found" and "BERKSHIRE" in str(e.value)


def test_13f_primary_reads_period_and_manager():
    xml = """<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><headerData><filerInfo><periodOfReport>06-30-2026</periodOfReport>
    </filerInfo></headerData><formData><coverPage><filingManager><name>Test Mgr</name></filingManager></coverPage>
    <summaryPage><tableEntryTotal>89</tableEntryTotal><tableValueTotal>1000</tableValueTotal></summaryPage></formData></edgarSubmission>"""
    assert fp.parse_13f_primary(xml) == {"period": "2026-06-30", "manager": "Test Mgr", "table_value": 1000.0, "table_entries": 89}


def test_memb_and_mgr_argument_errors(client):
    assert client.get("/api/research/memb").status_code == 400
    assert client.get("/api/research/mgr").status_code == 400
    r = client.get("/api/research/memb", params={"index": "TOOLONGNAME"})
    assert r.status_code == 400 and "SPX" in r.json()["error"]


def test_etf_for_a_symbol_with_no_fund_data_is_not_found(client):
    r = client.get("/api/research/etf", params={"symbol": "ZZZZ"})
    assert r.status_code == 404 and r.json()["kind"] == "not_found"
