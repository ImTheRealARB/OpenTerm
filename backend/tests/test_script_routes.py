"""OpenTerm Script storage routes (Phase 25): save, list, read, delete, the 20 starter examples and the size cap."""

from __future__ import annotations

from openterm import script_routes

SRC = '// A tiny one.\nindicator("Tiny", overlay=true)\nplot(close, "Close")\n'


def test_empty_list_then_save_read_list_delete(client):
    assert client.get("/api/scripts").json() == {"scripts": []}
    r = client.put("/api/scripts/my-rsi", json={"source": SRC})
    assert r.status_code == 200
    body = r.json()
    # The name is stored in capitals (like layouts), and the title comes from the indicator(...) line.
    assert body["name"] == "MY-RSI" and body["title"] == "Tiny"
    got = client.get("/api/scripts/MY-RSI").json()
    assert got["source"] == SRC and got["title"] == "Tiny" and got["created_at"] <= got["updated_at"]
    listed = client.get("/api/scripts").json()["scripts"]
    assert [(s["name"], s["title"]) for s in listed] == [("MY-RSI", "Tiny")]
    assert client.delete("/api/scripts/my-rsi").json() == {"deleted": "MY-RSI"}
    assert client.get("/api/scripts/MY-RSI").status_code == 404
    assert client.delete("/api/scripts/MY-RSI").status_code == 404


def test_saving_again_replaces_the_text_and_keeps_created_at(client):
    first = client.put("/api/scripts/A", json={"source": SRC}).json()
    created = client.get("/api/scripts/A").json()["created_at"]
    client.put("/api/scripts/A", json={"source": SRC.replace("Tiny", "Bigger")})
    got = client.get("/api/scripts/A").json()
    assert got["title"] == "Bigger" and got["created_at"] == created and got["updated_at"] >= first["updated_at"]
    assert len(client.get("/api/scripts").json()["scripts"]) == 1


def test_title_is_empty_when_there_is_no_indicator_line(client):
    # A script that does not compile yet still saves; it simply has no title in the list.
    client.put("/api/scripts/DRAFT", json={"source": "plot(close)\n"})
    assert client.get("/api/scripts").json()["scripts"][0]["title"] == ""


def test_title_reads_single_quotes():
    assert script_routes.title_of("indicator('Single quoted', overlay=false)") == "Single quoted"


def test_bad_names_are_refused(client):
    for bad in ("a%20b!", "-x", "x" * 33, "a$b"):
        r = client.put(f"/api/scripts/{bad}", json={"source": SRC})
        assert r.status_code == 400, bad
        assert "SCRIPT NAME" in r.json()["error"]
    assert client.get("/api/scripts/-x").status_code == 400


def test_source_is_required_and_capped(client):
    assert client.put("/api/scripts/A", json={}).status_code == 400
    assert client.put("/api/scripts/A", json={"source": "   "}).status_code == 400
    assert client.put("/api/scripts/A", json={"source": 5}).status_code == 400
    ok = client.put("/api/scripts/A", json={"source": "x" * script_routes.MAX_SOURCE})
    assert ok.status_code == 200
    too_long = client.put("/api/scripts/A", json={"source": "x" * (script_routes.MAX_SOURCE + 1)})
    assert too_long.status_code == 413 and "20,000" in too_long.json()["error"]


def test_put_needs_a_json_content_type(client):
    # The origin guard's second wall: a form-style body is refused before it is read.
    r = client.put("/api/scripts/A", content='{"source": "x"}', headers={"content-type": "text/plain"})
    assert r.status_code == 400


def test_examples_list_is_the_twenty_starters(client):
    r = client.get("/api/scripts/examples")
    assert r.status_code == 200
    ex = r.json()["examples"]
    assert len(ex) == 20
    names = [e["name"] for e in ex]
    assert names == sorted(names) and len(set(names)) == 20
    for e in ex:
        # Every example starts with a one-sentence comment, then indicator(...), and fits the source cap.
        assert e["about"].endswith(".") and e["title"], e["name"]
        assert e["source"].lstrip().startswith("//") and "indicator(" in e["source"], e["name"]
        assert len(e["source"]) <= script_routes.MAX_SOURCE, e["name"]
        assert script_routes.title_of(e["source"]) == e["title"]


def test_examples_route_is_not_taken_as_a_script_name(client):
    # `examples` must reach the examples route, not GET /api/scripts/{name} (which would say NO SCRIPT EXAMPLES).
    assert "examples" in client.get("/api/scripts/examples").json()


def test_every_example_has_a_valid_script_name(client):
    for e in client.get("/api/scripts/examples").json()["examples"]:
        assert client.put(f"/api/scripts/{e['name']}", json={"source": e["source"]}).status_code == 200


def test_scripts_router_uses_the_orjson_route_class():
    from openterm.responses import OrjsonRoute

    assert script_routes.router.route_class is OrjsonRoute


def test_ts_name_rule_mirrors_the_stored_name_rule():
    """`frontend/src/functions/scriptPanelArgs.ts` keeps a copy of STORED_NAME_RE (the panel checks a name before it asks the
    server). Both must change together, so the pattern text is compared here."""
    import re
    from pathlib import Path

    from openterm.idents import STORED_NAME_RE

    ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "functions" / "scriptPanelArgs.ts").read_text(encoding="utf-8")
    m = re.search(r"export const NAME_RE = /(.+)/;", ts)
    assert m, "NAME_RE not found in scriptPanelArgs.ts"
    # The TS regex ends in `$`; Python's ends in `\Z` (a `$` there would let a trailing newline through).
    assert m.group(1).removesuffix("$") == STORED_NAME_RE.pattern.removesuffix(r"\Z")


# --- live script alerts (ALRT AAPL SCRIPT=NAME [COND="..."]) ------------------------------------------------------------


def _save(client, name="RSI-CROSS"):
    assert client.put(f"/api/scripts/{name}", json={"source": SRC}).status_code == 200


def test_alerts_empty_then_add_list_delete(client):
    _save(client)
    assert client.get("/api/scripts/alerts").json() == {"alerts": []}
    r = client.post("/api/scripts/alerts", json={"symbol": "aapl", "script": "rsi-cross", "cond": "RSI down"})
    assert r.status_code == 200
    a = r.json()
    # symbol and script are stored in capitals; the condition title keeps its case (it is matched against alertcondition titles)
    assert (a["id"], a["symbol"], a["script"], a["cond"]) == (1, "AAPL", "RSI-CROSS", "RSI down") and a["created_at"] > 0
    b = client.post("/api/scripts/alerts", json={"symbol": "AAPL", "script": "RSI-CROSS"}).json()
    assert b["id"] == 2 and b["cond"] is None
    assert [x["id"] for x in client.get("/api/scripts/alerts").json()["alerts"]] == [1, 2]
    assert client.delete("/api/scripts/alerts/1").json() == {"deleted": 1}
    assert [x["id"] for x in client.get("/api/scripts/alerts").json()["alerts"]] == [2]
    # ids are never reused after a delete
    assert client.post("/api/scripts/alerts", json={"symbol": "MSFT", "script": "RSI-CROSS"}).json()["id"] == 3
    assert client.delete("/api/scripts/alerts/1").status_code == 404


def test_alerts_route_is_not_taken_as_a_script_name(client):
    # GET /api/scripts/alerts must be the list, not "script ALERTS not found"; and a script cannot take that name.
    assert client.get("/api/scripts/alerts").status_code == 200
    r = client.put("/api/scripts/alerts", json={"source": SRC})
    assert r.status_code == 400 and "ALERTS" in r.json()["error"]
    assert client.put("/api/scripts/examples", json={"source": SRC}).status_code == 400


def test_alert_needs_an_existing_script_and_valid_fields(client):
    r = client.post("/api/scripts/alerts", json={"symbol": "AAPL", "script": "NOPE"})
    assert r.status_code == 404 and "NO SCRIPT NOPE" in r.json()["error"]
    _save(client)
    for body in (
        {"script": "RSI-CROSS"},
        {"symbol": "a b", "script": "RSI-CROSS"},
        {"symbol": "AAPL"},
        {"symbol": "AAPL", "script": "-bad"},
        {"symbol": "AAPL", "script": "RSI-CROSS", "cond": ""},
        {"symbol": "AAPL", "script": "RSI-CROSS", "cond": "x" * (script_routes.MAX_COND + 1)},
        {"symbol": "AAPL", "script": "RSI-CROSS", "cond": "two\nlines"},
        {"symbol": "AAPL", "script": "RSI-CROSS", "cond": 5},
    ):
        assert client.post("/api/scripts/alerts", json=body).status_code == 400, body
    assert client.get("/api/scripts/alerts").json() == {"alerts": []}


def test_alert_duplicates_and_the_cap_are_refused(client):
    _save(client)
    body = {"symbol": "AAPL", "script": "RSI-CROSS", "cond": "RSI down"}
    assert client.post("/api/scripts/alerts", json=body).status_code == 200
    dup = client.post("/api/scripts/alerts", json=body)
    assert dup.status_code == 400 and "ALREADY" in dup.json()["error"]
    # same script on the same symbol without a condition is a different alert
    assert client.post("/api/scripts/alerts", json={**body, "cond": None}).status_code == 200
    for i in range(script_routes.MAX_ALERTS - 2):
        assert client.post("/api/scripts/alerts", json={"symbol": f"SYN{i:04d}", "script": "RSI-CROSS"}).status_code == 200
    full = client.post("/api/scripts/alerts", json={"symbol": "ZZZ", "script": "RSI-CROSS"})
    assert full.status_code == 413 and str(script_routes.MAX_ALERTS) in full.json()["error"]


def test_alert_post_needs_a_json_content_type(client):
    _save(client)
    r = client.post("/api/scripts/alerts", content='{"symbol":"AAPL","script":"RSI-CROSS"}', headers={"content-type": "text/plain"})
    assert r.status_code == 400


def test_ts_alert_command_rules_mirror_the_server():
    """`frontend/src/command/scriptAlertArgs.ts` checks the script name and the condition length before it asks the server."""
    import re
    from pathlib import Path

    from openterm.idents import STORED_NAME_RE

    ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "command" / "scriptAlertArgs.ts").read_text(encoding="utf-8")
    name = re.search(r"export const SCRIPT_NAME = /(.+)/;", ts)
    assert name, "SCRIPT_NAME not found in scriptAlertArgs.ts"
    assert name.group(1).removesuffix("$") == STORED_NAME_RE.pattern.removesuffix(r"\Z")
    cond = re.search(r"export const MAX_COND = (\d+);", ts)
    assert cond and int(cond.group(1)) == script_routes.MAX_COND
