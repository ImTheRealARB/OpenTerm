"""Phase 19 step 2: GP drawings are stored per symbol in kv (GET/PUT /api/drawings/{symbol})."""

import pytest

from openterm.drawings import MAX_DRAWINGS, validate
from openterm.userdata import UserDataError

TREND = {"id": "d1", "kind": "TREND", "pts": [{"t": 1_700_000_000, "p": 100.5}, {"t": 1_700_864_000, "p": 110.25}]}
HLINE = {"id": "d2", "kind": "HLINE", "pts": [{"t": 1_700_000_000, "p": 105}]}
FIB = {"id": "d3", "kind": "FIB", "pts": [{"t": 1_700_000_000, "p": 90}, {"t": 1_701_000_000, "p": 120}]}


def test_empty_symbol_has_no_drawings(client):
    r = client.get("/api/drawings/AAPL")
    assert r.status_code == 200
    assert r.json() == {"symbol": "AAPL", "drawings": [], "updated_at": None}


def test_round_trip_and_replace(client):
    r = client.put("/api/drawings/aapl", json={"drawings": [TREND, HLINE, FIB]})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["symbol"] == "AAPL" and saved["updated_at"] > 0
    got = client.get("/api/drawings/AAPL").json()
    assert got["drawings"] == [TREND, HLINE, FIB]
    client.put("/api/drawings/AAPL", json={"drawings": [HLINE]})
    assert client.get("/api/drawings/AAPL").json()["drawings"] == [HLINE]
    assert client.get("/api/drawings/MSFT").json()["drawings"] == []
    client.put("/api/drawings/AAPL", json={"drawings": []})
    assert client.get("/api/drawings/AAPL").json()["drawings"] == []


@pytest.mark.parametrize("bad", [
    {"id": "x", "kind": "RAY", "pts": [{"t": 1, "p": 1}]},
    {"id": "x", "kind": "TREND", "pts": [{"t": 1, "p": 1}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": 1, "p": 1}, {"t": 2, "p": 2}]},
    {"id": "", "kind": "HLINE", "pts": [{"t": 1, "p": 1}]},
    {"id": "x" * 40, "kind": "HLINE", "pts": [{"t": 1, "p": 1}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": "1", "p": 1}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": 1, "p": float("nan")}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": 1, "p": 1, "extra": 2}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": 1}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": -5, "p": 1}]},
    {"id": "x", "kind": "HLINE", "pts": [{"t": 1, "p": 1}], "color": "red"},
    "nope",
])
def test_invalid_drawing_is_refused(bad):
    with pytest.raises(UserDataError):
        validate([bad])


def test_limits_and_duplicates():
    one = {"id": "a", "kind": "HLINE", "pts": [{"t": 1, "p": 1}]}
    with pytest.raises(UserDataError):
        validate([one, dict(one)])
    many = [{"id": f"i{i}", "kind": "HLINE", "pts": [{"t": 1, "p": 1}]} for i in range(MAX_DRAWINGS + 1)]
    with pytest.raises(UserDataError):
        validate(many)
    with pytest.raises(UserDataError):
        validate({"not": "a list"})


def test_routes_refuse_bad_input(client):
    assert client.put("/api/drawings/AAPL", json={"drawings": [{"id": "x", "kind": "RAY", "pts": []}]}).status_code == 400
    assert client.put("/api/drawings/AAPL", json={"nodrawings": []}).status_code == 400
    assert client.put("/api/drawings/AAPL", content=b"not json").status_code == 400
    assert client.get("/api/drawings/BAD%20SYM!").status_code in (400, 404, 422)
