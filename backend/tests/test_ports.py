"""PORTS: IMF PortWatch daily port activity, on real recordings of the ArcGIS layers (2026-11-05); no network."""

import json
from datetime import date
from pathlib import Path

import pytest

from openterm.providers.base import ProviderError
from openterm.providers.portwatch import PORTS_DAILY_URL, PORTS_LIST_URL, PortWatchProvider
from openterm.world import ports

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 5)


def feats(name: str) -> list[dict]:
    """The attribute dicts of a recorded answer, through the same check the provider uses."""
    return ports.check_body(json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"])


def day(d: str, calls: int, pid: str = "port1", name: str = "Testport") -> dict:
    return {"date": d, "portid": pid, "portname": name, "country": "Testland", "ISO3": "TST", "portcalls": calls,
            "portcalls_tanker": 1, "portcalls_container": 2, "portcalls_dry_bulk": 3, "import": 100, "export": 50}


# --- query building -----------------------------------------------------------------------------------------------------
def test_words_are_upper_cased_and_sql_wildcards_are_dropped():
    assert ports.words_of("rotterdam") == ["ROTTERDAM"]
    assert ports.words_of("  port   said ") == ["PORT", "SAID"]
    assert ports.words_of("100%_x") == ["100", "X"]  # % and _ would be LIKE wildcards: they become separators
    assert ports.words_of("") == []


def test_too_many_or_too_long_words_are_refused():
    with pytest.raises(ValueError, match="TOO MANY"):
        ports.words_of("a b c d e")
    with pytest.raises(ValueError, match="TOO LONG"):
        ports.words_of("x" * 31)


def test_where_needs_every_word_and_doubles_quotes():
    w = ports.ports_where(["PORT", "SAID"])
    assert w.count(" AND ") == 1 and "UPPER(portname) LIKE '%PORT%'" in w and "UPPER(country) LIKE '%SAID%'" in w
    assert "O''BRIEN" in ports.ports_where(["O'BRIEN"])  # an apostrophe cannot end the string early
    with pytest.raises(ValueError):
        ports.ports_where([])


def test_daily_where_checks_the_ids():
    assert ports.daily_where(["port1", "port2"], date(2026, 9, 26)) == "portid IN ('port1','port2') AND date >= DATE '2026-09-26'"
    for bad in (["port1'; DROP"], [], ["a b"]):
        with pytest.raises(ValueError):
            ports.daily_where(bad, date(2026, 9, 26))


def test_newest_day_and_window_come_from_the_recording():
    newest = ports.newest_day(feats("portwatch_ports_newest"))
    assert newest == date(2026, 10, 30)
    assert ports.top_window_start(newest) == date(2026, 10, 23)  # where is date > 2026-10-23, i.e. 7 days
    with pytest.raises(ValueError):
        ports.newest_day([])


def test_top_ids_keep_the_server_order():
    ids = ports.top_ids(feats("portwatch_ports_top25"))
    assert len(ids) == 25 and ids[:3] == ["port1201", "port1114", "port1188"]  # Singapore, Rotterdam, Shanghai
    with pytest.raises(ValueError):
        ports.top_ids([])


# --- board rows ---------------------------------------------------------------------------------------------------------
def test_busiest_board_matches_the_server_side_sum():
    rows, missing = ports.board(feats("portwatch_ports_daily_top25"), [], TODAY)
    assert len(rows) == 25 and missing == 0
    assert rows[0]["name"] == "Singapore" and rows[0]["country"] == "Singapore"
    assert rows[0]["avg7"] * 7 == pytest.approx(805)  # the recorded outStatistics sum for the same 7 days
    assert rows[0]["imp7"] * 7 == pytest.approx(9678917)
    assert rows[0]["date"] == "2026-10-30" and rows[0]["age_days"] == 6 and not rows[0]["stale"]
    avgs = [r["avg7"] or 0 for r in rows]
    assert avgs == sorted(avgs, reverse=True)
    assert len(rows[0]["series"]) == 28


def test_search_rows_carry_the_port_list_details():
    rows, _ = ports.board([a for a in feats("portwatch_ports_daily_top25") if a["portid"] == "port1114"],
                          feats("portwatch_ports_db_rotterdam"), TODAY)
    assert len(rows) == 1 and rows[0]["id"] == "port1114"
    assert rows[0]["lat"] == pytest.approx(51.92, abs=0.01) and rows[0]["locode"] == "NL RTM"


def test_ports_without_daily_rows_are_counted_not_invented():
    rows, missing = ports.board([a for a in feats("portwatch_ports_daily_top25") if a["portid"] == "port57"],
                                feats("portwatch_ports_db_belgium"), TODAY)
    assert [r["name"] for r in rows] == ["Antwerp"] and missing == 4  # Ghent, Zeebrugge, Bruges, Oostende


def test_change_is_last_7_days_against_the_21_before():
    attrs = [day(f"2026-10-{d:02d}", 10) for d in range(1, 22)] + [day(f"2026-10-{d:02d}", 20) for d in range(22, 29)]
    row = ports.board(attrs, [], date(2026, 10, 30))[0][0]
    assert row["avg7"] == 20 and row["base"] == 10 and row["chg_pct"] == 100 and row["base_days"] == 21


def test_short_history_gives_no_change_and_old_data_is_stale():
    row = ports.board([day(f"2026-09-0{d}", 5) for d in range(1, 8)], [], TODAY)[0][0]
    assert row["base"] is None and row["chg_pct"] is None and row["stale"] and row["age_days"] == 59  # newest day 2026-09-07


def test_missing_numbers_stay_none():
    a = day("2026-10-30", 5)
    a["import"] = None
    row = ports.board([a], [], TODAY)[0][0]
    assert row["imp7"] is None and row["exp7"] == 50


def test_empty_answer_is_an_error_not_an_empty_board():
    with pytest.raises(ValueError):
        ports.board([], [], TODAY)


# --- provider: which calls it makes -------------------------------------------------------------------------------------
def make_provider(monkeypatch, answers_for):
    """A provider with no HTTP client: get_json is replaced by `answers_for(url, params) -> body`; returns (provider, calls)."""
    p = PortWatchProvider.__new__(PortWatchProvider)
    calls: list[tuple[str, dict]] = []

    async def fake_get_json(url, params=None, timeout=None):
        calls.append((url, params))
        return answers_for(url, params, len(calls))

    async def no_sleep(_):
        return None

    monkeypatch.setattr(p, "get_json", fake_get_json)
    monkeypatch.setattr("openterm.providers.portwatch.asyncio.sleep", no_sleep)
    return p, calls


def raw(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


async def test_bare_ports_makes_three_small_calls(monkeypatch):
    def answers(url, params, n):
        assert url == PORTS_DAILY_URL
        if params.get("outStatistics") and "max" in params["outStatistics"]:
            return raw("portwatch_ports_newest")
        if params.get("outStatistics"):
            return raw("portwatch_ports_top25")
        return raw("portwatch_ports_daily_top25")

    p, calls = make_provider(monkeypatch, answers)
    got = await p.ports_activity(TODAY, [])
    assert len(calls) == 3 and len(got["daily"]) == 875 and got["meta"] == []
    top = calls[1][1]
    assert top["where"] == "date > DATE '2026-10-23'" and top["groupByFieldsForStatistics"] == "portid"
    assert top["resultRecordCount"] == 25 and "calls7 DESC" in top["orderByFields"]
    assert calls[2][1]["where"].startswith("portid IN ('port1201','port1114'") and "date >= DATE '2026-09-26'" in calls[2][1]["where"]


async def test_search_asks_the_port_list_first_and_retries_the_flaky_node(monkeypatch):
    def answers(url, params, n):
        if n == 1:
            return {"error": {"message": "Invalid URL"}}  # the known node glitch: retried
        if url == PORTS_LIST_URL:
            return raw("portwatch_ports_db_rotterdam")
        return raw("portwatch_ports_daily_top25")

    p, calls = make_provider(monkeypatch, answers)
    got = await p.ports_activity(TODAY, ["ROTTERDAM"])
    assert [c[0] for c in calls] == [PORTS_LIST_URL, PORTS_LIST_URL, PORTS_DAILY_URL]
    assert "LIKE '%ROTTERDAM%'" in calls[0][1]["where"] and calls[0][1]["resultRecordCount"] == 20
    assert "portid IN ('port1114')" in calls[2][1]["where"] and got["meta"][0]["portname"] == "Rotterdam"


async def test_search_with_no_match_stops_after_one_call(monkeypatch):
    p, calls = make_provider(monkeypatch, lambda url, params, n: {"features": []})
    assert await p.ports_activity(TODAY, ["ZZZZ"]) == {"daily": [], "meta": []}
    assert len(calls) == 1


async def test_invalid_query_parameters_glitch_is_retried(monkeypatch):
    """Seen live: a valid request answered 'Invalid query parameters' once, then worked on the identical retry."""
    glitch = {"error": {"code": 400, "message": "Cannot perform query. Invalid query parameters."}}
    p, calls = make_provider(monkeypatch, lambda url, params, n: glitch if n == 1 else raw("portwatch_ports_db_rotterdam"))
    assert (await p._page({"f": "json"}, PORTS_LIST_URL))[0]["portname"] == "Rotterdam"
    assert len(calls) == 2


async def test_real_error_is_not_retried(monkeypatch):
    p, calls = make_provider(monkeypatch, lambda url, params, n: {"error": {"message": "Invalid token"}})
    with pytest.raises(ProviderError):
        await p.ports_activity(TODAY, ["ROTTERDAM"])
    assert len(calls) == 1


# --- the route, end to end on the fixtures ------------------------------------------------------------------------------
def test_route_bare_returns_the_busiest_ports(client):
    r = client.get("/api/world/ports").json()
    assert "PORTWATCH" in r["source"]
    d = r["data"]
    assert d["mode"] == "top" and len(d["rows"]) == 25 and d["newest"] == "2026-10-30"
    assert d["rows"][0]["name"] == "Singapore" and "SATELLITE AIS" in d["note"] and "NOT MEASURED CARGO" in d["note"]


def test_route_search_by_port_name(client):
    d = client.get("/api/world/ports", params={"q": "rotterdam"}).json()["data"]
    assert d["mode"] == "search" and [r["id"] for r in d["rows"]] == ["port1114"] and d["rows"][0]["lat"] is not None


def test_route_search_reports_ports_with_no_daily_rows(client):
    d = client.get("/api/world/ports", params={"q": "belgium"}).json()["data"]
    assert [r["name"] for r in d["rows"]] == ["Antwerp"] and d["no_daily_rows"] == 4


def test_route_no_match_is_a_not_found_with_advice(client):
    r = client.get("/api/world/ports", params={"q": "zzzz"})
    assert r.status_code == 404 and "NO PORT MATCHES ZZZZ" in r.json()["error"]


def test_route_too_many_words_is_a_bad_request(client):
    r = client.get("/api/world/ports", params={"q": "a b c d e"})
    assert r.status_code == 400 and "TOO MANY WORDS" in r.json()["error"]
