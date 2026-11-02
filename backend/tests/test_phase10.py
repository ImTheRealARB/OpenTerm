"""Phase 10: /api/settings (validation + persistence in kv) and optional static frontend serving."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openterm.db import open_db
from openterm.main import mount_static
from openterm.settings_store import SettingsStore, validate
from openterm.userdata import UserDataError

FULL = {
    "theme": "green",
    "vim": True,
    "numberFormat": {"thousands": ".", "decimal": ","},
    "clocks": ["LOCAL", "UTC", "America/New_York"],
    "chart": {"range": "6M", "type": "LINE"},
    "poll": {"news": 120, "movers": 60, "crypto": 15, "sources": 30},
    "keys": {"closePanel": ["Alt+Q"], "maximize": ["Ctrl+Shift+M", "Alt+M"], "splitVertical": ["Ctrl+\\"]},
}


def test_settings_empty_then_roundtrip(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {"version": 1, "settings": None, "updated_at": None}

    r = client.put("/api/settings", json={"version": 1, "settings": FULL})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["settings"] == FULL and saved["version"] == 1 and saved["updated_at"] > 0

    got = client.get("/api/settings").json()
    assert got["settings"] == FULL
    assert got["updated_at"] == saved["updated_at"]


def test_settings_partial_and_replace(client):
    client.put("/api/settings", json={"settings": {"theme": "light"}})
    assert client.get("/api/settings").json()["settings"] == {"theme": "light"}
    # PUT replaces the whole document (the frontend always sends everything it changed from the defaults).
    client.put("/api/settings", json={"settings": {"vim": True}})
    assert client.get("/api/settings").json()["settings"] == {"vim": True}


def test_settings_mode_roundtrip(client):
    """GUI mode: `mode` is a stored setting ("terminal" or "gui"); a document without it is valid (it means terminal)."""
    for mode in ("gui", "terminal"):
        r = client.put("/api/settings", json={"settings": {"mode": mode}})
        assert r.status_code == 200, r.text
        assert client.get("/api/settings").json()["settings"] == {"mode": mode}


@pytest.mark.parametrize(
    "bad, needle",
    [
        ({"theme": "neon"}, "theme"),
        ({"mode": "tui"}, "mode"),
        ({"vim": "yes"}, "vim"),
        ({"colour": "red"}, "UNKNOWN FIELD"),
        ({"numberFormat": {"thousands": ",", "decimal": ","}}, "MUST DIFFER"),
        ({"numberFormat": {"thousands": "_"}}, "thousands"),
        ({"clocks": []}, "clocks"),
        ({"clocks": ["LOCAL", "UTC", "Asia/Tokyo", "Europe/London"]}, "clocks"),
        ({"clocks": ["Mars/Olympus Mons"]}, "TIME ZONE"),
        ({"chart": {"range": "7Y"}}, "chart.range"),
        ({"chart": {"type": "PIE"}}, "chart.type"),
        ({"poll": {"news": 5}}, "poll.news"),
        ({"poll": {"crypto": 15.5}}, "poll.crypto"),
        ({"poll": {"sources": True}}, "poll.sources"),
        ({"poll": {"quotes": 10}}, "poll KEYS"),
        ({"ai": {"model": "bad model!"}}, "ai.model"),
        ({"ai": {"provider": "skynet"}}, "ai.provider"),
        ({"ai": {"temperature": 1}}, "ai KEYS"),
        ({"ai": "gpt"}, "ai MUST"),
        ({"keys": {"closePanel": "Alt+Q"}}, "keys.closePanel"),
        ({"keys": {"close panel": ["Alt+Q"]}}, "ACTION NAME"),
        ({"keys": {"closePanel": ["Alt Q"]}}, "BAD CHORD"),
        ({"keys": {"closePanel": ["A", "B", "C", "D", "E"]}}, "keys.closePanel"),
    ],
)
def test_settings_validation_rejects(client, bad, needle):
    r = client.put("/api/settings", json={"settings": bad})
    assert r.status_code == 400, r.text
    assert r.json()["kind"] == "bad_request"
    assert needle in r.json()["error"]
    assert client.get("/api/settings").json()["settings"] is None  # nothing stored


def test_settings_body_and_version_errors(client):
    assert client.put("/api/settings", content=b"not json").status_code == 400
    assert client.put("/api/settings", json=[1, 2]).status_code == 400
    assert "BODY NEEDS settings" in client.put("/api/settings", json={"theme": "green"}).json()["error"]
    r = client.put("/api/settings", json={"version": 2, "settings": {}})
    assert r.status_code == 400 and "NEWER" in r.json()["error"]
    assert client.put("/api/settings", json={"version": "1", "settings": {}}).status_code == 400


def test_settings_action_limit_and_dedupe():
    with pytest.raises(UserDataError) as e:
        validate({"keys": {f"action{i}": [f"Ctrl+Shift+F{i % 12 + 1}"] * 4 for i in range(64)} | {"x" * 41: []}})
    assert e.value.kind == "bad_request"
    # Duplicate chords collapse, order kept.
    assert validate({"keys": {"maximize": ["Alt+M", "Alt+M", "Ctrl++"]}}) == {"keys": {"maximize": ["Alt+M", "Ctrl++"]}}


def test_settings_persist_across_reopen(tmp_path):
    async def run():
        path = tmp_path / "s.db"
        db = await open_db(path)
        await SettingsStore(db).put({"theme": "white", "poll": {"news": 300}})
        await db.close()
        db = await open_db(path)
        got = await SettingsStore(db).get()
        async with db.execute("SELECT key FROM kv") as cur:
            keys = [r[0] for r in await cur.fetchall()]
        await db.close()
        return got, keys

    got, keys = asyncio.run(run())
    assert got["settings"] == {"theme": "white", "poll": {"news": 300}}
    assert keys == ["settings"]


def test_static_mount_serves_index_and_keeps_api(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8", newline="\n")
    (dist / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8", newline="\n")
    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    assert mount_static(app, "") is False
    assert mount_static(app, str(tmp_path / "missing")) is False
    assert mount_static(app, str(dist)) is True
    assert mount_static(app, str(dist)) is True  # idempotent
    assert sum(getattr(r, "name", None) == "frontend" for r in app.router.routes) == 1
    with TestClient(app) as c:
        assert c.get("/api/ping").json() == {"ok": True}
        assert "<title>t</title>" in c.get("/").text
        assert c.get("/assets/a.js").status_code == 200
        assert c.get("/nope.txt").status_code == 404


def test_settings_ai_roundtrip(client):
    ai = {"model": "deepseek/deepseek-v4-pro", "visionModel": "deepseek/deepseek-v4.1-flash", "provider": "openrouter"}
    r = client.put("/api/settings", json={"settings": {"ai": ai}})
    assert r.status_code == 200 and r.json()["settings"]["ai"] == ai
    assert client.get("/api/settings").json()["settings"]["ai"] == ai
