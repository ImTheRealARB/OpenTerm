"""Phase 6: SEC EDGAR fundamentals (FA), filings (FIL), Form 4 insiders (OWN), Yahoo holders (HDS)."""

import json

import httpx
import pytest

from openterm.cache import Cache
from openterm.config import get_settings
from openterm.errors import DataError
from openterm.providers.base import ProviderError
from openterm.providers.fixtures import FIXTURES, _route, fixture_transport
from openterm.providers.ownership import (
    YahooOwnProvider,
    holders_from_summary,
    insiders_from_summary,
)
from openterm.providers.sec import US_ONLY, SecProvider, default_user_agent, sec_ticker, store_from
from openterm.providers.sec_parse import (
    TAGS,
    describe,
    form4_xml_url,
    parse_companyfacts,
    parse_form4,
)
from openterm.router import Router
from openterm.service import DataService

ORDER = {"fundamentals": ["sec"], "filings": ["sec"], "insiders": ["sec", "yahoo_own"], "holders": ["yahoo_own"]}


def body(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]


def xml(accession: str) -> str:
    return json.loads((FIXTURES / "sec_form4" / f"{accession}.json").read_text(encoding="utf-8"))["text"]


@pytest.fixture(scope="module")
def aapl():
    return parse_companyfacts(body("sec_facts_aapl"))


@pytest.fixture(scope="module")
def msft():
    return parse_companyfacts(body("sec_facts_msft"))


def row(view: dict, key: str) -> dict:
    return next(r for rows in view["statements"].values() for r in rows if r["key"] == key)


def cell(view: dict, key: str, label: str):
    i = [p["label"] for p in view["periods"]].index(label)
    r = row(view, key)
    return r["values"][i], r["flags"][i], r["tags"][i]


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


def failing(hosts: set[str], status: int = 503) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in hosts:
            return httpx.Response(status, text="Your Request Originates from an Undeclared Automated Tool")
        return _route(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def no_ua(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- ticker -> CIK ---------------------------------------------------------------------------
def test_sec_ticker_forms():
    assert sec_ticker("AAPL") == "AAPL"
    assert sec_ticker("BRK.B") == "BRK-B" and sec_ticker("brk-b") == "BRK-B"
    for s in ("RELIANCE.NS", "SAP.DE", "^GSPC", "EURUSD=X", "BTC-USD", "GC=F", ""):
        assert sec_ticker(s) is None, s


async def test_cik_lookup_and_caching(http):
    p = SecProvider(http)
    assert await p.cik("AAPL") == 320193
    assert await p.cik("BRK.B") == 1067983
    with pytest.raises(ProviderError) as e:
        await p.cik("ZZZZ")
    assert e.value.kind == "not_found" and "no SEC filer" in str(e.value)
    with pytest.raises(ProviderError) as e:
        await p.cik("RELIANCE.NS")
    assert e.value.kind == "unsupported"
    assert p.supports("fundamentals", "AAPL") and not p.supports("fundamentals", "RELIANCE.NS")
    calls = p.bucket.remaining
    await p.cik("MSFT")  # ticker map is cached: no new request
    assert p.bucket.remaining >= calls - 0.01


# --- company facts ---------------------------------------------------------------------------
def test_fixture_is_trimmed_to_mapped_tags():
    tags = set(body("sec_facts_aapl")["facts"]["us-gaap"])
    assert tags <= set(TAGS) and "RevenueFromContractWithCustomerExcludingAssessedTax" in tags


def test_annual_fiscal_years_not_calendar(aapl, msft):
    a, m = aapl["A"], msft["A"]
    # Apple's fiscal year ends late September, Microsoft's on 30 June: labels follow each filer's own fy.
    assert a["periods"][0]["label"] == "FY2025" and a["periods"][0]["end"] == "2025-09-27"
    assert m["periods"][0]["label"] == "FY2026" and m["periods"][0]["end"] == "2026-06-30"
    assert [p["end"] for p in a["periods"]] == sorted((p["end"] for p in a["periods"]), reverse=True)
    assert cell(a, "revenue", "FY2024")[0] == 391_035_000_000
    assert cell(m, "revenue", "FY2024")[0] == 245_122_000_000
    assert aapl["name"] == "Apple Inc." and aapl["currency"] == "USD"


def test_tag_fallback_across_years(aapl):
    # Apple tagged revenue as SalesRevenueNet before FY2018 and RevenueFromContractWithCustomer... after.
    v, _, tag = cell(aapl["A"], "revenue", "FY2025")
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax" and v == 416_161_000_000
    _, _, old = cell(aapl["A"], "revenue", "FY2016")
    assert old in ("SalesRevenueNet", "Revenues")


def test_quarterly_labels_and_derived_q4(aapl, msft):
    q = aapl["Q"]
    labels = [p["label"] for p in q["periods"]]
    assert labels[:4] == ["Q3 FY2026", "Q2 FY2026", "Q1 FY2026", "Q4 FY2025"]
    # No 10-Q covers Q4: revenue = FY2025 minus the nine-month YTD, flagged derived.
    q4, flag, _ = cell(q, "revenue", "Q4 FY2025")
    fy = cell(aapl["A"], "revenue", "FY2025")[0]
    quarters = sum(cell(q, "revenue", f"Q{n} FY2025")[0] for n in (1, 2, 3))
    assert flag == "d" and q4 == fy - quarters == 102_466_000_000
    assert cell(q, "revenue", "Q1 FY2026")[1] == ""  # a real 3-month fact
    assert cell(q, "eps_diluted", "Q4 FY2025")[0] is None  # per-share values are never derived
    assert next(p for p in q["periods"] if p["label"] == "Q4 FY2025")["derived"] is True
    # Balance sheet at a fiscal year end is a real instant, not derived.
    assert cell(q, "total_assets", "Q4 FY2025") == (359_241_000_000, "", "Assets")
    m = msft["Q"]
    assert [p["label"] for p in m["periods"]][:2] == ["Q4 FY2026", "Q3 FY2026"]
    assert next(p for p in m["periods"] if p["label"] == "Q1 FY2026")["end"] == "2025-09-30"


def test_ytd_cash_flow_quarters_are_derived(aapl):
    # Apple's 10-Q cash flow statements are year-to-date only: Q2 = 6M - 3M.
    v, flag, _ = cell(aapl["Q"], "operating_cf", "Q2 FY2026")
    assert flag == "d" and v is not None
    assert cell(aapl["Q"], "operating_cf", "Q1 FY2026")[1] == ""


def test_fcf_computed(aapl):
    a = aapl["A"]
    fcf = row(a, "fcf")
    assert fcf["computed"] and fcf["label"] == "Free cash flow (computed)"
    assert cell(a, "fcf", "FY2025")[0] == cell(a, "operating_cf", "FY2025")[0] - cell(a, "capex", "FY2025")[0]
    assert cell(a, "fcf", "FY2025")[1] == "c"


def test_dedup_latest_filing_wins_and_other_forms_ignored():
    def fact(val, filed, form="10-K", fy=2024, fp="FY", accn=None, start="2023-07-01", end="2024-06-30"):
        return {"start": start, "end": end, "val": val, "accn": accn or f"acc-{filed}", "fy": fy, "fp": fp,
                "form": form, "filed": filed}

    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        fact(100, "2024-07-30"),
        fact(105, "2025-07-30", fy=2025),  # restated in the next 10-K: the later filing wins
        fact(999, "2025-12-01", form="8-K", fy=None, fp=None),  # 8-K recasts are ignored
        fact(120, "2025-07-30", fy=2025, start="2024-07-01", end="2025-06-30"),
    ]}}}}}
    out = parse_companyfacts(facts)
    a = out["A"]
    assert [p["label"] for p in a["periods"]] == ["FY2025", "FY2024"]
    assert row(a, "revenue")["values"] == [120, 105]
    with pytest.raises(ValueError):
        parse_companyfacts({"facts": {"us-gaap": {}}})


# --- filings ---------------------------------------------------------------------------------
async def test_filings_parse(http):
    out = await SecProvider(http).filings("AAPL")
    f = out["filings"]
    assert out["name"] == "Apple Inc." and out["fiscal_year_end"] == "0926" and len(f) == 60
    k = next(x for x in f if x["form"] == "8-K" and x["items"] == "2.02,9.01")
    assert k["description"] == "Current report: 2.02 Results of operations; 9.01 Exhibits"
    acc = k["accession"]
    assert k["url"] == f"https://www.sec.gov/Archives/edgar/data/320193/{acc.replace('-', '')}/{acc}-index.htm"
    assert describe("10-K/A", "", "") == "Annual report (amendment)"


def test_form4_url_drops_xsl_folder():
    assert form4_xml_url(320193, "0001140361-26-038674", "xslF345X06/form4.xml") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000114036126038674/form4.xml"
    )


# --- Form 4 ----------------------------------------------------------------------------------
def test_parse_form4_exercise_and_withholding():
    rows = parse_form4(xml("0001140361-26-038674"), "0001140361-26-038674", "2026-10-05")
    first = rows[0]
    assert first["owner"] == "COOK TIMOTHY D" and first["relation"] == "Director, Executive Chair"
    assert first["code"] == "M" and first["acq_disp"] == "A" and first["shares"] == 374_541
    assert first["price"] is None and first["value"] is None  # price given only as a footnote
    assert first["owned_after"] == 3_654_959 and first["direct"] == "D"
    f = rows[1]
    assert f["code"] == "F" and f["code_text"] == "Tax withholding" and f["price"] == 330.32
    assert any(r["derivative"] for r in rows)
    with pytest.raises(ValueError):
        parse_form4("<html>nope")


def test_parse_form4_sale():
    (r,) = parse_form4(xml("0001140361-26-039785"))
    assert (r["owner"], r["code"], r["shares"], r["price"]) == ("Newstead Jennifer", "S", 2399, 345.0)
    assert r["relation"] == "SVP, GC and Government Affairs" and r["value"] == 2399 * 345.0


async def test_insiders_cached_per_accession(http, tmp_path):
    cache = Cache(None)
    store = store_from(cache.get, cache.put)
    p = SecProvider(http)
    out = await p.insiders("AAPL", store)
    assert out["filings_read"] == 20 and out["failed"] == [] and len(out["trades"]) > 20
    dates = [t["date"] for t in out["trades"]]
    assert dates == sorted(dates, reverse=True)
    assert await store.get("0001140361-26-039785") is not None
    # Second run: every Form 4 comes from the store, so only submissions would hit SEC (memoized too).
    before = p.bucket.remaining
    again = await p.insiders("AAPL", store)
    assert again["trades"] == out["trades"] and p.bucket.remaining >= before - 0.01


# --- 403 / User-Agent ------------------------------------------------------------------------
async def test_403_names_the_user_agent_fix(no_ua):
    async with failing({"www.sec.gov", "data.sec.gov"}, 403) as c:
        p = SecProvider(c)
        assert p.headers["User-Agent"] == default_user_agent() and not p.ua_set
        assert "SEC_USER_AGENT" in p.terms
        svc = DataService(Router({"sec": p}, ORDER), Cache(None))
        with pytest.raises(DataError) as e:
            await svc.fundamentals("AAPL")
        assert e.value.kind == "unavailable" and "403 from SEC" in e.value.detail and "SEC_USER_AGENT" in e.value.detail


async def test_declared_user_agent_is_sent(monkeypatch, http):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Runner test@example.org")
    get_settings.cache_clear()
    try:
        p = SecProvider(http)
        assert p.ua_set and p.headers["User-Agent"] == "Test Runner test@example.org"
        assert "NOT SET" not in p.terms
    finally:
        get_settings.cache_clear()


async def test_insiders_fall_back_to_yahoo():
    async with failing({"www.sec.gov", "data.sec.gov"}) as c:
        svc = DataService(Router({"sec": SecProvider(c), "yahoo_own": YahooOwnProvider(c)}, ORDER), Cache(None))
        env = await svc.insiders("AAPL")
    assert env["fallback_from"] == ["sec"] and env["source"] == "yahoo_own"
    t = env["data"]["trades"][0]
    assert t["owner"] == "NEWSTEAD JENNIFER" and t["code"] == "S" and t["price"] == 332.01


# --- Yahoo holders ---------------------------------------------------------------------------
def test_holders_parse():
    r = body("yahoo_holders_aapl")["quoteSummary"]["result"][0]
    out = holders_from_summary("AAPL", r, "yahoo_own", 0)
    top = out["institutions"][0]
    assert top["holder"] == "Blackrock Inc." and top["pct_held"] == 0.0797 and top["report_date"] == "2026-06-30"
    assert out["funds"] and out["breakdown"]["institutions_pct"] is not None
    with pytest.raises(ProviderError):
        holders_from_summary("X", {}, "yahoo_own", 0)


def test_yahoo_insider_codes():
    r = body("yahoo_insiders_aapl")["quoteSummary"]["result"][0]
    trades = insiders_from_summary("AAPL", r, "yahoo_own", 0)["trades"]
    gift = next(t for t in trades if "Gift" in t["code_text"])
    assert gift["code"] == "G" and gift["price"] is None


# --- API -------------------------------------------------------------------------------------
def test_api_fa_envelope(client):
    r = client.get("/api/fa", params={"symbol": "aapl", "period": "q"})
    assert r.status_code == 200
    b = r.json()
    assert b["source"] == "sec:fixture" and b["stale"] is False and b["fallback_from"] == []
    d = b["data"]
    assert d["period"] == "Q" and d["symbol"] == "AAPL" and d["cik"] == 320193
    assert set(d["statements"]) == {"IS", "BS", "CF"} and "A" not in d and "Q" not in d
    assert d["periods"][0]["label"] == "Q3 FY2026"
    a = client.get("/api/fa", params={"symbol": "AAPL"}).json()["data"]
    assert a["period"] == "A" and a["periods"][0]["label"] == "FY2025"
    assert client.get("/api/fa", params={"symbol": "AAPL", "period": "X"}).status_code == 400


def test_api_non_us_and_unknown(client):
    for sym in ("RELIANCE.NS", "ZZZZ"):
        r = client.get("/api/fa", params={"symbol": sym})
        assert r.status_code == 404 and r.json()["error"] == US_ONLY
    r = client.get("/api/filings", params={"symbol": "^GSPC"})
    assert r.status_code == 404 and r.json()["error"] == US_ONLY


def test_api_filings_filter(client):
    all_ = client.get("/api/filings", params={"symbol": "MSFT"}).json()["data"]
    assert all_["total"] == 60 and all_["form"] is None and all_["name"] == "MICROSOFT CORP"
    k = client.get("/api/filings", params={"symbol": "AAPL", "form": "8-k"}).json()["data"]
    assert k["form"] == "8-K" and k["total"] == len(k["filings"]) > 0
    assert {f["form"] for f in k["filings"]} <= {"8-K", "8-K/A"}
    dates = [f["filed"] for f in k["filings"]]
    assert dates == sorted(dates, reverse=True)


def test_api_insiders_and_holders(client):
    own = client.get("/api/insiders", params={"symbol": "AAPL"}).json()
    assert own["source"] == "sec:fixture" and own["data"]["filings_read"] == 20
    hds = client.get("/api/holders", params={"symbol": "AAPL"}).json()
    assert hds["source"] == "yahoo_own:fixture" and len(hds["data"]["institutions"]) == 10
    r = client.get("/api/holders", params={"symbol": "MSFT"})
    assert r.status_code == 404 and r.json()["error"] == "NO DATA FOR SYMBOL"


def test_sources_lists_sec(client):
    s = client.get("/api/sources").json()
    sec = next(p for p in s["providers"] if p["name"] == "sec")
    assert sec["rate_per_s"] <= 10 and "fundamentals" in sec["capabilities"]
    assert s["order"]["insiders"] == ["sec", "yahoo_own"]
