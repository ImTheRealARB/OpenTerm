"""Phase 7: FRED (API + keyless CSV), MACRO, RATES (Treasury curve), ERN (Nasdaq earnings), ECO (BLS + BEA ICS).

Everything replays recorded responses from tests/fixtures (see the Phase 7 block in providers/fixtures.py).
"""

import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from openterm.providers import macro
from openterm.providers.base import ProviderError
from openterm.providers.fixtures import FIXTURES, _route, fixture_transport

TODAY = date(2026, 10, 17)  # the day the fixtures were recorded


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """Treasury files, ECO windows and the ERN date bound are keyed to 'today'."""
    monkeypatch.setattr(macro, "ny_today", lambda: TODAY)


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=fixture_transport()) as c:
        yield c


def failing(hosts: set[str], status: int = 503) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in hosts:
            return httpx.Response(status, text="down")
        return _route(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def fixture_text(name: str) -> str:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["text"]


@pytest.fixture
def keyed_client(tmp_path, monkeypatch):
    """App with FRED_API_KEY set (a dummy: the fixture transport answers instead of FRED)."""
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "k.db"))
    monkeypatch.setenv("FRED_API_KEY", "dummykey0123456789")
    from openterm.config import get_settings

    get_settings.cache_clear()
    from openterm.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


# --- FRED keyless CSV --------------------------------------------------------------------------
async def test_fred_csv_series(http):
    s = await macro.FredCsvProvider(http, source="fred_csv:fixture").fred_series("UNRATE", date(2021, 10, 1))
    assert s.id == "UNRATE" and s.title == "Unemployment Rate" and s.meta_source == "curated"
    assert s.last_date == "2026-09-01" and s.last_value == 4.2 and s.prev_value == 4.1
    assert s.change == pytest.approx(0.1)
    assert len(s.t) == len(s.v) and s.t == sorted(s.t)
    assert s.missing == sum(v is None for v in s.v)  # empty CSV fields stay None, never filled in


async def test_fred_csv_unknown_id_is_not_found(http):
    with pytest.raises(ProviderError) as e:
        await macro.FredCsvProvider(http, source="fred_csv:fixture").fred_series("NOPE1", None)
    assert e.value.kind == "not_found"


async def test_fred_csv_unlisted_series_has_no_metadata(http):
    s = await macro.FredCsvProvider(http, source="x").fred_series("DGS10", None)
    assert s.id == "DGS10" and s.last_value > 0


def test_fred_ranges_and_ids():
    assert macro.range_start("MAX") is None
    assert macro.range_start("1Y", TODAY) == date(2025, 10, 16)
    assert macro.SERIES_ID.match("A191RL1Q225SBEA") and not macro.SERIES_ID.match("BAD ID")


# --- FRED API (keyed) ----------------------------------------------------------------------------
async def test_fred_api_without_key_is_inactive(http):
    p = macro.FredApiProvider(http, api_key="")
    assert not p.supports("fred_series") and not p.has_key
    with pytest.raises(ProviderError) as e:
        await p.fred_series("GDP", None)
    assert e.value.kind == "key_required"


async def test_fred_api_series_with_metadata(http):
    p = macro.FredApiProvider(http, source="fred:fixture", api_key="dummykey0123456789")
    assert p.supports("fred_series") and p.supports("fred_search")
    s = await p.fred_series("GDP", None)
    assert s.id == "GDP" and s.meta_source == "fred_api" and s.title and s.units and s.frequency
    assert s.last_value > 0 and s.last_date
    rows = await p.fred_search("inflation")
    assert rows and {"id", "title"} <= set(rows[0])


async def test_fred_api_error_never_echoes_the_key(http):
    secret = "SECRETKEY0123456789"
    p = macro.FredApiProvider(http, source="fred:fixture", api_key=secret)
    with pytest.raises(ProviderError) as e:
        await p.fred_series("NOSUCH", None)
    assert e.value.kind == "not_found" and secret not in str(e.value)


# --- Treasury curve ---------------------------------------------------------------------------
async def test_treasury_curve(http):
    c = await macro.TreasuryProvider(http, source="treasury:fixture").yield_curve(TODAY)
    assert c.date == "2026-10-16" and len(c.tenors) == len(c.years) == len(c.yields)
    assert c.years == sorted(c.years)
    assert "2Y" in c.tenors and "10Y" in c.tenors
    y = dict(zip(c.tenors, c.yields))
    assert c.spread_2s10s == pytest.approx(round(y["10Y"] - y["2Y"], 2))
    assert set(c.compare) == {"1D", "1W", "1M", "1Y"}
    assert c.compare["1Y"]["date"] <= "2025-10-16" and len(c.compare["1Y"]["yields"]) == len(c.tenors)


async def test_treasury_previous_year_missing_drops_1y_with_a_note():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/2025/all"):
            return httpx.Response(503, text="down")
        return _route(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
        c = await macro.TreasuryProvider(h, source="t").yield_curve(TODAY)
    assert "1Y" not in c.compare and c.note and "1Y" in c.note


# --- Nasdaq earnings ----------------------------------------------------------------------------
async def test_earnings_reported_day(http):
    out = await macro.NasdaqEarningsProvider(http, source="n").earnings(date(2026, 10, 15))
    rows = out["rows"]
    assert out["date"] == "2026-10-15" and rows
    caps = [r["market_cap"] or 0 for r in rows]
    assert caps == sorted(caps, reverse=True)
    assert {r["time"] for r in rows} <= {"PRE", "POST", None}
    assert any(r["eps"] is not None and r["surprise_pct"] is not None for r in rows)


async def test_earnings_future_day_has_last_year_figures(http):
    rows = (await macro.NasdaqEarningsProvider(http, source="n").earnings(date(2026, 10, 20)))["rows"]
    assert rows and all(r["eps"] is None for r in rows)
    assert any(r["last_year_eps"] is not None for r in rows)


async def test_earnings_weekend_is_an_empty_day_not_an_error(http):
    out = await macro.NasdaqEarningsProvider(http, source="n").earnings(date(2026, 10, 17))
    assert out["rows"] == []


def test_money_parsing():
    assert macro.money("($0.24)") == -0.24
    assert macro.money("$1,234.50") == 1234.5
    assert macro.money("N/A") is None and macro.money(None) is None


# --- ECO (BLS + BEA ICS) --------------------------------------------------------------------------
def test_parse_ics_both_agencies():
    bls = macro.parse_ics(fixture_text("bls_schedule_ics"), "BLS", "t")
    bea = macro.parse_ics(fixture_text("bea_schedule_ics"), "BEA", "t")
    assert bls and bea
    assert all(e.agency == "BLS" for e in bls) and all(e.agency == "BEA" for e in bea)
    assert all(e.time is None or len(e.time) == 5 for e in bls + bea)
    # BEA publishes in UTC: converted to US Eastern, so no event can sit at an impossible local hour.
    assert all(e.time is None or "06:00" <= e.time <= "20:00" for e in bea)
    assert any(e.major for e in bls + bea)


async def test_eco_one_agency_down_reports_failed(monkeypatch):
    async with failing({"www.bls.gov"}) as h:
        out = await macro.AgencyCalendarProvider(h, source="x").eco_calendar(TODAY)
    assert out["failed"] == ["BLS"] and out["events"] and {e.agency for e in out["events"]} == {"BEA"}


async def test_eco_both_agencies_down_raises():
    async with failing({"www.bls.gov", "www.bea.gov"}) as h:
        with pytest.raises(ProviderError):
            await macro.AgencyCalendarProvider(h, source="x").eco_calendar(TODAY)


# --- API envelopes (no key) -----------------------------------------------------------------------
def test_api_fred(client):
    r = client.get("/api/fred", params={"id": "unrate"})
    assert r.status_code == 200
    b = r.json()
    d = b["data"]
    assert b["source"] == "fred_csv:fixture" and b["stale"] is False and b["fallback_from"] == []
    assert d["id"] == "UNRATE" and d["range"] == "5Y" and d["key_set"] is False
    assert d["last_date"] == "2026-09-01" and len(d["t"]) == len(d["v"])


def test_api_fred_errors(client):
    r = client.get("/api/fred", params={"id": "NOPE1"})
    assert r.status_code == 404 and r.json()["error"] == "NO FRED SERIES NOPE1"
    assert client.get("/api/fred", params={"id": "bad id"}).status_code == 400
    assert client.get("/api/fred", params={"id": "GDP", "range": "3Y"}).status_code == 400


def test_api_macro_curated_without_key(client):
    b = client.get("/api/macro").json()
    d = b["data"]
    assert d["mode"] == "curated" and d["needs_key"] == "FRED_API_KEY" and len(d["rows"]) >= 15
    row = next(r for r in d["rows"] if r["id"] == "CPIAUCSL")
    assert row["last_value"] > 0 and row["source"] == "fred_csv:fixture" and "error" not in row
    q = client.get("/api/macro", params={"q": "gdp"}).json()["data"]
    assert {r["id"] for r in q["rows"]} >= {"GDP", "A191RL1Q225SBEA"} and q["needs_key"] == "FRED_API_KEY"


def test_api_rates(client):
    b = client.get("/api/rates").json()
    assert b["source"] == "treasury:fixture" and b["data"]["date"] == "2026-10-16"
    assert b["data"]["spread_2s10s"] is not None


def test_api_rates_falls_back_to_fred_csv(tmp_path, monkeypatch):
    """Treasury down: the FRED constant-maturity series answer, flagged as a fallback."""
    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "f.db"))
    from openterm import providers
    from openterm.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        providers, "fixture_transport",
        lambda: httpx.MockTransport(lambda r: httpx.Response(503, text="down") if r.url.host == "home.treasury.gov"
                                    else _route(r)),
    )
    from openterm.main import app

    with TestClient(app) as c:
        b = c.get("/api/rates").json()
    get_settings.cache_clear()
    assert b["source"].startswith("fred_csv") and b["fallback_from"] == ["treasury"]
    assert b["data"]["yields"] and b["data"]["date"]


def test_api_earnings(client):
    b = client.get("/api/earnings", params={"date": "2026-10-15"}).json()
    assert b["source"] == "nasdaq_earnings:fixture" and b["data"]["rows"]
    assert client.get("/api/earnings", params={"date": "2026-10-17"}).json()["data"]["rows"] == []
    assert client.get("/api/earnings", params={"date": "15/10/2026"}).status_code == 400
    assert client.get("/api/earnings", params={"date": "2030-01-01"}).status_code == 400


def test_api_eco_window(client):
    b = client.get("/api/eco", params={"start": "2026-10-17", "days": 14}).json()
    d = b["data"]
    assert b["source"] == "agency_ics:fixture" and d["failed"] == [] and d["key_set"] is False
    assert d["events"] and all("2026-10-17" <= e["date"] < "2026-10-31" for e in d["events"])
    assert [e["ts"] for e in d["events"]] == sorted(e["ts"] for e in d["events"])
    assert d["coverage_end"] >= d["events"][-1]["date"]
    assert client.get("/api/eco", params={"start": "x"}).status_code == 400


def test_sources_lists_fred_as_key_required(client):
    s = client.get("/api/sources").json()
    keyed = {k["name"]: k for k in s["keyed"]}
    assert keyed["fred"]["status"] == "KEY REQUIRED" and "fred_csv" in keyed["fred"]["note"]
    assert s["order"]["fred_series"] == ["fred", "fred_csv"] and s["order"]["eco_calendar"][0] == "agency_ics"


# --- API with a key -------------------------------------------------------------------------------
def test_api_with_key_search_and_metadata(keyed_client):
    b = keyed_client.get("/api/fred", params={"id": "GDP"}).json()
    assert b["source"] == "fred:fixture" and b["data"]["meta_source"] == "fred_api" and b["data"]["key_set"] is True
    m = keyed_client.get("/api/macro", params={"q": "inflation"}).json()
    assert m["data"]["mode"] == "search" and m["data"]["needs_key"] is None and m["data"]["rows"]
    # No key leaks into any envelope.
    assert "dummykey0123456789" not in json.dumps(b) + json.dumps(m)
    keyed = {k["name"]: k["status"] for k in keyed_client.get("/api/sources").json()["keyed"]}
    assert "fred" not in keyed


def test_api_with_key_unknown_series_message(keyed_client):
    r = keyed_client.get("/api/fred", params={"id": "NOSUCH"})
    assert r.status_code == 404 and "dummykey0123456789" not in r.text
