"""DBSRCH: DBnomics dataset and series search. Parsers run on REAL recordings (scripts/record_dbsearch.py); routes run in fixture mode (no network)."""

import json
from pathlib import Path

import pytest

from openterm.providers.base import ProviderError
from openterm.world import dbsearch, stats

FIX = Path(__file__).parent / "fixtures"


def rec(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


# --- query and reference helpers ---------------------------------------------------------------------------------------
def test_query_words_are_collapsed_and_checked():
    assert dbsearch.norm_query("  france   inflation ", required=True) == "france inflation"
    assert dbsearch.norm_query("   ", required=False) == ""  # a series list may go without words
    for bad in ("", " ", "a", "x" * 121):
        with pytest.raises(ValueError):
            dbsearch.norm_query(bad, required=True)


def test_dataset_reference_accepts_oecd_codes_with_an_at_sign():
    assert dbsearch.parse_dataset_ref("ECB/CSEC") == ("ECB", "CSEC")
    assert dbsearch.parse_dataset_ref("OECD/DSD_TAXBEN_NRR@DF_NRR") == ("OECD", "DSD_TAXBEN_NRR@DF_NRR")
    assert dbsearch.parse_dataset_ref("IMF/WEO:latest") == ("IMF", "WEO:latest")
    for bad in ("", "ECB", "ECB/", "/CSEC", "ECB/CS EC", "ECB/CSEC/extra", None):
        assert dbsearch.parse_dataset_ref(bad) is None


def test_ecst_reference_accepts_a_dataset_with_an_at_sign():
    # DBSRCH lists OECD datasets such as DSD_TAXBEN_NRR@DF_NRR; ECST has to be able to open what DBSRCH hands it.
    assert stats.parse_dbn_ref("DBN:OECD/DSD_TAXBEN_NRR@DF_NRR/AUS.NHIDU.A") == ("OECD", "DSD_TAXBEN_NRR@DF_NRR", "AUS.NHIDU.A")


# --- frequency is read from the series, never guessed -------------------------------------------------------------------
@pytest.mark.parametrize("doc,expected", [
    ({"dimensions": {"FREQ": "A"}}, "ANNUAL"),
    ({"dimensions": {"freq": "m"}}, "MONTHLY"),
    ({"dimensions": {"FREQ": "Q"}}, "QUARTERLY"),
    ({"dimensions": {"FREQ": "D"}}, "DAILY"),
    ({"@frequency": "monthly", "dimensions": {"FREQ": "A"}}, "MONTHLY"),  # the series' own label wins when present
    ({"dimensions": {"FREQ": "Z9"}}, "Z9"),  # an unknown code is shown as written
    ({"dimensions": {"REF_AREA": "FR"}}, ""),  # no frequency dimension: blank, not a guess
    ({}, ""),
    ({"dimensions": ["not", "a", "dict"]}, ""),
])
def test_frequency(doc, expected):
    assert dbsearch.frequency(doc) == expected


# --- datasets (step 1) ---------------------------------------------------------------------------------------------------
def test_datasets_parse_on_the_recorded_search():
    out = dbsearch.parse_datasets(rec("dbnomics_search_france_inflation"))
    assert out["mode"] == "DATASETS" and out["total"] == 90 and out["offset"] == 0 and len(out["items"]) == 20
    first = out["items"][0]
    assert (first["provider"], first["dataset"]) == ("BDF", "ICP")
    assert first["provider_name"] == "Banque de France" and first["matching"] == 6954 and first["series"] == 6954
    assert first["updated"] == "2024-09-20" and first["indexed"] == "2024-11-01"
    ecb = out["items"][1]
    assert (ecb["provider"], ecb["dataset"], ecb["matching"], ecb["series"]) == ("ECB", "CSEC", 741, 738819)
    assert ecb["updated"] is None  # the API gave no provider update date: it stays blank
    assert "CITE THE ORIGINAL PROVIDER" in out["note"]


def test_datasets_keep_the_at_sign_in_oecd_codes():
    out = dbsearch.parse_datasets(rec("dbnomics_search_oecd_unemployment"))
    codes = {i["dataset"] for i in out["items"]}
    assert "DSD_TAXBEN_NRR@DF_NRR" in codes
    assert all(i["provider"] == "OECD" for i in out["items"])


def test_no_match_is_an_empty_list_not_an_error():
    out = dbsearch.parse_datasets(rec("dbnomics_search_nomatch"))
    assert out["items"] == [] and out["total"] == 0


def test_a_dataset_row_without_an_address_is_dropped_not_patched():
    body = {"results": {"num_found": 2, "offset": 0, "docs": [{"name": "no codes"}, {"provider_code": "X", "code": "Y"}]}}
    out = dbsearch.parse_datasets(body)
    assert [(i["provider"], i["dataset"], i["name"]) for i in out["items"]] == [("X", "Y", "Y")]
    assert out["items"][0]["matching"] is None and out["items"][0]["updated"] is None


@pytest.mark.parametrize("body", [None, [], {}, {"results": None}, {"results": {"docs": "no"}}, {"series": {"docs": []}}])
def test_a_changed_answer_shape_is_an_error(body):
    with pytest.raises(ProviderError):
        dbsearch.parse_datasets(body)


# --- series (step 2) -----------------------------------------------------------------------------------------------------
def test_series_parse_on_the_recorded_list():
    out = dbsearch.parse_series(rec("dbnomics_series_bdf_icp_france_inflation"), "BDF", "ICP")
    assert out["mode"] == "SERIES" and out["total"] == 6954 and len(out["items"]) == 30
    assert out["dataset_name"] == "Data on inflation and price developments."
    row = out["items"][0]
    assert row["series"] == "A.AT.N.000000.4.INW" and row["freq"] == "ANNUAL" and row["indexed"] == "2024-11-01"
    assert row["name"].startswith("Austria - HICP")
    assert row["ref"] == "DBN:BDF/ICP/A.AT.N.000000.4.INW"
    assert stats.parse_dbn_ref(row["ref"]) == ("BDF", "ICP", "A.AT.N.000000.4.INW")  # exactly what Enter hands to ECST


def test_series_of_an_oecd_dataset_with_an_at_sign_can_be_opened():
    out = dbsearch.parse_series(rec("dbnomics_series_oecd_nrr_oecd_unemployment"), "OECD", "DSD_TAXBEN_NRR@DF_NRR")
    assert out["total"] == 275520 and len(out["items"]) == 30
    assert all(i["ref"] and i["ref"].startswith("DBN:OECD/DSD_TAXBEN_NRR@DF_NRR/") for i in out["items"])
    assert all(stats.parse_dbn_ref(i["ref"]) for i in out["items"])


def test_a_series_id_ecst_cannot_take_has_no_ref():
    body = {"series": {"num_found": 1, "offset": 0, "docs": [{"series_code": "A B+C", "series_name": "odd", "provider_code": "P", "dataset_code": "D"}]}}
    row = dbsearch.parse_series(body, "P", "D")["items"][0]
    assert row["ref"] is None and row["freq"] == "" and row["indexed"] is None


# --- routes (fixture mode) -----------------------------------------------------------------------------------------------
def test_route_lists_datasets_with_source_and_age(client):
    r = client.get("/api/world/dbsearch", params={"q": "France  Inflation"}).json()  # spaces and case do not matter
    assert r["source"] == "dbnomics · dataset search" and r["stale"] is False and "as_of" in r and "age_s" in r
    assert r["data"]["mode"] == "DATASETS" and len(r["data"]["items"]) == 20 and r["data"]["total"] == 90


def test_route_lists_the_series_of_one_dataset(client):
    r = client.get("/api/world/dbsearch", params={"q": "france inflation", "dataset": "BDF/ICP"}).json()
    assert r["source"] == "dbnomics · BDF/ICP series"
    assert r["data"]["mode"] == "SERIES" and r["data"]["items"][0]["ref"] == "DBN:BDF/ICP/A.AT.N.000000.4.INW"


def test_route_handles_an_oecd_dataset_code_with_an_at_sign(client):
    r = client.get("/api/world/dbsearch", params={"q": "OECD unemployment", "dataset": "OECD/DSD_TAXBEN_NRR@DF_NRR"}).json()
    assert r["data"]["total"] == 275520 and r["data"]["items"][0]["ref"].startswith("DBN:OECD/DSD_TAXBEN_NRR@DF_NRR/")


def test_route_no_match_answers_200_with_no_rows(client):
    resp = client.get("/api/world/dbsearch", params={"q": "zzqxjw"})
    assert resp.status_code == 200 and resp.json()["data"]["items"] == []


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "a"}, {"q": "ok words", "dataset": "nonsense"}, {"q": "x", "dataset": "ECB/CSEC"}])
def test_route_refuses_bad_input(client, params):
    r = client.get("/api/world/dbsearch", params=params)
    assert r.status_code == 400 and r.json()["error"]


def test_route_says_so_when_nothing_is_recorded_instead_of_inventing_rows(client):
    r = client.get("/api/world/dbsearch", params={"q": "something never recorded"})
    assert r.status_code >= 400 and "items" not in json.dumps(r.json())
    page2 = client.get("/api/world/dbsearch", params={"q": "france inflation", "offset": 20})
    assert page2.status_code >= 400


def test_provider_asks_for_small_pages_without_observations(client):
    sent = []

    async def fake_get_json(url, params=None, timeout=None):
        sent.append((url, dict(params or {})))
        return rec("dbnomics_search_nomatch") if url.endswith("/search") else rec("dbnomics_series_bdf_icp_france_inflation")

    prov = client.app.state.service.router.providers["dbnomics"]
    prov.get_json = fake_get_json
    client.app.state.service.cache.mem.clear()
    client.get("/api/world/dbsearch", params={"q": "gdp"})
    client.get("/api/world/dbsearch", params={"q": "gdp", "dataset": "IMF/WEO:latest", "offset": 30})
    client.get("/api/world/dbsearch", params={"dataset": "IMF/WEO:latest"})
    assert sent[0] == ("https://api.db.nomics.world/v22/search", {"q": "gdp", "limit": 20, "offset": 0})
    assert sent[1] == ("https://api.db.nomics.world/v22/series/IMF/WEO:latest", {"q": "gdp", "limit": 30, "offset": 30, "observations": 0, "metadata": 0})
    assert "q" not in sent[2][1]  # no words: the series list is not filtered
