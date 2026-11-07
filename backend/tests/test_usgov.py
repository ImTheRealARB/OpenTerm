"""USASP, FEDREG (keyless, REAL recordings) and FEC, CONGRESS (free api.data.gov keys, DOC-SHAPED fixtures).

Status of the data behind these tests:
  - REAL recordings (scripts/record_usgov.py, 2026-11-05): every `usasp_real_*` and `fedreg_real_*` file, and the api.data.gov gateway's answers to NO key and to a
    made-up key (`keytest_datagov_*`: HTTP 403 API_KEY_MISSING / API_KEY_INVALID).
  - DOC-SHAPED (invented numbers, each file says "NOT A RECORDING"): every successful FEC and Congress.gov answer (`fec_*_docshape`, `congress_*_docshape`).
    The first call with a real key is the real test of those two shapes.
Fixture mode accepts only keys that start with "docshape" for the two keyed hosts (providers/fixtures.py).
"""

import json
from datetime import date

import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.fixtures import FIXTURES
from openterm.providers.usgov import CongressProvider, OpenFecProvider
from openterm.world import congress, fec, fedreg, usaspending
from openterm.world.usgov import UsGovError

KEY = "docshape_key_0123456789"


def body(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["body"]


def mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- USASP: pure parsers over real recordings ------------------------------------------------------------------------------

def test_fiscal_window_counts_october_into_the_next_fiscal_year():
    w = usaspending.fiscal_window(date(2026, 11, 5))  # FY2027 has begun (1 Oct 2026): three fiscal years = FY2025..FY2027
    assert w["start_date"] == "2024-10-01" and w["end_date"] == "2026-11-05" and w["label"].startswith("FY2025")
    assert usaspending.fiscal_window(date(2026, 3, 1))["start_date"] == "2023-10-01"  # FY2026: FY2024..FY2026


def test_usasp_query_words():
    assert usaspending.norm_query("") == ("agency", "") and usaspending.norm_query("agency") == ("agency", "")
    assert usaspending.norm_query("  lockheed   martin ") == ("keyword", "lockheed martin")
    with pytest.raises(UsGovError) as e:
        usaspending.norm_query("x")
    assert e.value.kind == "bad_request"


def test_usasp_parses_the_real_recipient_award_and_agency_answers():
    rec = usaspending.parse_recipients(body("usasp_real_recipient_lockheed"))
    assert rec[0]["name"] == "LOCKHEED MARTIN CORPORATION" and rec[0]["amount"] > 1e9 and rec[0]["uei"]
    awards = usaspending.parse_awards(body("usasp_real_awards_lockheed"))
    assert awards[0]["award_id"] and awards[0]["amount"] >= awards[1]["amount"] and all(len(a["description"]) <= 120 for a in awards)
    ag = usaspending.parse_agencies(body("usasp_real_agency"))
    assert ag[0]["code"] == "HHS" and ag[0]["amount"] > 1e12
    assert usaspending.parse_recipients(body("usasp_real_recipient_none")) == [] and usaspending.parse_awards(body("usasp_real_awards_none")) == []


def test_usasp_a_changed_shape_fails_loudly_not_as_an_empty_table():
    with pytest.raises(UsGovError):
        usaspending.parse_recipients({"detail": "oops"})
    with pytest.raises(UsGovError):
        usaspending.parse_awards({"results": [{"no": "award id"}]})


def test_usasp_request_bodies_carry_the_documented_filters():
    w = usaspending.fiscal_window(date(2026, 11, 5))
    b = usaspending.recipient_body(w, "lockheed martin")
    assert b["filters"]["keywords"] == ["lockheed martin"] and b["filters"]["award_type_codes"] == ["A", "B", "C", "D"]
    assert b["filters"]["time_period"] == [{"start_date": "2024-10-01", "end_date": "2026-11-05"}]
    assert "award_type_codes" not in usaspending.agency_body(w)["filters"]  # the agency view counts every award type
    assert usaspending.recipient_in_agency_body(w, "Department of Defense")["filters"]["agencies"][0]["name"] == "Department of Defense"


# --- FEDREG --------------------------------------------------------------------------------------------------------------------

def test_fedreg_query_type_word_and_params():
    assert fedreg.parse_query("") == (None, "") and fedreg.parse_query("rule chips act") == ("RULE", "chips act")
    assert fedreg.parse_query("proposed") == ("PRORULE", "") and fedreg.parse_query("chips rule") == (None, "chips rule")
    p = fedreg.params("RULE", "chips")
    assert ("conditions[term]", "chips") in p and ("conditions[type][]", "RULE") in p and ("order", "newest") in p
    assert [v for k, v in p if k == "fields[]"] == list(fedreg.FIELDS)  # repeated keys, in order
    with pytest.raises(UsGovError):
        fedreg.parse_query("x" * 101)


def test_fedreg_parses_the_real_answers_including_the_one_with_no_results_key():
    out = fedreg.parse(body("fedreg_real_semiconductor"), None, "semiconductor")
    assert out["total"] > 100 and out["shown"] == len(out["items"]) == 15
    first = out["items"][0]
    assert first["number"] and first["title"] and first["url"].startswith("https://www.federalregister.gov/") and first["date"]
    assert {i["type"] for i in out["items"]} <= {"Rule", "Proposed Rule", "Notice", "Presidential Document"}
    latest = fedreg.parse(body("fedreg_real_latest"), None, "")["items"]
    assert all(i["abstract"] is None or i["abstract"] for i in latest)  # a missing abstract is None, never an empty string
    empty = fedreg.parse(body("fedreg_real_none"), None, "zzqxqx")  # the real empty answer has no "results" key at all
    assert empty["total"] == 0 and empty["items"] == []
    assert all(i["type"] == "Rule" for i in fedreg.parse(body("fedreg_real_rules_only"), "RULE", "semiconductor")["items"])
    with pytest.raises(UsGovError):
        fedreg.parse({"count": 5}, None, "x")  # a count with no list is not the documented shape


# --- FEC (doc-shaped) ----------------------------------------------------------------------------------------------------------

def test_fec_query_kinds():
    assert fec.norm_query("h0zz00001") == ("candidate", "H0ZZ00001") and fec.norm_query("C00000001") == ("committee", "C00000001")
    assert fec.norm_query("smith") == ("search", "smith")
    with pytest.raises(UsGovError):
        fec.norm_query("a")


def test_fec_parsers_on_doc_shaped_fixtures_and_a_changed_shape_failing():
    c = fec.parse_candidates(body("fec_candidates_search_docshape"))
    assert c[0]["id"] == "H0ZZ00001" and c[0]["kind"] == "CANDIDATE" and c[0]["last_year"] == 2026 and c[0]["office"] == "House"
    m = fec.parse_committees(body("fec_committees_docshape"))
    assert m[0]["id"] == "C00000001" and m[0]["kind"] == "COMMITTEE" and m[0]["office"] == "House"
    t = fec.parse_totals(body("fec_candidate_totals_docshape"))
    assert [x["cycle"] for x in t] == [2026, 2024, 2022] and t[0]["receipts"] == 1250000.5 and t[0]["individual"] == 950000.5  # itemised + unitemised
    assert t[0]["covered_to"] == "2026-12-31"
    assert fec.parse_totals(body("fec_committee_totals_docshape"))[0]["individual"] == 950000.5  # committees report one figure
    assert fec.parse_name(body("fec_candidate_entity_docshape")) == "EXAMPLE, TEST A" and fec.parse_name({"results": []}) is None
    with pytest.raises(UsGovError):
        fec.parse_candidates({"error": "x"})
    with pytest.raises(UsGovError):
        fec.parse_totals({"results": [{"receipts": 1}]})


# --- CONGRESS (doc-shaped) -----------------------------------------------------------------------------------------------------

def test_congress_number_for_a_date():
    assert congress.current_congress(date(2026, 11, 5)) == 119 and congress.current_congress(date(2025, 1, 3)) == 119
    assert congress.current_congress(date(2025, 1, 2)) == 118 and congress.current_congress(date(2023, 6, 1)) == 118


def test_congress_query_forms():
    today = date(2026, 11, 5)
    assert congress.parse_query("", today) == ("latest", None)
    assert congress.parse_query("H.R. 1234", today) == ("bill", (119, "HR", 1234))
    assert congress.parse_query("118 s 55", today) == ("bill", (118, "S", 55))
    assert congress.parse_query("hjres77", today) == ("bill", (119, "HJRES", 77))
    assert congress.parse_query("Semiconductor Supply", today) == ("words", ["semiconductor", "supply"])
    with pytest.raises(UsGovError):
        congress.parse_query("a", today)


def test_congress_parsers_on_doc_shaped_fixtures():
    rows = congress.parse_list(body("congress_bills_list_docshape"))
    assert [r["type"] + r["number"] for r in rows] == ["HR9001", "S4242", "HJRES77"] and rows[0]["action_date"] == "2026-11-03"
    assert [r["number"] for r in congress.filter_words(rows, ["semiconductor"])] == ["4242"]
    assert congress.filter_words(rows, ["semiconductor", "nothing"]) == []
    bill = congress.parse_bill(body("congress_bill_detail_docshape"))
    assert bill["sponsors"] == ["Rep. Example, Test A [I-ZZ-1]"] and bill["cosponsors"] == 4 and bill["policy_area"].startswith("Government")
    p = congress.list_payload("TITLE FILTER", "semiconductor", 250, rows[1:2])
    assert "250 MOST RECENTLY UPDATED" in p["note"] and p["matched"] == 1
    assert congress.list_params(25)["sort"] == "updateDate desc"  # httpx turns the space into "+": updateDate+desc
    with pytest.raises(UsGovError):
        congress.parse_bill({"nope": 1})


# --- providers: the key rules ----------------------------------------------------------------------------------------------------

def make(cls, handler):
    p = cls(mock(handler), source=f"{cls.name}:fixture", fixture=True)
    p.bucket.tokens = 100  # no waiting in tests
    return p


async def test_no_key_raises_key_required_before_any_network_call():
    calls = []
    p = make(OpenFecProvider, lambda r: calls.append(r) or httpx.Response(200, json={}))
    for fn in (lambda: p.fec_search("smith"), lambda: p.fec_entity("CANDIDATE", "H0ZZ00001")):
        with pytest.raises(ProviderError) as e:
            await fn()
        assert e.value.kind == "key_required"
    assert calls == []


async def test_key_goes_in_the_header_never_the_url_and_a_refused_key_never_echoes():
    seen = []

    def handler(r: httpx.Request):
        seen.append(r)
        return httpx.Response(200, json=body("congress_bills_list_docshape"))

    p = make(CongressProvider, handler)
    p.set_keys({"CONGRESS_API_KEY": KEY})
    assert (await p.cg_list(25))[0]["number"] == "9001"
    assert seen[0].headers["x-api-key"] == KEY and KEY not in str(seen[0].url) and seen[0].url.params["sort"] == "updateDate desc"
    refused = make(CongressProvider, lambda r: httpx.Response(403, json=body("keytest_datagov_congress_invalid")))
    refused.set_keys({"CONGRESS_API_KEY": KEY})
    with pytest.raises(ProviderError) as e:
        await refused.cg_list(5)
    assert e.value.kind == "key_required" and KEY not in str(e.value)
    limited = make(CongressProvider, lambda r: httpx.Response(429, json={"error": {"code": "OVER_RATE_LIMIT"}}))
    limited.set_keys({"CONGRESS_API_KEY": KEY})
    with pytest.raises(ProviderError) as e2:
        await limited.cg_list(5)
    assert e2.value.kind == "rate_limited" and KEY not in str(e2.value)


async def test_fec_search_keeps_one_half_when_the_other_fails_and_raises_when_both_do():
    def half(r: httpx.Request):
        return httpx.Response(200, json=body("fec_candidates_search_docshape")) if "candidates" in r.url.path else httpx.Response(500, text="boom")

    p = make(OpenFecProvider, half)
    p.set_keys({"FEC_API_KEY": KEY})
    out = await p.fec_search("example")
    assert [c["id"] for c in out["candidates"]] == ["H0ZZ00001"] and out["committees"] == [] and "COMMITTEES NOT LOADED" in out["notes"][0]
    both = make(OpenFecProvider, lambda r: httpx.Response(500, text="boom"))
    both.set_keys({"FEC_API_KEY": KEY})
    with pytest.raises(ProviderError):
        await both.fec_search("example")


async def test_fec_unknown_id_is_not_found():
    p = make(OpenFecProvider, lambda r: httpx.Response(200, json={"results": []}))
    p.set_keys({"FEC_API_KEY": KEY})
    with pytest.raises(ProviderError) as e:
        await p.fec_entity("CANDIDATE", "H0ZZ99999")
    assert e.value.kind == "not_found"


# --- the app: key specs, tests, routes ---------------------------------------------------------------------------------------------

def test_key_specs_and_tests_exist_for_the_two_data_gov_sources():
    from openterm.keys import KEY_SPECS, TESTS, classify

    for name, field in (("openfec", "FEC_API_KEY"), ("congressgov", "CONGRESS_API_KEY")):
        assert KEY_SPECS[name].fields == (field,) and KEY_SPECS[name].signup == "https://api.data.gov/signup/" and name in TESTS
        method, url, params, headers, _ = TESTS[name]({field: "abc"})
        assert method == "GET" and headers == {"X-Api-Key": "abc"} and "abc" not in url + str(params)  # header, never the URL
    assert classify(403, json.dumps(body("keytest_datagov_fec_invalid"))) == "INVALID"
    assert classify(429, '{"error": {"code": "OVER_RATE_LIMIT"}}') == "QUOTA"


def test_usasp_over_http_keyword_agency_and_drill_down(client):
    k = client.get("/api/world/usasp", params={"q": "lockheed martin"}).json()
    d = k["data"]
    assert d["mode"] == "KEYWORD" and d["award_kind"] == "CONTRACTS" and d["recipients"][0]["name"] == "LOCKHEED MARTIN CORPORATION"
    assert d["recipients_total"] > 1e10 and d["awards"][0]["award_id"] and d["notes"] == [] and "OBLIGATED" in d["note"] and k["source"] == "USASPENDING.GOV"
    a = client.get("/api/world/usasp").json()["data"]
    assert a["mode"] == "AGENCY" and a["agencies"][0]["code"] == "HHS" and a["award_kind"] == "ALL AWARD TYPES"
    dd = client.get("/api/world/usasp", params={"q": "AGENCY:Department of Defense"}).json()["data"]
    assert dd["mode"] == "AGENCY_RECIPIENTS" and dd["agency"] == "Department of Defense" and dd["recipients"]
    none = client.get("/api/world/usasp", params={"q": "zzqxqx nonexistent"}).json()["data"]
    assert none["recipients"] == [] and none["awards"] == [] and none["recipients_total"] is None
    assert client.get("/api/world/usasp", params={"q": "x"}).status_code == 400


def test_fedreg_over_http(client):
    d = client.get("/api/world/fedreg", params={"q": "semiconductor"}).json()["data"]
    assert d["total"] > 100 and d["items"][0]["number"] and "AGENCY'S OWN SUMMARY" in d["note"]
    r = client.get("/api/world/fedreg", params={"q": "rule semiconductor"}).json()["data"]
    assert r["type"] == "RULES" and all(i["type"] == "Rule" for i in r["items"])
    assert client.get("/api/world/fedreg").json()["data"]["shown"] == 15
    assert client.get("/api/world/fedreg", params={"q": "zzqxqx nonexistent"}).json()["data"]["items"] == []


@pytest.mark.parametrize(("name", "field", "path", "params"), [
    ("openfec", "FEC_API_KEY", "/api/world/fec", {"q": "example"}),
    ("congressgov", "CONGRESS_API_KEY", "/api/world/congress", {}),
])
def test_keyed_routes_say_key_required_without_a_key_and_work_with_one(client, name, field, path, params):
    r = client.get(path, params=params)
    assert r.status_code == 424 and r.json()["key"] == field and r.json()["detail"] == f"KEY REQUIRED: set {field} in APIKEYS"
    put = client.put(f"/api/keys/{name}", json={"fields": {field: KEY}})
    assert put.status_code == 200 and put.json()["state"] == "OK" and KEY not in put.text  # fixture mode accepts "docshape" keys
    r = client.get(path, params=params)
    assert r.status_code == 200 and "NOT A RECORDING" in r.json()["source"] and not r.json()["stale"]


@pytest.mark.parametrize(("name", "field"), [("openfec", "FEC_API_KEY"), ("congressgov", "CONGRESS_API_KEY")])
def test_a_key_the_gateway_would_refuse_is_invalid_and_never_echoed(client, name, field):
    put = client.put(f"/api/keys/{name}", json={"fields": {field: "a-key-the-fixtures-refuse-0123"}})
    assert put.status_code == 200 and put.json()["state"] == "INVALID" and "a-key-the-fixtures-refuse" not in put.text


def test_fec_and_congress_views_over_http(client):
    client.put("/api/keys/openfec", json={"fields": {"FEC_API_KEY": KEY}})
    client.put("/api/keys/congressgov", json={"fields": {"CONGRESS_API_KEY": KEY}})
    s = client.get("/api/world/fec", params={"q": "example"}).json()["data"]
    assert s["mode"] == "SEARCH" and [i["id"] for i in s["items"]] == ["H0ZZ00001", "C00000001"] and "SELF-REPORTED" in s["note"]
    c = client.get("/api/world/fec", params={"q": "H0ZZ00001"}).json()["data"]
    assert c["mode"] == "CANDIDATE" and c["name"] == "EXAMPLE, TEST A" and c["latest"]["cycle"] == 2026 and len(c["cycles"]) == 3
    assert client.get("/api/world/fec", params={"q": "C00000001"}).json()["data"]["mode"] == "COMMITTEE"
    gone = client.get("/api/world/fec", params={"q": "H0ZZ99999"})
    assert gone.status_code == 404 and "H0ZZ99999" in gone.json()["error"]
    latest = client.get("/api/world/congress").json()["data"]
    assert latest["mode"] == "LATEST" and len(latest["items"]) == 3 and "THE LIST HAS NO SPONSOR" in latest["note"]
    f = client.get("/api/world/congress", params={"q": "semiconductor"}).json()["data"]
    assert f["mode"] == "TITLE FILTER" and [i["number"] for i in f["items"]] == ["4242"] and f["fetched"] == 3 and "NO FULL-TEXT SEARCH" in f["note"]
    b = client.get("/api/world/congress", params={"q": "HR 9001"}).json()["data"]
    assert b["mode"] == "BILL" and b["sponsors"] and b["cosponsors"] == 4
    missing = client.get("/api/world/congress", params={"q": "HR 1"})
    assert missing.status_code == 404 and "HR" in missing.json()["error"]
