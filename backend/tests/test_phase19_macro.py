"""Phase 19 step 5: ECST / WECO parsers, CENB table and rate parsers, FOMC rows in ECO, holidays route (recorded answers; no network)."""

import json
from datetime import date
from pathlib import Path

import pytest

from openterm.providers.base import ProviderError
from openterm.world import cb_calendar as cal
from openterm.world import cenb, fomc_eco, stats

FIX = Path(__file__).parent / "fixtures"


def rec(name: str):
    r = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    return r["body"] if "body" in r else r["text"]


async def boom(*a, **k):
    raise ProviderError("unavailable", "down")


# --- country and indicator resolution ----------------------------------------------------------------------------------
@pytest.mark.parametrize("text,iso", [("USA", "USA"), ("us", "USA"), ("Germany", "DEU"), ("uk", "GBR"), ("South Korea", "KOR"), ("in", "IND"), ("eu", "EUU"), ("world", "WLD"), ("BRA", "BRA")])
def test_country_resolution(text, iso):
    assert stats.resolve_country(text) == iso


@pytest.mark.parametrize("text", ["", "  ", "Atlantis", "1"])
def test_unknown_country_is_refused(text):
    with pytest.raises(ValueError):
        stats.resolve_country(text)


def test_indicator_catalogue_has_the_headline_set_with_world_bank_codes():
    for alias in ("GDP", "GDPG", "GDPPC", "CPI", "UNEMP", "POP", "DEBT", "CA", "TRADE"):
        assert stats.INDICATORS[alias].wb.count(".") >= 2
    assert stats.INDICATORS["INFLATION"] is stats.INDICATORS["CPI"]
    assert stats.INDICATORS["TRADE"].imf is None  # no IMF WEO twin: DBnomics cannot back it up


def test_dbnomics_reference_form():
    assert stats.parse_dbn_ref("DBN:IMF/WEO:latest/USA.NGDP_RPCH") == ("IMF", "WEO:latest", "USA.NGDP_RPCH")
    assert stats.parse_dbn_ref("dbn:eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20") == ("EUROSTAT", "une_rt_m", "M.SA.TOTAL.PC_ACT.T.EA20")
    assert stats.parse_dbn_ref("GDP") is None


def test_period_ends():
    assert stats.period_epoch("2025") == 1767139200  # 2025-12-31
    assert stats.period_epoch("2025-Q2") == stats.period_epoch("2025-06")
    assert stats.period_epoch("2024-02") == 1709164800  # 2024-02-29 (leap year)
    with pytest.raises(ValueError):
        stats.period_epoch("soon")


# --- World Bank / DBnomics parsers on recorded answers -----------------------------------------------------------------
def test_world_bank_series_is_ascending_annual_and_drops_empty_years():
    out = stats.parse_wb_series(rec("worldbank_usa_gdp_growth"), stats.INDICATORS["GDPG"], "USA")
    assert out["country_name"] == "United States" and out["freq"] == "ANNUAL"
    assert out["periods"] == sorted(out["periods"]) and len(out["t"]) == len(out["v"]) == len(out["periods"])
    assert out["last_period"] == out["periods"][-1] and out["last_value"] == out["v"][-1]
    assert out["updated"] == "2026-10-08"
    assert all(isinstance(v, float) for v in out["v"])


def test_world_bank_error_message_and_empty_are_not_found():
    err = [{"message": [{"id": "120", "key": "Invalid value", "value": "The provided parameter value is not valid"}]}]
    for body in (err, [{"page": 1}, []], [{"page": 1}, [{"date": "2025", "value": None, "country": {"value": "X"}}]], {}):
        with pytest.raises(ProviderError) as e:
            stats.parse_wb_series(body, stats.INDICATORS["CPI"], "XXX")
        assert e.value.kind == "not_found"


def test_dbnomics_series_scales_and_drops_missing():
    body = rec("dbnomics_imf_weo_usa_ngdp_rpch")
    out = stats.parse_dbn_series(body, "GDP growth", "%", 1.0, "USA", "GDPG")
    assert out["periods"][0] == "1980" and out["t"] == sorted(out["t"])
    doc = body["series"]["docs"][0]
    assert len(out["v"]) == len([v for v in doc["value"] if isinstance(v, float)])
    scaled = stats.parse_dbn_series(body, "x", "", 1e9, "USA", "GDP")
    assert scaled["v"][0] == pytest.approx(out["v"][0] * 1e9)
    with pytest.raises(ProviderError):
        stats.parse_dbn_series({"series": {"docs": []}})


def test_weco_every_cell_keeps_its_own_year_and_old_data_is_flagged():
    cols = (("GDPG", "gdp_growth"), ("CPI", "inflation"), ("UNEMP", "unemployment"), ("DEBT", "debt_gdp"), ("CA", "current_account"))
    latest = {c: stats.parse_wb_latest(rec(f"worldbank_g20_{n}")) for c, n in cols}
    rows = stats.weco_rows(latest, 2026)
    assert [r["iso3"] for r in rows] == list(stats.G20)
    years = {c["year"] for r in rows for c in r["cells"].values() if c}
    assert len(years) > 1  # the recorded debt column really mixes years (1990 ... 2024)
    old = [c["year"] for r in rows for k, c in r["cells"].items() if k == "DEBT" and c and c["stale"]]
    assert old and all(y <= 2023 for y in old)
    assert set(rows[0]["cells"]["CPI"]) == {"v", "year", "stale"}
    assert [r["iso3"] for r in rows if r["cells"]["DEBT"] is None]  # 14 of 19 countries have debt data: the rest are empty cells, never zeros


# --- CENB ----------------------------------------------------------------------------------------------------------------
def test_policy_rate_parsers_on_recorded_answers():
    assert cenb.parse_boc_last(rec("boc_policy_rate"))[0] == "2026-10-09"
    d, v = cenb.parse_ecb_last(rec("ecb_policy_rate_mrr"))
    assert d == "2026-09-16" and v == 2.65
    d, v = cenb.parse_boe_last(rec("boe_bank_rate"))
    assert d == "2026-10-15" and v == 3.75
    assert cenb.parse_fred_csv_last(rec("fred_csv_DFEDTARU")) == ("2026-10-17", 4.0)
    for fn in (cenb.parse_fred_csv_last, cenb.parse_boe_last):
        with pytest.raises(ProviderError):
            fn("x")
    for fn in (cenb.parse_ecb_last, cenb.parse_boc_last):
        with pytest.raises(ProviderError):
            fn({})


def test_calendar_table_is_sorted_dated_and_every_bank_has_a_source():
    assert cal.AS_OF.startswith("2026-")
    for key, info in cal.BANKS.items():
        assert info["url"].startswith("https://"), key
        for year, ds in info["dates"].items():
            assert ds == sorted(ds) and all(d.startswith(str(year)) for d in ds), (key, year)


def test_around_picks_last_next_and_after():
    ds = ["2026-09-17", "2026-11-05", "2026-12-17"]
    assert cal.around(ds, date(2026, 10, 18)) == ("2026-09-17", "2026-11-05", "2026-12-17")
    assert cal.around(ds, date(2026, 11, 5)) == ("2026-11-05", "2026-12-17", None)
    assert cal.around(ds, date(2027, 1, 1)) == ("2026-12-17", None, None)


def test_table_builds_rows_with_rates_next_dates_and_honest_gaps():
    rates = {"FED": {"rate": 4.0, "as_of": "2026-10-17"}, "ECB": {"rate": 2.65, "as_of": "2026-09-16"}, "BOE": {"error": "UNAVAILABLE: timeout"}}
    fomc = ["2026-09-16", "2026-10-28", "2026-12-09"]
    out = cenb.build(rates, fomc, date(2026, 10, 18))
    by = {r["bank"]: r for r in out["rows"]}
    assert [r["bank"] for r in out["rows"]] == list(cal.ORDER)
    assert by["FED"]["next"] == "2026-10-28" and by["FED"]["days"] == 10 and by["FED"]["rate"] == 4.0
    assert by["BOE"]["rate"] is None and "TIMEOUT" in by["BOE"]["rate_note"].upper()
    assert by["BOE"]["next"] == "2026-11-05" and by["BOE"]["last"] == "2026-09-17"
    assert by["RBA"]["rate_note"] == "NO KEYLESS POLICY-RATE SOURCE" and by["RBA"]["next"] == "2026-11-03"
    assert by["ECB"]["note"] == "ONLY THE REMAINING 2026 MEETINGS ARE LISTED ON THE ECB PAGE"
    assert out["calendar_as_of"] == cal.AS_OF


def test_year_not_loaded_is_said_not_estimated():
    out = cenb.build({}, None, date(2028, 3, 1))
    by = {r["bank"]: r for r in out["rows"]}
    for r in out["rows"]:
        assert r["next"] is None and r["note"].startswith("CALENDAR NOT LOADED FOR 2028"), r["bank"]
    assert "FOMC PAGE DID NOT ANSWER" in by["FED"]["note"]


# --- FOMC rows in ECO -----------------------------------------------------------------------------------------------------
def test_fomc_events_are_eco_shaped_and_respect_since():
    ev = fomc_eco.fomc_events(["2026-09-16", "2026-10-28"], "2026-10-01")
    assert len(ev) == 1
    e = ev[0]
    assert (e["date"], e["time"], e["name"], e["agency"], e["major"], e["source"]) == ("2026-10-28", "14:00", "FOMC DECISION", "FED", True, "federalreserve.gov")
    assert e["ts"] == 1793210400.0  # 2026-10-28 14:00 EDT (UTC-4)


def test_eco_route_includes_the_fomc_decision(client):
    r = client.get("/api/eco", params={"start": "2026-10-20", "days": 14}).json()
    fomc = [e for e in r["data"]["events"] if e["agency"] == "FED" and e["name"] == "FOMC DECISION"]
    assert [e["date"] for e in fomc] == ["2026-10-28"]
    assert r["data"]["notes"] == []


def test_eco_says_fomc_stale_when_the_fed_page_is_down(client):
    async def down():
        raise ProviderError("unavailable", "down")

    client.app.state.service.router.providers["fomc"].fomc_dates = down
    client.app.state.service.cache.mem.clear()
    r = client.get("/api/eco", params={"start": "2026-10-20", "days": 14}).json()
    assert r["data"]["notes"] == ["FOMC: STALE (federalreserve.gov DID NOT ANSWER)"]
    assert not [e for e in r["data"]["events"] if e["name"] == "FOMC DECISION"]


# --- routes (fixture mode) ------------------------------------------------------------------------------------------------
def test_ecst_route_world_bank_series(client):
    r = client.get("/api/world/stats", params={"country": "usa", "ind": "gdpg"}).json()
    assert r["data"]["indicator"] == "GDPG" and r["data"]["country"] == "USA" and r["source"].startswith("worldbank")
    assert r["data"]["last_period"] >= "2024"


def test_ecst_dbnomics_fallback_is_labelled_with_projections(client):
    client.app.state.service.router.providers["worldbank"].worldstats = boom
    r = client.get("/api/world/stats", params={"country": "United States", "ind": "GDPG"}).json()
    assert r["fallback_from"] == ["worldbank"]
    assert "IMF WEO" in r["source"] and "PROJECTIONS" in r["source"].upper()


def test_ecst_dbn_reference_and_bad_inputs(client):
    r = client.get("/api/world/stats", params={"ind": "DBN:IMF/WEO:latest/USA.NGDP_RPCH"}).json()
    assert r["data"]["periods"][0] == "1980" and "IMF/WEO" in r["source"]
    bad = client.get("/api/world/stats", params={"country": "usa", "ind": "nope"})
    assert bad.status_code == 400 and "UNKNOWN INDICATOR" in bad.json()["error"]
    assert client.get("/api/world/stats", params={"country": "Atlantis", "ind": "CPI"}).status_code == 400


def test_weco_route_has_19_countries_5_columns_and_a_year_per_cell(client):
    d = client.get("/api/world/weco").json()["data"]
    assert len(d["rows"]) == 19 and [c["alias"] for c in d["columns"]] == list(stats.WECO_COLUMNS)
    assert d["failed"] == [] and "OWN DATA YEAR" in d["note"]
    usa = next(x for x in d["rows"] if x["iso3"] == "USA")
    assert usa["cells"]["CPI"]["year"] >= 2024


def test_cenb_route(client):
    r = client.get("/api/world/cenb").json()
    rows = {x["bank"]: x for x in r["data"]["rows"]}
    assert rows["FED"]["rate"] == 4.0 and rows["ECB"]["rate"] == 2.65 and rows["BOE"]["rate"] == 3.75 and rows["BOC"]["rate"] is not None
    assert r["data"]["notes"] == [] and r["data"]["calendar_as_of"] == cal.AS_OF


def test_holidays_route_ny_by_rule_and_nager_labelled(client):
    ny = client.get("/api/world/holidays", params={"mkt": "NY", "year": 2026}).json()
    assert ny["data"]["basis"] == "rules" and "2026-07-03" in [h["date"] for h in ny["data"]["holidays"]]
    assert [h["date"] for h in ny["data"]["early"]] == ["2026-11-27", "2026-12-24"]
    ln = client.get("/api/world/holidays", params={"mkt": "LN", "year": 2026}).json()
    assert ln["data"]["basis"] == "public" and "EXCHANGE MAY DIFFER" in ln["data"]["label"]
    assert any(h["date"] == "2026-12-25" for h in ln["data"]["holidays"])
    assert client.get("/api/world/holidays", params={"mkt": "ZZ"}).status_code == 400
