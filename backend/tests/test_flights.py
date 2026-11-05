"""FLT: live aircraft from OpenSky. No network, no real account.

What is real and what is not (say it plainly):
  - OpenSky refused every connection from the build machine (2026-11-05), so there is NO live recording. `fixtures/opensky_docshape_states.json` and
    `opensky_docshape_token.json` are DOC-SHAPED: invented aircraft in the layout the REST docs describe.
  - The OAuth2 token flow (client credentials, 30 minute token, Bearer header, 401 = expired) follows the docs and is tested with a fake HTTP
    transport and a fake clock. Nothing here has run against a real OpenSky account.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from openterm.providers import opensky as osky
from openterm.providers.base import ProviderError
from openterm.providers.opensky import OpenSkyProvider, check_key
from openterm.world import flights as fl

FIX = Path(__file__).parent / "fixtures"
STATES = json.loads((FIX / "opensky_docshape_states.json").read_text(encoding="utf-8"))["body"]
CID, SECRET = "client-id-test-0001", "client-secret-test-0123456789"


# --- parser -------------------------------------------------------------------------------------------------------------------
def test_parse_states_on_the_doc_shaped_fixture():
    t, rows, no_pos = fl.parse_states(STATES)
    assert t == STATES["time"] and no_pos == 1 and len(rows) == 9  # SIA321 has no position: counted, not shown as a row
    baw = next(r for r in rows if r["icao24"] == "400a1b")
    assert baw["callsign"] == "BAW123" and baw["country"] == "United Kingdom" and baw["on_ground"] is False
    assert baw["alt_m"] == 3048.0 and baw["alt_ft"] == 10000  # 3048 m is exactly 10,000 ft
    assert baw["speed_kt"] == 250 and baw["heading"] == 271 and baw["vrate_fpm"] == -1600  # 128.5 m/s ~ 250 kt; -8.13 m/s ~ -1600 ft/min
    assert baw["source"] == "ADS-B" and baw["age_s"] == 1 + 1 and baw["seen"] == STATES["time"] - 2  # position time, not last contact
    assert {"lat", "lon", "heading", "seen"} <= set(baw)  # the shape a MAP layer would need


def test_missing_values_stay_missing_not_zero():
    _, rows, _ = fl.parse_states(STATES)
    ground = next(r for r in rows if r["icao24"] == "406c11")
    assert ground["on_ground"] is True and ground["alt_ft"] is None and ground["vrate_fpm"] is None  # None, never 0
    nocall = next(r for r in rows if r["icao24"] == "4010ee")
    assert nocall["callsign"] == "" and nocall["squawk"] == "" and nocall["source"] == "MLAT"


def test_null_states_is_an_empty_answer_not_an_error():
    assert fl.parse_states({"time": 5, "states": None}) == (5.0, [], 0)
    assert fl.parse_states({"time": 5, "states": []}) == (5.0, [], 0)


@pytest.mark.parametrize("body", [None, [], {"states": []}, {"time": "x", "states": []}, {"time": 1, "states": "no"}, {"time": 1, "states": [["abc"]]},
                                  {"time": 1, "states": [[None] * 17]}])
def test_wrong_shapes_raise_not_drop(body):
    with pytest.raises(fl.FlightsError) as e:
        fl.parse_states(body)
    assert e.value.kind == "unavailable"


def test_a_non_number_in_a_number_slot_raises():
    row = list(STATES["states"][0])
    row[7] = "3048"  # text where a number belongs: the shape changed
    with pytest.raises(fl.FlightsError):
        fl.parse_states({"time": 1, "states": [row]})


def test_order_puts_airborne_high_first_and_ground_last():
    _, rows, _ = fl.parse_states(STATES)
    ordered = fl.order_rows(rows)
    assert ordered[-1]["on_ground"] is True and ordered[0]["alt_m"] == max(r["alt_m"] or 0 for r in rows)


# --- arguments, boxes and credits ------------------------------------------------------------------------------------------------
def test_presets_are_small_and_cost_one_credit():
    for name, box in fl.PRESETS.items():
        assert fl.area_sq_deg(box) <= 25 and fl.credits_for(box) == 1, name
        assert fl.check_box(*box) == box


def test_credit_cost_follows_the_documented_area_bands():
    assert fl.credits_for((0, 0, 5, 5)) == 1       # 25 sq deg
    assert fl.credits_for((0, 0, 5, 5.1)) == 2     # just over 25
    assert fl.credits_for((0, 0, 10, 10)) == 2     # 100
    assert fl.credits_for((0, 0, 10, 10.5)) == 3
    assert fl.credits_for((0, 0, 20, 20)) == 3     # 400
    assert fl.credits_for((0, 0, 21, 20)) == 4
    assert fl.credits_for(None) == 4               # a global (CALLSIGN) call


@pytest.mark.parametrize("args", [("a", "b", "c", "d"), (10, 0, 5, 1), (0, 10, 1, 5), (-91, 0, 0, 1), (0, 0, 1, 181), (0, 0, 20, 20),
                                  (float("nan"), 0, 1, 1), (float("inf"), 0, 1, 1)])
def test_bad_boxes_are_refused(args):
    with pytest.raises(fl.FlightsError) as e:
        fl.check_box(*args)
    assert e.value.kind == "bad_request"


def test_parse_args():
    assert fl.parse_args("london") == ("AREA", "LONDON", fl.PRESETS["LONDON"], None)
    assert fl.parse_args("BOX 51 -1 52 1")[:3] == ("BOX", "BOX 51 -1 52 1", (51.0, -1.0, 52.0, 1.0))
    assert fl.parse_args("callsign baw") == ("CALLSIGN", "CALLSIGN BAW", None, "BAW")
    for bad in ("", "ATLANTIS", "BOX 1 2 3", "CALLSIGN", "CALLSIGN TOOLONGONE", "CALLSIGN B-A", "LONDON NYC"):
        with pytest.raises(fl.FlightsError):
            fl.parse_args(bad)


def test_the_panels_preset_list_equals_the_backends():
    ts = (Path(__file__).parents[2] / "frontend" / "src" / "functions" / "fltArgs.ts").read_text(encoding="utf-8")
    import re

    listed = re.search(r"FLT_AREAS = \[(.*?)\]", ts, re.DOTALL).group(1)
    assert re.findall(r'"([A-Z]+)"', listed) == list(fl.PRESETS)


# --- the provider, with a fake transport and a fake clock ---------------------------------------------------------------------------
class Net:
    """A fake OpenSky: counts calls, hands out tokens, and can be told to answer 429 or 401."""

    def __init__(self):
        self.states_calls: list[httpx.Request] = []
        self.token_calls = 0
        self.token_ttl = 1800
        self.next_states = None  # a Response to return once instead of the normal answer
        self.valid_tokens: set[str] = set()
        self.bad_login = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.host == "auth.opensky-network.org":
            self.token_calls += 1
            if self.bad_login:
                return httpx.Response(401, json={"error": "unauthorized_client"})
            tok = f"tok-{self.token_calls}-abcdefghijklmnop"
            self.valid_tokens.add(tok)
            return httpx.Response(200, json={"access_token": tok, "expires_in": self.token_ttl, "token_type": "Bearer"})
        self.states_calls.append(req)
        auth = req.headers.get("authorization")
        if auth is not None and auth.removeprefix("Bearer ") not in self.valid_tokens:
            return httpx.Response(401, json={})
        if self.next_states is not None:
            r, self.next_states = self.next_states, None
            return r
        return httpx.Response(200, json=STATES, headers={"X-Rate-Limit-Remaining": "391"})


def make(net: Net, keys: bool = False) -> tuple[OpenSkyProvider, list[float]]:
    p = OpenSkyProvider(httpx.AsyncClient(transport=httpx.MockTransport(net)))
    now = [1_000_000.0]
    p.clock = lambda: now[0]
    p.bucket.acquire = _noop  # our own pacing bucket is not under test
    if keys:
        p.set_keys({"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": SECRET})
    return p, now


async def _noop(*_a, **_k):
    return None


BOX = fl.PRESETS["LONDON"]


async def test_anonymous_call_sends_the_box_and_no_token_and_reads_the_credit_header():
    net = Net()
    p, _ = make(net)
    meta = await p.flights(BOX)
    req = net.states_calls[0]
    assert dict(req.url.params) == {"lamin": "51.3", "lomin": "-0.6", "lamax": "51.7", "lomax": "0.2"} and "authorization" not in req.headers
    assert net.token_calls == 0 and meta["authenticated"] is False and meta["credits_remaining"] == 391 and len(meta["rows"]) == 9


async def test_identical_box_is_served_from_memory_for_30_seconds_then_refetched():
    net = Net()
    p, now = make(net)
    await p.flights(BOX)
    now[0] += 29
    await p.flights(BOX)
    assert len(net.states_calls) == 1  # credits protected
    await p.flights(fl.PRESETS["NYC"])
    assert len(net.states_calls) == 2  # another box is another call
    now[0] += 2
    await p.flights(BOX)
    assert len(net.states_calls) == 3  # 31 s later: a fresh call


async def test_429_is_reported_with_the_wait_and_no_further_call_is_made_until_then():
    net = Net()
    net.next_states = httpx.Response(429, headers={"X-Rate-Limit-Retry-After-Seconds": "3600"}, json={})
    p, now = make(net)
    with pytest.raises(ProviderError) as e:
        await p.flights(BOX)
    assert e.value.kind == "rate_limited" and "RETRY IN 60 MIN" in str(e.value) and "ANONYMOUS" in str(e.value)
    for _ in range(3):  # the user hammering F5: each one is refused locally, without touching the network
        with pytest.raises(ProviderError) as e2:
            await p.flights(fl.PRESETS["NYC"])
        assert e2.value.kind == "rate_limited" and "NO NEW CALL" in str(e2.value)
    assert len(net.states_calls) == 1
    now[0] += 3601
    assert (await p.flights(BOX))["rows"]  # after the stated time it works again
    assert len(net.states_calls) == 2


async def test_429_without_a_retry_header_says_so_and_still_backs_off():
    net = Net()
    net.next_states = httpx.Response(429, json={})
    p, _ = make(net)
    with pytest.raises(ProviderError) as e:
        await p.flights(BOX)
    assert "NO RETRY TIME SENT" in str(e.value) and "60 S" in str(e.value)


async def test_server_errors_and_junk_are_provider_errors():
    for resp, word in ((httpx.Response(503), "HTTP 503"), (httpx.Response(200, content=b"<html>"), "NON-JSON"), (httpx.Response(200, json={"x": 1}), "time/states")):
        net = Net()
        net.next_states = resp
        p, _ = make(net)
        with pytest.raises(ProviderError) as e:
            await p.flights(BOX)
        assert e.value.kind == "unavailable" and word in str(e.value)


async def test_empty_box_is_a_normal_answer():
    net = Net()
    net.next_states = httpx.Response(200, json={"time": 7, "states": None})
    p, _ = make(net)
    meta = await p.flights(BOX)
    assert meta["rows"] == [] and meta["received"] == 0


# --- OAuth2 (docs-shaped) -----------------------------------------------------------------------------------------------------------
async def test_signed_in_call_fetches_one_token_and_sends_it_as_bearer():
    net = Net()
    p, _ = make(net, keys=True)
    meta = await p.flights(BOX)
    assert net.token_calls == 1 and meta["authenticated"] is True
    assert net.states_calls[0].headers["authorization"] == "Bearer tok-1-abcdefghijklmnop"
    await p.flights(fl.PRESETS["NYC"])
    assert net.token_calls == 1  # reused, not fetched per call


async def test_token_is_refreshed_before_it_expires_using_the_clock():
    net = Net()
    p, now = make(net, keys=True)
    await p.flights(BOX)
    now[0] += 1800 - osky.REFRESH_MARGIN_S - 5  # still 65 s of life left: keep it
    await p.flights(fl.PRESETS["NYC"])
    assert net.token_calls == 1
    now[0] += 10  # 55 s left: inside the refresh margin
    await p.flights(fl.PRESETS["DUBAI"])
    assert net.token_calls == 2 and net.states_calls[-1].headers["authorization"] == "Bearer tok-2-abcdefghijklmnop"


async def test_a_401_drops_the_token_and_retries_exactly_once():
    net = Net()
    p, _ = make(net, keys=True)
    await p.flights(BOX)
    net.valid_tokens.clear()  # the server has forgotten our token early
    net.valid_tokens.add("tok-2-abcdefghijklmnop")  # ...and will accept the next one it hands out
    meta = await p.flights(fl.PRESETS["NYC"])
    assert net.token_calls == 2 and meta["authenticated"] is True
    assert len(net.states_calls) == 1 + 2  # the first call, then the rejected one and its single retry


async def test_a_second_401_is_an_error_not_a_loop():
    net = Net()
    p, _ = make(net, keys=True)
    await p.flights(BOX)
    net.valid_tokens.clear()
    net.token_ttl = 1800

    def never_valid(req):  # every token we get is rejected
        if req.url.host == "auth.opensky-network.org":
            net.token_calls += 1
            return httpx.Response(200, json={"access_token": f"zz-{net.token_calls}-abcdefghijkl", "expires_in": 1800})
        net.states_calls.append(req)
        return httpx.Response(401, json={})

    p.http = httpx.AsyncClient(transport=httpx.MockTransport(never_valid))
    before = len(net.states_calls)
    with pytest.raises(ProviderError) as e:
        await p.flights(fl.PRESETS["NYC"])
    assert "TWICE" in str(e.value) and len(net.states_calls) - before == 2


async def test_a_rejected_login_fails_loudly_and_never_falls_back_to_anonymous():
    net = Net()
    net.bad_login = True
    p, _ = make(net, keys=True)
    with pytest.raises(ProviderError) as e:
        await p.flights(BOX)
    assert e.value.kind == "unavailable" and "LOGIN REJECTED" in str(e.value) and SECRET not in str(e.value)
    assert net.states_calls == []  # no anonymous call was made behind the user's back


async def test_a_token_answer_without_expiry_is_refused():
    def odd(req):
        return httpx.Response(200, json={"access_token": "abcdefghijklmnopqrst"})

    p = OpenSkyProvider(httpx.AsyncClient(transport=httpx.MockTransport(odd)))
    p.set_keys({"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": SECRET})
    with pytest.raises(ProviderError) as e:
        await p.flights(BOX)
    assert "access_token/expires_in" in str(e.value)


async def test_changing_the_keys_drops_the_token_and_the_cache():
    net = Net()
    p, _ = make(net, keys=True)
    await p.flights(BOX)
    p.set_keys(None)
    assert p.has_key is False and p._token == "" and p._cache == {}
    meta = await p.flights(BOX)
    assert meta["authenticated"] is False and "authorization" not in net.states_calls[-1].headers


async def test_secret_and_token_are_registered_for_redaction():
    from openterm import redact

    net = Net()
    p, _ = make(net, keys=True)
    await p.flights(BOX)
    assert SECRET not in redact.redact(f"boom {SECRET} and tok-1-abcdefghijklmnop")
    assert "tok-1-abcdefghijklmnop" not in redact.redact("Bearer tok-1-abcdefghijklmnop")


def test_only_both_halves_count_as_a_login():
    p = OpenSkyProvider(None)
    p.set_keys({"OPENSKY_CLIENT_ID": CID})
    assert p.has_key is False
    p.set_keys({"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": SECRET})
    assert p.has_key is True


# --- key test classification -------------------------------------------------------------------------------------------------------
async def test_key_test_classification():
    vals = {"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": SECRET}

    def client(status, body):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)))

    assert await check_key(vals, client(200, {"access_token": "x" * 20, "expires_in": 1800})) == ("OK", None)
    assert (await check_key(vals, client(401, {"error": "unauthorized_client"})))[0] == "INVALID"
    assert (await check_key(vals, client(400, {"error": "invalid_request"})))[0] == "INVALID"
    assert (await check_key(vals, client(503, {})))[0] == "ERROR"
    assert (await check_key(vals, client(200, {"nope": 1})))[0] == "ERROR"

    def boom(_r):
        raise httpx.ConnectError("no route", request=_r)

    assert (await check_key(vals, httpx.AsyncClient(transport=httpx.MockTransport(boom)))) == ("ERROR", "ConnectError")


def test_the_key_is_one_optional_spec_with_a_masked_secret():
    from openterm.keys import KEY_SPECS, TESTS

    spec = KEY_SPECS["opensky"]
    assert spec.fields == ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET") and spec.secrets == ("OPENSKY_CLIENT_SECRET",)
    assert "optional" in spec.purpose.lower() and "opensky" not in TESTS  # its test is the token request in run_test


async def test_run_test_in_fixture_mode_uses_the_fixture_token_endpoint(tmp_path):
    from openterm import keys as keystore
    from openterm.providers.fixtures import fixture_transport

    http = httpx.AsyncClient(transport=fixture_transport())
    store = keystore.KeyStore(env={"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": SECRET}, dotenv=tmp_path / ".env", keyring=keystore.MemoryKeyring())
    assert (await keystore.run_test(store, "opensky", http, fixtures=True))["state"] == "OK"
    bad = keystore.KeyStore(env={"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": "wrong-secret-value"}, dotenv=tmp_path / ".env2",
                            keyring=keystore.MemoryKeyring())
    assert (await keystore.run_test(bad, "opensky", http, fixtures=True))["state"] == "INVALID"


# --- the route (fixture mode) ------------------------------------------------------------------------------------------------------------
def test_route_works_with_no_key_and_labels_anonymous_and_doc_shaped(client):
    r = client.get("/api/world/flt", params={"q": "LONDON"})
    assert r.status_code == 200
    j = r.json()
    d = j["data"]
    assert j["source"] == "OPENSKY" and d["authenticated"] is False and "ANONYMOUS: LIMITED CREDITS" in d["access"] and d["fixture"] is True
    assert "AS REPORTED BY AIRCRAFT TRANSPONDERS" in d["note"] and "COVERAGE IS PARTIAL" in d["note"]
    assert d["credits_cost"] == 1 and d["credits_remaining"] == 397
    assert {r_["icao24"] for r_ in d["rows"]} == {"400a1b", "4ca7b2", "406c11", "4010ee"}  # only aircraft inside the box
    assert all(51.3 <= r_["lat"] <= 51.7 for r_ in d["rows"])


def test_route_with_a_key_is_signed_in_and_never_echoes_the_secret(client):
    client.put("/api/keys/opensky", json={"fields": {"OPENSKY_CLIENT_ID": CID, "OPENSKY_CLIENT_SECRET": SECRET}})
    r = client.get("/api/world/flt", params={"q": "NYC"})
    assert r.status_code == 200 and SECRET not in r.text and "fixture-token" not in r.text
    d = r.json()["data"]
    assert d["authenticated"] is True and "SIGNED IN" in d["access"] and d["credits_remaining"] == 3996


def test_route_callsign_search_filters_the_global_answer_and_states_the_cost(client):
    d = client.get("/api/world/flt", params={"q": "CALLSIGN SIA"}).json()["data"]
    assert d["credits_cost"] == 4 and d["no_position"] == 1 and [r["callsign"] for r in d["rows"]] == ["SIA7"]
    assert client.get("/api/world/flt", params={"q": "CALLSIGN QQQ"}).json()["data"]["rows"] == []


def test_route_empty_box_is_empty_not_invented(client):
    d = client.get("/api/world/flt", params={"q": "BOX 0 0 1 1"}).json()["data"]
    assert d["rows"] == [] and d["received"] == 0


def test_route_refuses_bad_arguments(client):
    for q in ("", "ATLANTIS", "BOX 1 2 3", "BOX 0 0 50 50", "CALLSIGN"):
        r = client.get("/api/world/flt", params={"q": q})
        assert r.status_code == 400, q


def test_sources_lists_opensky(client):
    s = client.get("/api/sources").json()
    assert "opensky" in {p["name"] for p in s["providers"]}


def test_the_fixtures_are_labelled_doc_shaped_and_hold_no_secret():
    for name in ("opensky_docshape_states.json", "opensky_docshape_token.json"):
        rec = json.loads((FIX / name).read_text(encoding="utf-8"))
        assert "DOC-SHAPED" in rec["note"] and "NOT A RECORDING" in rec["note"]


def test_route_says_when_to_retry_after_a_429_not_just_provider_down(client):
    prov = client.app.state.service.router.providers["opensky"]
    prov._blocked_until = prov.clock() + 3600  # as if OpenSky had just answered 429 with a one hour wait
    r = client.get("/api/world/flt", params={"q": "DUBAI"})
    assert r.status_code == 503 and r.json()["kind"] == "unavailable"
    assert "NO NEW CALL FOR" in r.json()["error"] and "MIN" in r.json()["error"]
