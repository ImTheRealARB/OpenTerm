"""SHIP: IMF PortWatch chokepoint board, on a real recording of the ArcGIS layer (2026-11-05); no network."""

import json
from datetime import date
from pathlib import Path

import pytest

from openterm.providers.base import ProviderError
from openterm.providers.portwatch import PortWatchProvider
from openterm.world import shipping

FIX = Path(__file__).parent / "fixtures"


def body() -> dict:
    return json.loads((FIX / "portwatch_chokepoints_daily.json").read_text(encoding="utf-8"))["body"]


def day(d: str, total: int, pid: str = "chokepoint1", name: str = "Suez Canal") -> dict:
    return {"date": d, "portid": pid, "portname": name, "n_total": total, "n_tanker": 1, "n_container": 2, "n_dry_bulk": 3, "capacity": 100}


# --- pure parsing -------------------------------------------------------------------------------------------------------
def test_recording_has_28_chokepoints_with_names():
    rows = shipping.board(shipping.check_body(body()), date(2026, 11, 5))
    assert len(rows) == 28
    assert {r["name"] for r in rows} >= {"Suez Canal", "Panama Canal", "Strait of Hormuz", "Cape of Good Hope"}
    suez = next(r for r in rows if r["id"] == "chokepoint1")
    assert suez["date"] == "2026-10-25"  # the newest recorded day
    assert suez["age_days"] == 11  # PortWatch's normal lag
    assert not suez["stale"]
    assert suez["avg7"] and suez["base"] and suez["chg_pct"] is not None


def test_board_is_sorted_busiest_first():
    rows = shipping.board(shipping.check_body(body()), date(2026, 11, 5))
    avgs = [r["avg7"] or 0 for r in rows]
    assert avgs == sorted(avgs, reverse=True)


def test_change_is_last_7_days_against_the_21_before():
    # 21 days at 10 ships, then 7 days at 20: the average doubled
    attrs = [day(f"2026-10-{d:02d}", 10) for d in range(1, 22)] + [day(f"2026-10-{d:02d}", 20) for d in range(22, 29)]
    row = shipping.board(attrs, date(2026, 10, 30))[0]
    assert row["avg7"] == 20 and row["base"] == 10 and row["chg_pct"] == 100
    assert row["base_days"] == 21


def test_short_history_gives_no_change_instead_of_a_guess():
    row = shipping.board([day(f"2026-10-0{d}", 5) for d in range(1, 8)], date(2026, 10, 30))[0]
    assert row["avg7"] == 5 and row["base"] is None and row["chg_pct"] is None


def test_old_data_is_marked_stale():
    row = shipping.board([day("2026-09-01", 5)], date(2026, 11, 5))[0]
    assert row["stale"] and row["age_days"] == 65


def test_error_body_is_classified_flaky_or_real():
    with pytest.raises(shipping.PortWatchError) as flaky:
        shipping.check_body({"error": {"code": 400, "message": "Invalid URL"}})
    assert flaky.value.flaky
    with pytest.raises(shipping.PortWatchError) as real:
        shipping.check_body({"error": {"code": 498, "message": "Invalid token"}})
    assert not real.value.flaky
    with pytest.raises(shipping.PortWatchError, match="NO FEATURES"):
        shipping.check_body({"fields": []})


def test_empty_answer_is_an_error_not_an_empty_board():
    with pytest.raises(ValueError):
        shipping.board([], date(2026, 11, 5))


# --- provider retry -----------------------------------------------------------------------------------------------------
async def test_provider_retries_the_flaky_node_then_succeeds(monkeypatch):
    p = PortWatchProvider.__new__(PortWatchProvider)  # no HTTP client needed: get_json is replaced
    answers = [{"error": {"message": "Invalid URL"}}, {"error": {"message": "Object reference not set to an instance of an object."}}, body()]
    calls = []

    async def fake_get_json(url, params=None, timeout=None):
        calls.append(params)
        return answers[len(calls) - 1]

    async def no_sleep(_):
        return None

    monkeypatch.setattr(p, "get_json", fake_get_json)
    monkeypatch.setattr("openterm.providers.portwatch.asyncio.sleep", no_sleep)
    rows = await p.chokepoints(date(2026, 11, 5))
    assert len(calls) == 3 and len(rows) == 868


async def test_provider_gives_up_after_the_attempt_limit(monkeypatch):
    p = PortWatchProvider.__new__(PortWatchProvider)

    async def always_flaky(url, params=None, timeout=None):
        return {"error": {"message": "Invalid URL"}}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(p, "get_json", always_flaky)
    monkeypatch.setattr("openterm.providers.portwatch.asyncio.sleep", no_sleep)
    with pytest.raises(ProviderError, match="STILL FAILING"):
        await p.chokepoints(date(2026, 11, 5))


async def test_provider_does_not_retry_a_real_error(monkeypatch):
    p = PortWatchProvider.__new__(PortWatchProvider)
    n = 0

    async def real_error(url, params=None, timeout=None):
        nonlocal n
        n += 1
        return {"error": {"message": "Invalid token"}}

    monkeypatch.setattr(p, "get_json", real_error)
    with pytest.raises(ProviderError):
        await p.chokepoints(date(2026, 11, 5))
    assert n == 1


# --- the route, end to end on the fixture -------------------------------------------------------------------------------
def test_ship_route_returns_the_board_with_source_and_note(client):
    r = client.get("/api/world/ship").json()
    assert "PORTWATCH" in r["source"]
    d = r["data"]
    assert len(d["rows"]) == 28 and d["newest"] == "2026-10-25"
    assert "SATELLITE AIS" in d["note"]
