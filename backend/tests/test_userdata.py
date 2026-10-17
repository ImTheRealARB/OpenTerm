import asyncio

from openterm.db import MIGRATIONS, open_db
from openterm.userdata import HISTORY_MAX

STATE = {
    "layout": {"t": "split", "dir": "v", "ratio": 0.5, "a": {"t": "leaf", "id": 1}, "b": {"t": "leaf", "id": 2}},
    "panels": {
        "1": {"id": 1, "views": [{"fn": "GP", "security": {"symbol": "AAPL"}, "args": ["1Y"]}], "pos": 0},
        "2": {"id": 2, "views": [{"fn": "Q", "args": ["AAPL", "MSFT"]}], "pos": 0},
    },
    "focus": 1,
    "maximized": None,
}


def test_migrations_upgrade_an_existing_db(tmp_path):
    async def run():
        path = tmp_path / "old.db"
        db = await open_db(path)
        await db.execute("PRAGMA user_version=2")  # a phase 2/3 database: cache + kv only
        await db.execute("DROP TABLE IF EXISTS layouts")
        await db.execute("DROP TABLE IF EXISTS history")
        await db.commit()
        await db.close()
        db = await open_db(path)
        async with db.execute("PRAGMA user_version") as cur:
            assert (await cur.fetchone())[0] == len(MIGRATIONS)
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            tables = {r[0] for r in await cur.fetchall()}
        await db.close()
        return tables

    assert {"cache", "kv", "layouts", "history"} <= asyncio.run(run())


def test_layout_crud(client):
    assert client.get("/api/layouts").json() == {"layouts": []}
    r = client.put("/api/layouts/my desk", json={"state": STATE})
    assert r.status_code == 400  # spaces are not allowed in names
    r = client.put("/api/layouts/desk-1", json={"state": STATE})
    assert r.status_code == 200 and r.json()["name"] == "DESK-1"

    listed = client.get("/api/layouts").json()["layouts"]
    assert [(x["name"], x["panels"]) for x in listed] == [("DESK-1", 2)]
    got = client.get("/api/layouts/Desk-1").json()
    assert got["name"] == "DESK-1" and got["state"] == STATE

    # Saving under an existing name overwrites it.
    one = {**STATE, "layout": {"t": "leaf", "id": 1}, "panels": {"1": STATE["panels"]["1"]}}
    client.put("/api/layouts/DESK-1", json={"state": one})
    assert client.get("/api/layouts").json()["layouts"][0]["panels"] == 1

    assert client.delete("/api/layouts/desk-1").json() == {"deleted": "DESK-1"}
    assert client.delete("/api/layouts/desk-1").status_code == 404
    assert client.get("/api/layouts/desk-1").status_code == 404


def test_layout_validation(client):
    assert client.put("/api/layouts/X", json={"state": {"layout": 1}}).status_code == 400
    assert client.put("/api/layouts/X", json={"nope": 1}).status_code == 400
    assert client.put("/api/layouts/X", content=b"not json").status_code == 400
    big = {**STATE, "pad": "x" * 70_000}
    assert client.put("/api/layouts/X", json={"state": big}).status_code == 413
    assert client.put("/api/layouts/" + "A" * 33, json={"state": STATE}).status_code == 400


def test_history_round_trip_and_cap(client):
    assert client.get("/api/cmdhistory").json() == {"items": []}
    client.post("/api/cmdhistory", json={"cmds": ["AAPL GP", "AAPL GP", "Q", "  "]})
    assert client.get("/api/cmdhistory").json()["items"] == ["AAPL GP", "Q"]  # consecutive dupes and blanks dropped
    client.post("/api/cmdhistory", json={"cmds": ["Q", "HELP"]})
    assert client.get("/api/cmdhistory").json()["items"] == ["AAPL GP", "Q", "HELP"]
    assert client.get("/api/cmdhistory", params={"limit": 2}).json()["items"] == ["Q", "HELP"]

    client.post("/api/cmdhistory", json={"cmds": [f"C{i}" for i in range(HISTORY_MAX + 20)]})
    items = client.get("/api/cmdhistory", params={"limit": 10_000}).json()["items"]
    assert len(items) == HISTORY_MAX and items[-1] == f"C{HISTORY_MAX + 19}"
    assert client.post("/api/cmdhistory", json={"cmds": "Q"}).status_code == 400


def test_history_survives_restart(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from openterm.config import get_settings

    monkeypatch.setenv("OPENTERM_FIXTURES", "1")
    monkeypatch.setenv("OPENTERM_DB_PATH", str(tmp_path / "persist.db"))
    get_settings.cache_clear()
    from openterm.main import app

    with TestClient(app) as c:
        c.post("/api/cmdhistory", json={"cmds": ["AAPL DES"]})
        c.put("/api/layouts/KEEP", json={"state": STATE})
    with TestClient(app) as c:
        assert c.get("/api/cmdhistory").json()["items"] == ["AAPL DES"]
        assert c.get("/api/layouts/KEEP").json()["state"] == STATE
    get_settings.cache_clear()
