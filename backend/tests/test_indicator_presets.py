"""Indicator presets: GET/PUT/DELETE /api/indicator-presets[/{name}] backed by kv `ind_presets`."""

import pytest

from openterm.indicator_presets import MAX_FORMULA, MAX_ITEMS, MAX_PRESETS, validate_items
from openterm.userdata import UserDataError

ITEMS = [
    {"id": "RSI", "params": [14], "label": "RSI 14"},
    {"formula": "EMA(close,12)-EMA(close,26)", "params": [], "label": "MY MACD"},
]


def test_empty_list(client):
    r = client.get("/api/indicator-presets")
    assert r.status_code == 200
    assert r.json() == {"presets": []}


def test_round_trip_list_replace_delete(client):
    r = client.put("/api/indicator-presets/Trend%20set", json={"items": ITEMS})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["name"] == "Trend set" and saved["items"] == ITEMS and saved["updated_at"] > 0
    assert client.get("/api/indicator-presets/Trend%20set").json()["items"] == ITEMS
    client.put("/api/indicator-presets/Another", json={"items": [{"id": "ATR"}]})
    names = [p["name"] for p in client.get("/api/indicator-presets").json()["presets"]]
    assert names == ["Another", "Trend set"]
    client.put("/api/indicator-presets/Trend%20set", json={"items": []})
    assert client.get("/api/indicator-presets/Trend%20set").json()["items"] == []
    assert client.delete("/api/indicator-presets/Trend%20set").json() == {"deleted": "Trend set"}
    assert client.get("/api/indicator-presets/Trend%20set").status_code == 404
    assert client.delete("/api/indicator-presets/Trend%20set").status_code == 404


def test_item_defaults_are_filled(client):
    r = client.put("/api/indicator-presets/P", json={"items": [{"id": "SMA"}]})
    assert r.json()["items"] == [{"id": "SMA", "params": [], "label": ""}]


@pytest.mark.parametrize("bad", [
    {"id": "RSI", "formula": "close"},
    {},
    {"id": "rsi"},
    {"id": "RSI;DROP"},
    {"id": "RSI", "params": ["14"]},
    {"id": "RSI", "params": [1] * 13},
    {"id": "RSI", "label": "x" * 41},
    {"id": "RSI", "extra": 1},
    {"formula": ""},
    {"formula": "x" * (MAX_FORMULA + 1)},
    {"formula": 5},
])
def test_bad_items_refused(client, bad):
    r = client.put("/api/indicator-presets/P", json={"items": [bad]})
    assert r.status_code == 400, r.text
    assert "PRESETS" in r.json()["error"]


def test_limits(client):
    r = client.put("/api/indicator-presets/P", json={"items": [{"id": "SMA"}] * (MAX_ITEMS + 1)})
    assert r.status_code == 413
    assert client.put("/api/indicator-presets/P", json={"items": [{"id": "SMA"}] * MAX_ITEMS}).status_code == 200
    assert client.put("/api/indicator-presets/" + "n" * 41, json={"items": []}).status_code == 400
    assert client.put("/api/indicator-presets/P", json={}).status_code == 400
    assert client.put("/api/indicator-presets/P", json={"items": "x"}).status_code == 400


def test_preset_count_cap(client):
    for i in range(MAX_PRESETS):
        assert client.put(f"/api/indicator-presets/p{i}", json={"items": []}).status_code == 200
    assert client.put("/api/indicator-presets/overflow", json={"items": []}).status_code == 413
    assert client.put("/api/indicator-presets/p0", json={"items": [{"id": "SMA"}]}).status_code == 200


def test_validate_items_unit():
    assert validate_items([]) == []
    with pytest.raises(UserDataError):
        validate_items("nope")
    with pytest.raises(UserDataError):
        validate_items([{"id": "RSI", "params": [float("nan")]}])
