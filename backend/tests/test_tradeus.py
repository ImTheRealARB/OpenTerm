"""Trade + US macro family: UN Comtrade (TRADE), BLS / BEA / Census (USMAC).

ALL FIXTURES HERE ARE DOC-SHAPED (built from each provider's documentation, invented numbers): no key was available to record real
answers. These tests prove our parsing, key handling and labelling against that assumed shape, not against the live services.
"""

import json
from pathlib import Path

import pytest

from openterm.world import bea, bls, census, comtrade
from openterm.world.seriesboard import KeyRejected, NoData, NotUnderstood, build_series, num

FIX = Path(__file__).parent / "fixtures"
KEY = "test-key-0123456789"


def body(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


# --- shared helpers -------------------------------------------------------------------------------------------------
def test_num_strips_commas_and_treats_placeholders_as_missing():
    assert num("23,456.7") == 23456.7
    assert num("-") is None and num("(NA)") is None and num("") is None and num(None) is None
    with pytest.raises(NotUnderstood):
        num("abc")


def test_build_series_uses_the_two_newest_periods_that_have_a_value():
    s = build_series("X", "X", "x", "u", "M", [("2026-01", 1.0), ("2026-02", 2.0), ("2026-03", None)])
    assert (s["last"], s["last_period"], s["prev"], s["chg"], s["chg_pct"]) == (2.0, "2026-02", 1.0, 1.0, 100.0)
    assert s["points"][-1] == ["2026-03", None]  # the gap is kept, never filled


# --- BLS ------------------------------------------------------------------------------------------------------------
def test_bls_ids_and_body():
    assert [a for a, _ in bls.parse_ids("")] == list(bls.CATALOG)
    assert bls.parse_ids("cpi, LNS14000000") == [("CPI", "CUSR0000SA0"), ("UNEMP", "LNS14000000")]
    with pytest.raises(ValueError):
        bls.parse_ids("not a series!")
    b = bls.build_body(["A1"], 2024, 2026, KEY)
    assert b == {"seriesid": ["A1"], "startyear": "2024", "endyear": "2026", "registrationkey": KEY}


def test_bls_parse_keeps_gaps_skips_annual_average_and_reads_footnotes():
    data = bls.parse(body("bls_docshape_series"), bls.parse_ids("CPI UNEMP"))
    cpi, unemp = data["series"]
    assert cpi["last_period"] == "2026-08" and cpi["freq"] == "M"
    assert all(p != "2025-13" for p, _ in cpi["points"])  # M13 is the annual average, not a month
    gap = dict(unemp["points"])["2025-10"]
    assert gap is None and "lapse in appropriations" in unemp["notes"][0]
    assert data["missing"] == [] and "BLS" in data["source"]


def test_bls_rejected_key_and_unprocessed_request():
    with pytest.raises(KeyRejected):
        bls.parse(body("bls_docshape_bad_key"), bls.parse_ids("CPI"))
    with pytest.raises(NotUnderstood):
        bls.parse({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}, bls.parse_ids("CPI"))
    with pytest.raises(NotUnderstood):
        bls.parse({"nope": 1}, bls.parse_ids("CPI"))
    with pytest.raises(NoData):
        bls.parse({"status": "REQUEST_SUCCEEDED", "message": ["No Data Available for Series CUSR0000SA0"], "Results": {"series": [
            {"seriesID": "CUSR0000SA0", "data": []}]}}, bls.parse_ids("CPI"))


# --- BEA ------------------------------------------------------------------------------------------------------------
def test_bea_params_share_one_call_for_two_aliases():
    assert bea.call_key(bea.CATALOG["GDPG"]) == bea.call_key(bea.CATALOG["PCEG"]) != bea.call_key(bea.CATALOG["GDP"])
    p = bea.build_params(bea.CATALOG["GDPG"], 2026, KEY)
    assert p["datasetname"] == "NIPA" and p["TableName"] == "T10101" and p["Year"].endswith("2026") and p["UserID"] == KEY
    with pytest.raises(ValueError):
        bea.parse_aliases("NOPE")


def test_bea_nipa_picks_the_line_and_strips_commas():
    gdpg = bea.parse(body("bea_docshape_nipa_T10101"), bea.CATALOG["GDPG"])[0]
    pce = bea.parse(body("bea_docshape_nipa_T10101"), bea.CATALOG["PCEG"])[0]
    assert gdpg["id"] == "A191RL" and pce["id"] == "DPCERL" and gdpg["last_period"] == "2026Q2"
    gdp = bea.parse(body("bea_docshape_nipa_T10105"), bea.CATALOG["GDP"])[0]
    assert gdp["last"] > 27000  # "27,xxx.x" printed with a comma


def test_bea_ita_and_industry_and_errors():
    bal = bea.parse(body("bea_docshape_ita_BalGds"), bea.CATALOG["TRADEBAL"])[0]
    assert bal["unit"] == "USD MN" and bal["last"] < 0
    ind = bea.parse(body("bea_docshape_gdpbyindustry"), bea.CATALOG["INDUSTRY"])  # Results is a list here, and the field is IndustrYDescription
    assert [s["last_period"] for s in ind] == ["2024"] * 3 and ind[0]["last"] >= ind[-1]["last"]
    with pytest.raises(KeyRejected):
        bea.parse(body("bea_docshape_bad_userid"), bea.CATALOG["GDP"])
    with pytest.raises(NotUnderstood):
        bea.parse({"BEAAPI": {"Results": {"Data": [{"TimePeriod": "2025Q1"}]}}}, bea.CATALOG["GDP"])  # missing LineNumber: loud, not guessed
    with pytest.raises(NoData):
        bea.parse({"BEAAPI": {"Results": {"Data": []}}}, bea.CATALOG["GDP"])


# --- Census ---------------------------------------------------------------------------------------------------------
def test_census_args():
    assert census.parse_retail([]) == ["TOTAL"] and census.parse_retail(["AUTO", "FOOD"]) == ["AUTO", "FOOD"]
    assert census.parse_trade(["CHINA", "85"]) == ("CHINA", "5700", "85")
    for bad in (["CHINA"], ["MARS", "85"], ["CHINA", "8"], ["CHINA", "00"]):
        with pytest.raises(ValueError):
            census.parse_trade(bad)
    path, q = census.trade_params("M", "5700", "85", "2025-01", KEY)
    assert path.endswith("imports/hs") and "GEN_VAL_MO" in q["get"] and q["key"] == KEY


def test_census_retail_and_trade_parsing():
    r = census.parse_retail_answer(body("census_docshape_marts"), ["TOTAL", "AUTO"])
    assert [s["alias"] for s in r["series"]] == ["TOTAL", "AUTO"] and r["series"][0]["last_period"] == "2026-09"
    t = census.parse_trade_answers(body("census_docshape_exports_hs85_china"), body("census_docshape_imports_hs85_china"), "CHINA", "85")
    exp, imp, bal = t["series"]
    assert bal["last"] == pytest.approx(exp["last"] - imp["last"]) and "ELECTRICAL" in exp["label"]
    with pytest.raises(NotUnderstood):
        census.parse_retail_answer({"error": "x"}, ["TOTAL"])
    with pytest.raises(KeyRejected):
        census.parse_retail_answer({"error": "Invalid Key"}, ["TOTAL"])
    with pytest.raises(NotUnderstood):
        census.parse_retail_answer([["cell_value"], ["1"]], ["TOTAL"])  # no category_code column


# --- Comtrade -------------------------------------------------------------------------------------------------------
def test_comtrade_country_and_hs_words():
    assert comtrade.country("china")[:2] == ("CHN", 156) and comtrade.country("842")[0] == "USA" and comtrade.country("uk")[0] == "GBR"
    assert comtrade.commodity("") == "TOTAL" and comtrade.commodity("8517") == "8517"
    for bad in ("85a", "1", "12345"):
        with pytest.raises(ValueError):
            comtrade.commodity(bad)
    with pytest.raises(ValueError):
        comtrade.country("Narnia")


def test_comtrade_parse_ignores_breakdown_rows_and_leaves_gaps_blank():
    rep, par = comtrade.country("USA"), comtrade.country("CHN")
    d = comtrade.parse(body("comtrade_docshape_usa_chn_total"), rep, par, "TOTAL", list(range(2019, 2026)))
    years = [r["year"] for r in d["rows"]]
    assert years == [2025, 2024, 2023, 2022, 2021, 2020]  # 2019 absent: not invented
    r25 = d["rows"][0]
    assert r25["exports"] == pytest.approx(120e9 + 5 * 7e9)  # the motCode=1000 quarter-size row was not added in
    assert r25["balance"] == pytest.approx(r25["exports"] - r25["imports"]) and d["unit"] == "USD"
    with pytest.raises(NoData):
        comtrade.parse(body("comtrade_docshape_empty"), rep, par, "85", [2024])
    with pytest.raises(NotUnderstood):
        comtrade.parse({"data": [{"flowCode": "X"}], "error": ""}, rep, par, "TOTAL", [2024])
    with pytest.raises(NotUnderstood):
        comtrade.parse({"nope": 1}, rep, par, "TOTAL", [2024])


def test_comtrade_params_ask_for_totals_only():
    p = comtrade.build_params(842, 156, "TOTAL", [2023, 2024])
    assert p["period"] == "2023,2024" and p["flowCode"] == "X,M" and p["motCode"] == "0" and p["customsCode"] == "C00"


# --- HTTP: key handling, labelling, redaction -----------------------------------------------------------------------
def put_key(client, name: str, field: str, value: str = KEY):
    r = client.put(f"/api/keys/{name}", json={"fields": {field: value}})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("url,env", [
    ("/api/world/trade?reporter=USA&partner=CHN", "UN_COMTRADE_KEY"),
    ("/api/world/usmac?src=BLS", "BLS_API_KEY"),
    ("/api/world/usmac?src=BEA", "BEA_API_KEY"),
    ("/api/world/usmac?src=CENSUS", "CENSUS_API_KEY"),
])
def test_no_key_answers_424_and_names_the_variable(client, url, env):
    r = client.get(url)
    assert r.status_code == 424
    assert r.json()["key"] == env and r.json()["detail"] == f"KEY REQUIRED: set {env} in APIKEYS"


def test_trade_with_a_key_labels_source_period_and_fixture(client):
    assert put_key(client, "comtrade", "UN_COMTRADE_KEY")["state"] == "OK"
    r = client.get("/api/world/trade", params={"reporter": "usa", "partner": "china"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["data"]["rows"][0]["year"] == 2025 and j["data"]["reporter"]["iso"] == "USA" and j["data"]["partner"]["iso"] == "CHN"
    assert "UN COMTRADE" in j["source"] and "FIXTURE" in j["source"]  # test data is always labelled
    assert KEY not in r.text
    assert client.get("/api/world/trade", params={"reporter": "usa", "partner": "usa"}).status_code == 400
    assert client.get("/api/world/trade", params={"reporter": "usa", "partner": "china", "hs": "85"}).status_code == 404  # fixture: no HS85 recorded


def test_a_key_the_source_refuses_is_key_required_not_provider_down(client):
    put_key(client, "comtrade", "UN_COMTRADE_KEY", "invalid-fixture-key")
    r = client.get("/api/world/trade", params={"reporter": "usa", "partner": "china"})
    assert r.status_code == 424 and r.json()["key"] == "UN_COMTRADE_KEY"
    put_key(client, "bls", "BLS_API_KEY", "invalid-fixture-key")  # BLS says so inside an HTTP 200 body
    r = client.get("/api/world/usmac", params={"src": "BLS", "q": "CPI"})
    assert r.status_code == 424 and r.json()["key"] == "BLS_API_KEY"


def test_key_tests_read_the_in_body_complaints_of_bls_and_bea(client):
    assert put_key(client, "bls", "BLS_API_KEY", "invalid-fixture-key")["state"] == "INVALID"
    assert put_key(client, "bea", "BEA_API_KEY", "invalid-fixture-key")["state"] == "INVALID"
    assert put_key(client, "bls", "BLS_API_KEY")["state"] == "OK"
    assert put_key(client, "bea", "BEA_API_KEY")["state"] == "OK"
    assert put_key(client, "census", "CENSUS_API_KEY")["state"] == "OK"


def test_usmac_bls_bea_census_routes(client):
    for name, field in (("bls", "BLS_API_KEY"), ("bea", "BEA_API_KEY"), ("census", "CENSUS_API_KEY")):
        put_key(client, name, field)
    j = client.get("/api/world/usmac", params={"src": "bls", "q": "CPI UNEMP"}).json()
    assert j["data"]["src"] == "BLS" and [s["alias"] for s in j["data"]["series"]] == ["CPI", "UNEMP"]
    assert "FIXTURE" in j["source"] and j["data"]["series"][0]["last_period"] == "2026-08"
    j = client.get("/api/world/usmac", params={"src": "BEA", "q": "GDPG PCEG TRADEBAL"}).json()
    assert [s["alias"] for s in j["data"]["series"]] == ["GDPG", "PCEG", "TRADEBAL"]
    j = client.get("/api/world/usmac", params={"src": "CENSUS", "q": "RETAIL AUTO"}).json()
    assert [s["alias"] for s in j["data"]["series"]] == ["AUTO"] and j["data"]["series"][0]["unit"] == "USD MN"
    j = client.get("/api/world/usmac", params={"src": "CENSUS", "q": "TRADE CHINA 85"}).json()
    assert [s["alias"] for s in j["data"]["series"]] == ["EXPORTS", "IMPORTS", "BALANCE"]
    assert client.get("/api/world/usmac", params={"src": "CENSUS", "q": "TRADE CHINA 61"}).status_code == 404  # fixture: 204 no data
    assert client.get("/api/world/usmac", params={"src": "BLS", "q": "bad!"}).status_code == 400
    assert client.get("/api/world/usmac", params={"src": "XYZ"}).status_code == 400
    assert client.get("/api/world/usmac", params={"src": "BEA", "q": "NOPE"}).status_code == 400


def test_the_four_sources_appear_on_sources_and_keys(client):
    names = {p["name"] for p in client.get("/api/sources").json()["providers"]}
    assert {"comtrade", "bls", "bea", "census"} <= names
    rows = {row["name"]: row for row in client.get("/api/keys").json()["keys"]}
    assert all(rows[n]["state"] == "MISSING" for n in ("comtrade", "bls", "bea", "census"))


# --- the adapter never lets the key into error text -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upstream_error_text_is_redacted_and_statuses_map_to_kinds():
    import httpx

    from openterm.providers.base import ProviderError
    from openterm.providers.tradeus import BeaProvider

    def handler(request: httpx.Request) -> httpx.Response:
        mode = request.url.params.get("mode")
        if mode == "echo":
            return httpx.Response(500, text=f"boom UserID={KEY} {KEY}")
        return httpx.Response({"quota": 429, "denied": 403, "none": 204}[mode])

    p = BeaProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as e:
        await p.bea(KEY, "https://apps.bea.gov/api/data", {"mode": "echo", "UserID": KEY})
    assert e.value.kind == "unavailable" and KEY not in str(e.value)
    for mode, kind in (("quota", "rate_limited"), ("denied", "key_required"), ("none", "not_found")):
        p.bucket.tokens = 10  # the test makes several calls in a row
        with pytest.raises(ProviderError) as e:
            await p.bea(KEY, "https://apps.bea.gov/api/data", {"mode": mode})
        assert e.value.kind == kind and KEY not in str(e.value)
