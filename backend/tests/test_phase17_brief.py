"""Phase 17 C: the daily brief (data only, no AI), its routes and its cron job. No network (fixture mode)."""

import time

from fastapi.testclient import TestClient

from openterm import brief, scheduler
from tests.test_phase17_delivery import SMTP_KEYS, FakeSMTP, configure, fake_email_sender

IDS = ["movers", "alerts", "earnings", "eco", "news"]
KEYS = {"id", "title", "source", "age_s", "stale", "error", "lines"}


def run(client, send=0):
    r = client.post(f"/api/brief/run?send={send}")
    assert r.status_code == 200, r.text
    return r.json()


def test_no_brief_before_a_run(client):
    assert client.get("/api/brief").json() == {"brief": None}


def test_run_builds_five_sections_with_the_contract_keys(client):
    client.put("/api/watchlists/default", json={"symbols": ["AAPL", "MSFT"]})
    body = run(client)
    b = body["brief"]
    assert body["delivered"] is None and set(b) == {"at", "sections", "watchlist"}
    assert b["watchlist"] == "DEFAULT"
    assert [s["id"] for s in b["sections"]] == IDS
    for s in b["sections"]:
        assert set(s) == KEYS and isinstance(s["lines"], list) and isinstance(s["stale"], bool)
    movers = b["sections"][0]
    assert movers["error"] is None and movers["source"] and "up" in movers["lines"][0]
    assert client.get("/api/brief").json()["brief"] == b  # stored in kv brief:last


def test_no_watchlist_says_so(client):
    movers = run(client)["brief"]["sections"][0]
    assert movers["lines"] == ["NO WATCHLIST: create one with WL"]


def test_failing_section_shows_err_and_the_brief_still_returns(client):
    # the fixture Nasdaq earnings route answers 404 for today, which is a real failing section
    client.put("/api/watchlists/default", json={"symbols": ["AAPL"]})
    by_id = {s["id"]: s for s in run(client)["brief"]["sections"]}
    assert by_id["earnings"]["error"].startswith("ERR ") and by_id["earnings"]["lines"] == []
    assert by_id["movers"]["error"] is None and by_id["news"]["lines"]


def test_format_text_has_a_header_per_section():
    b = {"at": time.time(), "watchlist": None, "sections": [
        {"id": "news", "title": "TOP HEADLINES", "source": "rss", "age_s": 12.0, "stale": False, "error": None,
         "lines": ["a"]},
        {"id": "eco", "title": "ECONOMIC EVENTS TODAY", "source": None, "age_s": None, "stale": False,
         "error": "ERR eco", "lines": []}]}
    subject, text = brief.format_text(b)
    assert subject.startswith("OpenTerm daily brief 20")
    assert "== TOP HEADLINES (rss, 12s old) ==\na" in text and "== ECONOMIC EVENTS TODAY ==\nERR eco" in text


def test_send_logs_kind_brief(client):
    client.app.state.keys.set("smtp", SMTP_KEYS)
    client.app.state.delivery_senders = {"email": fake_email_sender()}
    configure(client)
    body = run(client, send=1)
    assert [d["channel"] for d in body["delivered"]] == ["email"] and body["delivered"][0]["status"] == "sent"
    rows = client.get("/api/delivery/log").json()["deliveries"]
    assert rows[0]["kind"] == "brief" and len(FakeSMTP.sent) == 1
    assert "OpenTerm daily brief" in FakeSMTP.sent[0]["Subject"]


def test_run_needs_loopback(client):
    remote = TestClient(client.app, client=("10.1.2.3", 40000))
    assert remote.post("/api/brief/run").status_code == 403
    assert remote.get("/api/brief").status_code == 200  # reading the last brief is fine


def test_schedule_brief_adds_and_removes_the_job(client):
    sched = client.app.state.scheduler
    app = client.app
    scheduler.schedule_brief(sched, app, {"enabled": True, "time": "08:30", "days": "mon-fri", "tz": "Asia/Kolkata"})
    job = sched.get_job("brief")
    f = {x.name: str(x) for x in job.trigger.fields}
    assert f["day_of_week"] == "mon-fri" and f["hour"] == "8" and f["minute"] == "30"
    assert str(job.trigger.timezone) == "Asia/Kolkata"
    scheduler.schedule_brief(sched, app, {"enabled": True, "time": "17:05", "days": "daily", "tz": ""})
    f = {x.name: str(x) for x in sched.get_job("brief").trigger.fields}
    assert f["day_of_week"] == "*" and f["hour"] == "17" and f["minute"] == "5"
    scheduler.schedule_brief(sched, app, {"enabled": False, "time": "08:30", "days": "daily", "tz": ""})
    assert sched.get_job("brief") is None
    scheduler.schedule_brief(sched, app, {"enabled": False, "time": "08:30", "days": "daily", "tz": ""})  # no error


def test_put_delivery_reschedules(client):
    sched = client.app.state.scheduler
    assert sched.get_job("brief") is None
    assert client.put("/api/delivery", json={"brief": {"enabled": True, "time": "07:15"}}).status_code == 200
    assert sched.get_job("brief") is not None
    assert client.put("/api/delivery", json={"brief": {"enabled": False}}).status_code == 200
    assert sched.get_job("brief") is None
