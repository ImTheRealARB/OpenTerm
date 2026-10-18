"""Phase 19 step 4: SECF identifier detection, the OpenFIGI adapter (batching, rate limit, parse, errors) and /api/world/figi."""

import asyncio
import json
import types
from pathlib import Path

import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.openfigi import OpenFigiProvider
from openterm.secf import ids

FIX = Path(__file__).parent / "fixtures"
RECORDED = json.loads((FIX / "openfigi_mapping.json").read_text(encoding="utf-8"))["body"]


# --- identifier detection ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,kind,value", [
    ("US0378331005", "ISIN", "US0378331005"),
    ("us5949181045", "ISIN", "US5949181045"),
    ("037833100", "CUSIP", "037833100"),
    ("2046251", "SEDOL", "2046251"),
    ("0263494", "SEDOL", "0263494"),
    ("B0YBKJ7", "SEDOL", "B0YBKJ7"),
    ("BBG000B9XRY4", "FIGI", "BBG000B9XRY4"),
    ("FIGI:BBG000B9XRY4", "FIGI", "BBG000B9XRY4"),
    ("figi:kkg000000m81", "FIGI", "KKG000000M81"),
])
def test_valid_identifiers_are_recognised(text, kind, value):
    got = ids.classify(text)
    assert got is not None and (got.kind, got.value, got.valid) == (kind, value, True)


@pytest.mark.parametrize("text,kind", [("US0378331006", "ISIN"), ("037833101", "CUSIP"), ("2046252", "SEDOL")])
def test_wrong_check_digit_is_flagged_not_dropped(text, kind):
    got = ids.classify(text)
    assert got is not None and got.kind == kind and got.valid is False


@pytest.mark.parametrize("text", ["AAPL", "APPLE", "MICROSOFT", "RELIANCE.NS", "BRK-B", "", "  ", "12345", "FIGI:", "FIGI:SHORT", "ABCDEFGHIJKL", "BBG00"])
def test_names_and_tickers_are_not_identifiers(text):
    assert ids.classify(text) is None


def test_isin_check_digit_matches_published_values():
    # Published ISINs: Apple, Microsoft, Nestle, BAE Systems, Reliance Industries.
    for isin in ("US0378331005", "US5949181045", "CH0038863350", "GB0002634946", "INE002A01018"):
        assert ids.isin_ok(isin), isin
    assert not ids.isin_ok("US0378331004")


def test_cusip_and_sedol_check_digits():
    assert ids.cusip_ok("037833100") and ids.cusip_ok("594918104") and ids.cusip_ok("38259P508")
    assert not ids.cusip_ok("037833109")
    assert ids.sedol_ok("2046251") and ids.sedol_ok("B0YBKJ7") and not ids.sedol_ok("B0YBKJ8")


def test_split_query_takes_commas_spaces_and_drops_duplicates():
    assert ids.split_query("US0378331005, 037833100 US0378331005;2046251") == ["US0378331005", "037833100", "2046251"]
    assert ids.split_query("   ") == []


def test_id_type_names_are_openfigi_names():
    assert [ids.ID_TYPES[k] for k in ("ISIN", "CUSIP", "SEDOL", "FIGI")] == ["ID_ISIN", "ID_CUSIP", "ID_SEDOL", "ID_BB_GLOBAL"]


# --- parse --------------------------------------------------------------------------------------------------------------
def test_parse_found_not_found_and_error_jobs():
    jobs = [ids.classify("US0378331005"), ids.classify("US0000000002"), ids.classify("037833100")]
    results = [RECORDED["ID_ISIN:US0378331005"], {"warning": "No identifier found."}, {"error": "Invalid idType"}]
    items = ids.parse_mapping(jobs, results)
    assert [i["status"] for i in items] == ["FOUND", "NOT FOUND", "ERROR"]
    assert items[2]["message"] == "Invalid idType"
    first = items[0]["listings"][0]
    assert first["figi"] == first["composite_figi"] == "BBG000B9XRY4"  # the composite listing comes first
    assert first["ticker"] == "AAPL" and first["name"] == "APPLE INC" and first["exch_code"] == "US" and first["security_type"] == "Common Stock"
    assert first["share_class_figi"] == "BBG001S5N8V8"
    assert items[0]["kind"] == "ISIN" and items[0]["id"] == "US0378331005"


def test_parse_moves_the_composite_listing_first_when_upstream_does_not():
    data = [{"figi": "B2", "compositeFIGI": "B1", "ticker": "X", "name": "N", "exchCode": "UA"}, {"figi": "B1", "compositeFIGI": "B1", "ticker": "X", "name": "N", "exchCode": "US"}]
    items = ids.parse_mapping([ids.classify("US0378331005")], [{"data": data}])
    assert [row["figi"] for row in items[0]["listings"]] == ["B1", "B2"]


def test_parse_pads_a_short_answer_instead_of_dropping_jobs():
    jobs = [ids.classify("US0378331005"), ids.classify("037833100")]
    items = ids.parse_mapping(jobs, [RECORDED["ID_ISIN:US0378331005"]])
    assert items[1]["status"] == "ERROR" and "NO ANSWER" in items[1]["message"]


# --- adapter ------------------------------------------------------------------------------------------------------------
def provider(handler) -> OpenFigiProvider:
    return OpenFigiProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok_handler(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request, body))
        return httpx.Response(200, json=[{"warning": "No identifier found."} for _ in body])
    return handler


def make_ids(n: int):
    # n distinct, check-digit-correct CUSIPs: 8 base characters plus the computed digit.
    out = []
    for i in range(n):
        base = f"{i:08d}"
        out.append(ids.classify(base + str(ids.cusip_check(base))))
    assert all(x and x.valid for x in out)
    return out


def test_requests_are_batched_ten_jobs_at_a_time_and_order_is_kept():
    calls: list = []
    p = provider(ok_handler(calls))
    out = asyncio.run(p.figi(make_ids(23)))
    assert [len(body) for _, body in calls] == [10, 10, 3]
    assert [i["id"] for i in out["items"]] == [x.value for x in make_ids(23)]
    req = calls[0][0]
    assert req.method == "POST" and str(req.url) == "https://api.openfigi.com/v3/mapping"
    assert "x-openfigi-apikey" not in {k.lower() for k in req.headers}
    assert calls[0][1][0] == {"idType": "ID_CUSIP", "idValue": make_ids(1)[0].value}
    assert out["source"] == p.source


def test_the_keyless_rate_limit_is_obeyed_with_a_fake_clock(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("openterm.ratelimit.time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    calls: list = []
    p = provider(ok_handler(calls))
    one = make_ids(1)
    for _ in range(25):  # the window allows 25 requests
        asyncio.run(p.figi(one))
    assert len(calls) == 25
    with pytest.raises(ProviderError) as e:
        asyncio.run(p.figi(one))
    assert e.value.kind == "rate_limited" and len(calls) == 25  # refused locally: nothing was sent
    clock[0] += 60.0  # a full window later the bucket is full again
    asyncio.run(p.figi(one))
    assert len(calls) == 26


def test_upstream_429_is_rate_limited_and_5xx_is_unavailable():
    for status, kind in ((429, "rate_limited"), (500, "unavailable"), (403, "unavailable")):
        p = provider(lambda r, s=status: httpx.Response(s, json={"error": "x"}))
        with pytest.raises(ProviderError) as e:
            asyncio.run(p.figi(make_ids(1)))
        assert e.value.kind == kind


def test_a_non_list_answer_is_unavailable_not_a_crash():
    p = provider(lambda r: httpx.Response(200, json={"error": "No API key"}))
    with pytest.raises(ProviderError) as e:
        asyncio.run(p.figi(make_ids(1)))
    assert e.value.kind == "unavailable"


def test_bad_identifiers_never_reach_the_network():
    calls: list = []
    p = provider(ok_handler(calls))
    bad = ids.classify("US0378331006")
    with pytest.raises(ProviderError) as e:
        asyncio.run(p.figi([bad]))
    assert e.value.kind == "unsupported" and not calls


def test_recorded_answer_parses_for_every_recorded_identifier():
    jobs = [ids.classify(k.split(":", 1)[1]) for k in RECORDED]
    items = ids.parse_mapping(jobs, list(RECORDED.values()))
    assert [i["status"] for i in items] == ["FOUND"] * 5 + ["NOT FOUND"]
    assert {i["listings"][0]["ticker"] for i in items[:5]} == {"AAPL", "MSFT"}


# --- route (fixture mode: recorded answers, no network) -----------------------------------------------------------------
def test_route_maps_an_isin_with_the_envelope(client):
    r = client.get("/api/world/figi", params={"q": "US0378331005"}).json()
    assert r["source"].startswith("openfigi")
    items = r["data"]["items"]
    assert items[0]["status"] == "FOUND" and items[0]["kind"] == "ISIN"
    assert items[0]["listings"][0]["ticker"] == "AAPL"
    assert r["data"]["note"].startswith("OPENFIGI")


def test_route_handles_several_identifiers_and_a_not_found(client):
    r = client.get("/api/world/figi", params={"q": "US0378331005 037833100 US0000000002"}).json()
    assert [i["status"] for i in r["data"]["items"]] == ["FOUND", "FOUND", "NOT FOUND"]


def test_route_bad_check_digit_is_said_and_costs_no_request(client):
    r = client.get("/api/world/figi", params={"q": "US0378331006"}).json()
    item = r["data"]["items"][0]
    assert item["status"] == "BAD CHECK DIGIT" and item["listings"] == []


def test_route_rejects_empty_non_identifier_and_too_many(client):
    assert client.get("/api/world/figi", params={"q": "  "}).status_code == 400
    r = client.get("/api/world/figi", params={"q": "APPLE"})
    assert r.status_code == 400 and "ISIN" in r.json()["error"]
    many = " ".join(f"{i:08d}{ids.cusip_check(f'{i:08d}')}" for i in range(26))
    assert client.get("/api/world/figi", params={"q": many}).status_code == 400


def test_route_unrecorded_identifier_in_fixture_mode_is_not_invented(client):
    r = client.get("/api/world/figi", params={"q": "GB0002634946"})
    assert r.status_code == 404 and r.json()["kind"] == "not_found"


def test_openfigi_is_listed_on_sources(client):
    names = {p["name"] for p in client.get("/api/sources").json()["providers"]}
    assert "openfigi" in names
