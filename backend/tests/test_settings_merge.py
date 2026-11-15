"""Settings sync is a per-field merge (settings_store.merge / SettingsStore.put with `field_times`), not whole-document last-write-wins.

The rules under test:
- each top-level field has its own change time; on a PUT the later change wins per field, the stored copy keeps a tie;
- a field absent from `settings` but present in `field_times` is a reset to default (a tombstone) and merges like any value;
- a time of 0 means "never set" and never beats anything;
- an old stored document (no `field_times`) counts every field as changed at its `updated_at`;
- an old client (PUT without `field_times`) still replaces the whole document.
"""

import asyncio
import time

import orjson
import pytest

from openterm.db import open_db
from openterm.settings_store import (
    FIELDS,
    KEY,
    SettingsStore,
    effective_times,
    merge,
    validate_times,
)
from openterm.userdata import UserDataError

T0 = 1_700_000_000.0  # a fixed "past" so the tests never depend on the clock (or on its coarse resolution on Windows)


def put(client, settings, times, **extra):
    return client.put("/api/settings", json={"version": 1, "settings": settings, "field_times": times, **extra})


# --- pure merge ---------------------------------------------------------------------------------


def test_merge_later_change_wins_per_field():
    cur = ({"theme": "green", "vim": True}, {"theme": 10.0, "vim": 20.0})
    new = ({"theme": "white", "vim": False}, {"theme": 15.0, "vim": 5.0})
    settings, times = merge(*cur, *new)
    assert settings == {"theme": "white", "vim": True}  # theme: incoming is newer; vim: stored is newer
    assert times == {"theme": 15.0, "vim": 20.0}


def test_merge_tie_keeps_stored_and_zero_never_wins():
    settings, times = merge({"theme": "green"}, {"theme": 10.0}, {"theme": "white", "vim": True}, {"theme": 10.0, "vim": 0.0})
    assert settings == {"theme": "green"}  # tie: stored copy stays; vim has time 0 = never set, so it is not stored
    assert times == {"theme": 10.0}


def test_merge_tombstone_resets_a_field_only_when_newer():
    # incoming has no `theme` value but a newer time: the user reset it to the default
    settings, _ = merge({"theme": "green", "vim": True}, {"theme": 10.0, "vim": 10.0}, {}, {"theme": 11.0})
    assert settings == {"vim": True}
    # an older tombstone loses to a newer stored value
    settings, _ = merge({"theme": "green"}, {"theme": 10.0}, {}, {"theme": 9.0})
    assert settings == {"theme": "green"}


def test_merge_field_with_no_incoming_time_is_untouched():
    settings, times = merge({"theme": "green", "vim": True}, {"theme": 10.0, "vim": 10.0}, {"vim": False}, {"vim": 12.0})
    assert settings == {"theme": "green", "vim": False}
    assert times == {"theme": 10.0, "vim": 12.0}


def test_effective_times_legacy_and_new():
    legacy = {"settings": {"theme": "green"}, "updated_at": 50.0}  # saved before field_times existed
    assert effective_times(legacy) == {f: 50.0 for f in FIELDS}  # every field, even an absent one, changed when the doc was saved
    assert effective_times({"updated_at": None}) == {f: 0.0 for f in FIELDS}
    new = {"settings": {}, "updated_at": 99.0, "field_times": {"theme": 7.0}}
    times = effective_times(new)
    assert times["theme"] == 7.0 and times["vim"] == 0.0  # a new-format doc does NOT fall back to updated_at


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("times", "settings", "needle"),
    [
        ([1], {}, "MUST BE AN OBJECT"),
        ({"bogus": 1}, {}, "UNKNOWN FIELD"),
        ({"theme": "now"}, {}, "EPOCH SECONDS"),
        ({"theme": True}, {}, "EPOCH SECONDS"),
        ({"theme": -1}, {}, "EPOCH SECONDS"),
        ({"theme": float("inf")}, {}, "EPOCH SECONDS"),
        ({"theme": time.time() + 10 * 86_400}, {}, "IN THE FUTURE"),
        ({"vim": 5}, {"theme": "green"}, "NO TIME FOR 'theme'"),
    ],
)
def test_validate_times_rejects(times, settings, needle):
    with pytest.raises(UserDataError) as e:
        validate_times(times, settings, time.time())
    assert e.value.kind == "bad_request" and needle in str(e.value)


def test_validate_times_accepts_zero_tombstones_and_ints():
    assert validate_times({"theme": 0, "vim": 12}, {"theme": "green"}, time.time()) == {"theme": 0.0, "vim": 12.0}


# --- the route ----------------------------------------------------------------------------------


def test_two_clients_editing_different_fields_both_survive(client):
    # Browser A and browser B both last synced an empty document; each edits one field and PUTs.
    a = put(client, {"theme": "green"}, {"theme": T0 + 1})
    b = put(client, {"vim": True}, {"vim": T0 + 2})  # B never saw A's edit, so its body has no theme
    assert a.status_code == 200 and b.status_code == 200
    merged = b.json()
    assert merged["settings"] == {"theme": "green", "vim": True}  # B's response already carries A's field
    assert merged["field_times"]["theme"] == T0 + 1 and merged["field_times"]["vim"] == T0 + 2
    got = client.get("/api/settings").json()
    assert got["settings"] == {"theme": "green", "vim": True}
    assert got["updated_at"] > 0 and got["version"] == 1  # the old response keys are still there


def test_same_field_later_edit_wins_even_when_it_arrives_first(client):
    put(client, {"theme": "white"}, {"theme": T0 + 20})
    r = put(client, {"theme": "green"}, {"theme": T0 + 10})  # an older edit arriving late (offline device)
    assert r.json()["settings"] == {"theme": "white"}  # not stored, and the response tells the client so
    assert client.get("/api/settings").json()["settings"] == {"theme": "white"}


def test_reset_on_one_device_wins_over_an_older_copy_on_another(client):
    put(client, {"theme": "green", "vim": True}, {"theme": T0 + 1, "vim": T0 + 1})
    put(client, {"vim": True}, {"theme": T0 + 5, "vim": T0 + 1})  # theme reset to default at T0 + 5
    assert client.get("/api/settings").json()["settings"] == {"vim": True}
    put(client, {"theme": "green"}, {"theme": T0 + 3})  # a stale device re-sends its older theme
    assert client.get("/api/settings").json()["settings"] == {"vim": True}


def test_never_set_field_does_not_beat_a_remote_edit(client):
    put(client, {"theme": "green"}, {"theme": T0 + 1})
    # This client holds theme "white" but never set it itself (time 0), e.g. a seed or a default.
    r = put(client, {"theme": "white", "vim": True}, {"theme": 0, "vim": T0 + 2})
    assert r.json()["settings"] == {"theme": "green", "vim": True}


def test_old_client_without_field_times_replaces_the_whole_document(client):
    put(client, {"theme": "green", "vim": True}, {"theme": T0 + 1, "vim": T0 + 1})
    r = client.put("/api/settings", json={"settings": {"vim": False}})  # exactly what the old frontend sent
    assert r.status_code == 200
    doc = r.json()
    assert doc["settings"] == {"vim": False}  # theme is gone, as it was before per-field merge
    assert doc["updated_at"] > 0 and set(doc["field_times"]) == set(FIELDS)
    assert client.get("/api/settings").json()["settings"] == {"vim": False}


def test_put_validation_errors_store_nothing(client):
    for body, needle in [
        ({"settings": {"theme": "green"}, "field_times": None}, "MUST BE AN OBJECT"),
        ({"settings": {"theme": "green"}, "field_times": {}}, "NO TIME FOR 'theme'"),
        ({"settings": {"theme": "green"}, "field_times": {"theme": 1, "nope": 2}}, "UNKNOWN FIELD"),
        ({"settings": {"theme": "pink"}, "field_times": {"theme": 1}}, "theme MUST BE ONE OF"),
    ]:
        r = client.put("/api/settings", json=body)
        assert r.status_code == 400 and needle in r.json()["error"], (body, r.text)
    assert client.get("/api/settings").json()["settings"] is None


def test_get_of_an_empty_store_keeps_its_old_shape_plus_empty_times(client):
    assert client.get("/api/settings").json() == {"version": 1, "settings": None, "updated_at": None, "field_times": {}}


def test_pin_preference_follows_the_merged_document(client):
    """The router's source pins come from the stored (merged) settings, not from the request body alone."""
    put(client, {"sources": {"history": "nasdaq"}}, {"sources": T0 + 1})
    put(client, {"theme": "green"}, {"theme": T0 + 2})  # a body with no `sources` must not drop the pin
    from openterm.main import app

    assert app.state.service.router.prefs == {"history": "nasdaq"}


# --- the store itself (real database, real concurrency) -----------------------------------------


def test_concurrent_puts_of_different_fields_both_land(tmp_path):
    async def run():
        db = await open_db(tmp_path / "s.db")
        try:
            # 12 devices, each editing a different field at the same moment. Without the per-connection lock the
            # read-merge-write of one would overwrite another's.
            bodies = [({f: v}, {f: T0 + i}) for i, (f, v) in enumerate(
                [("theme", "green"), ("vim", True), ("font", "Consolas"), ("tape", True), ("mode", "gui"), ("startup", "layout"),
                 ("clocks", ["UTC"]), ("chart", {"range": "6M"}), ("poll", {"news": 120}), ("tapeSymbols", ["^GSPC"]),
                 ("numberFormat", {"thousands": "'"}), ("sources", {})], start=1)]
            await asyncio.gather(*(SettingsStore(db).put(s, 1, t) for s, t in bodies))
            return await SettingsStore(db).get()
        finally:
            await db.close()

    got = asyncio.run(run())
    assert set(got["settings"]) == {"theme", "vim", "font", "tape", "mode", "startup", "clocks", "chart", "poll", "tapeSymbols", "numberFormat", "sources"}


def test_legacy_doc_on_disk_is_upgraded_by_the_first_merge(tmp_path):
    async def run():
        db = await open_db(tmp_path / "s.db")
        try:
            legacy = {"version": 1, "settings": {"theme": "green", "poll": {"news": 300}}, "updated_at": T0 + 100}
            await db.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (KEY, orjson.dumps(legacy)))
            await db.commit()
            before = await SettingsStore(db).get()
            # vim at T0 + 200 is newer than the legacy doc; theme at T0 + 10 is older than it
            after = await SettingsStore(db).put({"vim": True, "theme": "white"}, 1, {"vim": T0 + 200, "theme": T0 + 10})
            return before, after, await SettingsStore(db).get()
        finally:
            await db.close()

    before, after, got = asyncio.run(run())
    assert before["settings"] == {"theme": "green", "poll": {"news": 300}} and before["updated_at"] == T0 + 100
    assert after["settings"] == {"theme": "green", "poll": {"news": 300}, "vim": True}
    # Times were materialised: the untouched legacy fields keep the old doc's time, so they stay protected from stale edits.
    assert after["field_times"]["vim"] == T0 + 200 and after["field_times"]["theme"] == T0 + 100 and after["field_times"]["poll"] == T0 + 100
    assert got["settings"] == after["settings"]
