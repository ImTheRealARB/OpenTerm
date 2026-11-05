"""Phase 20: alerts that fire on the server with no browser connected.

Unit tests use a fake hub (just the parts the engine touches), a fake clock and a recording `deliver`, so no network and
no real WebSocket. The last group drives the real app through HTTP (fixture + synthetic mode).
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from openterm import alert_channels, delivery
from openterm.alerts_engine import STALE_S, AlertsEngine, news_match, rule_met
from openterm.db import open_db
from openterm.delivery import settings as dsettings
from openterm.streaming.tick import Tick
from openterm.userdata import UserDataError

T0 = 1_800_000_000.0  # a fixed "now" so ages are exact


class Clock:
    t = T0

    def __call__(self):
        return self.t


class FakeHub:
    """Just what the engine uses from Hub: tick listeners, refcounted subscribe/unsubscribe, broadcast."""

    def __init__(self):
        self.tick_listeners, self.frames, self.subscribed = [], [], set()

    async def subscribe(self, client, symbols):
        client.symbols.update(symbols)
        self.subscribed |= set(symbols)

    async def unsubscribe(self, client, symbols):
        client.symbols.difference_update(symbols)
        self.subscribed -= set(symbols)

    def broadcast(self, frame):
        self.frames.append(frame)


def tick(symbol="AAPL", price=201.0, source="y", age=1.0, clock=None, change=None, pct=None):
    """A tick whose own timestamp is `age` seconds before the (fake) now."""
    now = clock() if clock else T0
    return Tick(symbol, price, change, pct, None, None, None, int((now - age) * 1000), source)


@pytest.fixture
async def rig(tmp_path):
    db = await open_db(tmp_path / "a.db")
    clock, hub, delivered = Clock(), FakeHub(), []
    news = {"env": {"data": {"items": []}, "stale": False, "age_s": 5, "source": "rss"}}

    async def news_fetch(symbol):
        return news["env"]

    engine = AlertsEngine(db, hub, lambda *a: delivered.append(a), news_fetch, fixtures=False, now=clock)
    # test handles hung on the engine so each test reads them from one place
    engine.delivered, engine.clock, engine.news_env, engine.hub_ = delivered, clock, news, hub
    yield engine
    await engine.stop()
    await db.close()


async def settle(engine):
    """Waits for the fire tasks the last ticks started."""
    await asyncio.gather(*list(engine._tasks))


async def add(engine, symbol="AAPL", op=">", value=200, unit="price"):
    a = await engine.alerts.create({"symbol": symbol, "op": op, "unit": unit, "value": value})
    await engine.sync()
    return a


# ---------------------------------------------------------------- pure rules


def test_rule_maths_matches_the_browser_rules():
    assert rule_met(">", "price", 200, 200.0, None, None)  # inclusive
    assert not rule_met(">", "price", 200, 199.99, None, None)
    assert rule_met("<", "pct", -3, 100, None, -3.5)  # change -3.5 on price 100 is -3.38%
    assert rule_met(">", "pct", 5, 110, 5.5, None)
    assert not rule_met(">", "pct", 5, 110, None, None)  # no pct and no change: cannot judge
    assert not rule_met(">", "price", 1, float("nan"), None, None)


def test_news_match_is_whole_word_case_insensitive_with_optional_plural():
    assert news_match("RECALL", "Apple announces recall of chargers")
    assert news_match("recall", "Recalls widen")
    assert not news_match("RECALL", "Recallable bonds")
    assert not news_match("", "anything")


# ---------------------------------------------------------------- price alerts


async def test_fires_with_no_websocket_client_and_hands_the_message_to_delivery(rig):
    a = await add(rig)
    assert rig.hub_.subscribed == {"AAPL"}  # the engine holds the subscription itself, like a panel would
    rig.on_tick(tick(price=201.5, clock=rig.clock))
    await settle(rig)
    stored = (await rig.alerts.all())[0]
    assert stored["status"] == "triggered" and stored["trigger_price"] == 201.5 and stored["triggered_at"] == T0
    assert rig.hub_.frames == [["A", "price", a["id"]]]  # open tabs are told
    (kind, ref, subject, text, extra), = rig.delivered
    assert (kind, ref, extra) == ("alert", a["id"], {"kind": "alert", "symbol": "AAPL"})
    assert "AAPL" in subject and "201.5" in text and "yahoo stream" in text and "by the OpenTerm server" in text
    assert rig.hub_.subscribed == set()  # nothing left to watch once it fired


async def test_it_fires_once_even_if_many_ticks_arrive_at_once(rig):
    await add(rig)
    for p in (201, 202, 203):
        rig.on_tick(tick(price=p, clock=rig.clock))
    await settle(rig)
    assert len(rig.delivered) == 1 and len(rig.hub_.frames) == 1


async def test_it_does_not_fire_again_after_it_fired(rig):
    await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    rig.on_tick(tick(price=250, clock=rig.clock))  # the rule is gone from the engine's list
    await settle(rig)
    assert len(rig.delivered) == 1


async def test_a_browser_that_triggered_it_first_means_no_second_message(rig):
    """The trigger route (browser path) and the engine share one store call; the loser sees changed=False and sends nothing."""
    a = await add(rig)
    await rig.alerts.trigger(a["id"], 205.0, T0)  # e.g. another path got there first
    rig._rules = {"AAPL": [a]}  # the engine has not synced yet (stale rule list), the worst case
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    assert rig.delivered == [] and rig.hub_.frames == []


@pytest.mark.parametrize(("kw", "reason"), [({"source": "s"}, "SYNTHETIC"), ({"age": STALE_S + 5}, "STALE")])
async def test_bad_ticks_never_fire_and_the_skip_is_recorded(rig, kw, reason):
    a = await add(rig)
    rig.on_tick(tick(clock=rig.clock, **kw))
    await settle(rig)
    assert (await rig.alerts.all())[0]["status"] == "active" and rig.delivered == []
    (skip,) = rig.state()["skipped"]
    assert skip["key"] == f"price:{a['id']}" and reason in skip["reason"] and skip["label"] == "AAPL > 200"
    rig.on_tick(tick(clock=rig.clock))  # a good tick afterwards still fires, and the note goes away
    await settle(rig)
    assert (await rig.alerts.all())[0]["status"] == "triggered" and rig.state()["skipped"] == []


async def test_fixture_mode_never_fires(rig):
    rig.fixtures = True
    await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    assert (await rig.alerts.all())[0]["status"] == "active" and rig.delivered == []
    assert rig.state()["skipped"][0]["reason"] == "FIXTURE MODE"


async def test_a_tick_that_does_not_meet_the_rule_does_nothing_and_leaves_no_note(rig):
    await add(rig)
    rig.on_tick(tick(price=150, clock=rig.clock))
    await settle(rig)
    assert (await rig.alerts.all())[0]["status"] == "active" and rig.state()["skipped"] == []


async def test_a_percent_alert_uses_the_tick_change(rig):
    await add(rig, symbol="MSFT", op="<", unit="pct", value=-3)
    rig.on_tick(tick("MSFT", price=100, change=-3.5, clock=rig.clock))
    await settle(rig)
    assert (await rig.alerts.all())[0]["status"] == "triggered"


async def test_ticks_for_unwatched_symbols_are_ignored_and_do_not_touch_the_tick_age(rig):
    await add(rig)
    rig.on_tick(tick("MSFT", price=999, clock=rig.clock))
    assert rig.state()["last_tick_age_s"] is None  # only watched symbols count
    rig.clock.t = T0 + 4
    rig.on_tick(tick("AAPL", price=1, clock=rig.clock))
    rig.clock.t = T0 + 7.5
    assert rig.state()["last_tick_age_s"] == 3.5


async def test_rearm_makes_it_fire_again_once_sync_runs(rig):
    a = await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    await rig.alerts.rearm(a["id"])
    await rig.sync()  # the rearm route does this
    assert rig.hub_.subscribed == {"AAPL"}
    rig.on_tick(tick(price=205, clock=rig.clock))
    await settle(rig)
    assert len(rig.delivered) == 2


async def test_a_restart_reloads_active_rules_from_the_database(rig):
    await add(rig, symbol="MSFT", value=300)
    fresh = AlertsEngine(rig.db, FakeHub(), lambda *a: None, None, fixtures=False, now=rig.clock)  # new process, same database
    await fresh.start()
    try:
        assert fresh.state()["watching"] == ["MSFT"] and fresh.hub.subscribed == {"MSFT"}
        assert fresh.running and fresh.on_tick in fresh.hub.tick_listeners
    finally:
        await fresh.stop()
    assert not fresh.running and fresh.hub.tick_listeners == [] and fresh.hub.subscribed == set()


async def test_a_triggered_alert_stays_triggered_across_a_restart(rig):
    await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    fresh = AlertsEngine(rig.db, FakeHub(), lambda *a: None, None, fixtures=False, now=rig.clock)
    await fresh.start()
    try:
        assert fresh.state()["watching"] == []  # nothing active, so nothing to fire twice
    finally:
        await fresh.stop()


async def test_a_failing_delivery_hook_does_not_break_the_engine(rig):
    def boom(*a):
        raise RuntimeError("queue broke")

    rig.deliver = boom
    await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    assert (await rig.alerts.all())[0]["status"] == "triggered"  # the trigger itself was recorded
    assert rig.hub_.subscribed == set()  # the engine still cleaned up after the failure


# ---------------------------------------------------------------- channel routing through the real Phase 17 delivery


class FakeKeys:
    def get(self, name):
        return {"TELEGRAM_BOT_TOKEN": "x" * 20}


async def test_a_fired_alert_reaches_the_enabled_delivery_channel(rig):
    """Engine -> delivery.spawn -> the channel sender, with only the senders injected (as CLAUDE.md describes)."""
    sent = []

    async def telegram(app, values, cfg, subject, text, extra):
        sent.append((subject, text))

    app = SimpleNamespace(state=SimpleNamespace(
        userdata=SimpleNamespace(db=rig.db), keys=FakeKeys(), settings=SimpleNamespace(openterm_fixtures=False),
        delivery_senders={"telegram": telegram}))
    await dsettings.put(rig.db, {"channels": {"telegram": True}, "telegram_chat_id": "12345"})
    rig.deliver = lambda *a: delivery.spawn(app, *a)
    await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    await asyncio.gather(*list(app.state.delivery_tasks))
    assert len(sent) == 1 and "AAPL" in sent[0][0] and "checked by the OpenTerm server" in sent[0][1]
    rows = await (await rig.db.execute("SELECT kind, channel, status FROM deliveries")).fetchall()
    assert rows == [("alert", "telegram", "sent")]


async def test_a_disabled_channel_receives_nothing(rig):
    sent = []

    async def telegram(app, values, cfg, subject, text, extra):
        sent.append(text)

    app = SimpleNamespace(state=SimpleNamespace(
        userdata=SimpleNamespace(db=rig.db), keys=FakeKeys(), settings=SimpleNamespace(openterm_fixtures=False),
        delivery_senders={"telegram": telegram}))
    rig.deliver = lambda *a: delivery.spawn(app, *a)  # no channel switched on in DELIVERY settings
    await add(rig)
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    await asyncio.gather(*list(app.state.delivery_tasks))
    assert sent == []


# ---------------------------------------------------------------- news alerts


async def add_news(engine, word="RECALL", symbol="AAPL"):
    a = await engine.news.create({"word": word, "symbol": symbol})
    # the store stamps real wall-clock time; pin it to the test clock so "published after the alert was made" is meaningful
    await engine.db.execute("UPDATE news_alerts SET created_at=? WHERE id=?", (T0, a["id"]))
    await engine.db.commit()
    return a


def headline(title, published, url="https://example.com/x"):
    return {"title": title, "published": published, "url": url}


async def test_news_match_fires_once_and_delivers(rig):
    a = await add_news(rig)
    rig.news_env["env"]["data"]["items"] = [headline("Apple recall of chargers", T0 + 10)]
    rig.clock.t = T0 + 20
    assert await rig.poll_news() == 1
    stored = (await rig.news.all())[0]
    assert stored["status"] == "triggered" and stored["headline"] == "Apple recall of chargers" and stored["triggered_at"] == T0 + 20
    assert rig.hub_.frames == [["A", "news", a["id"]]]
    (kind, ref, subject, text, _extra), = rig.delivered
    assert kind == "news" and ref == a["id"] and "RECALL" in subject and "Apple recall of chargers" in text
    assert await rig.poll_news() == 0  # triggered alerts are not looked at again
    assert len(rig.delivered) == 1


async def test_old_headlines_and_non_matches_do_not_fire(rig):
    await add_news(rig)
    rig.clock.t = T0 + 100
    rig.news_env["env"]["data"]["items"] = [headline("Apple recall", T0 - 50), headline("Apple earnings beat", T0 + 50)]
    assert await rig.poll_news() == 0
    assert rig.delivered == []


async def test_a_stale_news_answer_is_retried_once_then_not_acted_on(rig, monkeypatch):
    monkeypatch.setattr("openterm.alerts_engine.STALE_NEWS_RETRY_S", 0)
    a = await add_news(rig)
    rig.news_env["env"]["stale"] = True
    rig.news_env["env"]["data"]["items"] = [headline("Apple recall", T0 + 10)]
    rig.clock.t = T0 + 20
    assert await rig.poll_news() == 0
    assert "STALE" in rig.state()["skipped"][0]["reason"] and rig.state()["skipped"][0]["key"] == f"news:{a['id']}"
    rig.news_env["env"]["stale"] = False  # the refresh arrived
    assert await rig.poll_news() == 1
    assert rig.state()["skipped"] == []


async def test_a_news_outage_is_recorded_not_hidden(rig):
    await add_news(rig)

    async def boom(symbol):
        raise RuntimeError("down")

    rig.news_fetch = boom
    assert await rig.poll_news() == 0
    assert "NEWS UNAVAILABLE" in rig.state()["skipped"][0]["reason"]


async def test_news_alerts_skip_in_fixture_mode(rig):
    rig.fixtures = True
    await add_news(rig)
    assert await rig.poll_news() == 0
    assert rig.state()["skipped"][0]["reason"] == "FIXTURE MODE"


async def test_deleting_an_alert_clears_its_skip_note(rig):
    a = await add(rig)
    rig.on_tick(tick(clock=rig.clock, source="s"))
    assert len(rig.state()["skipped"]) == 1
    await rig.alerts.delete(a["id"])
    await rig.sync()
    assert rig.state()["skipped"] == [] and rig.hub_.subscribed == set()


# ---------------------------------------------------------------- the real app (fixture + synthetic mode)


def test_engine_endpoint_reports_state_and_the_honest_limit(client):
    s = client.get("/api/alerts/engine").json()
    assert s["running"] is True and s["note"] == "ACTIVE WHILE OPENTERM RUNNING"
    assert s["fixtures"] is True and s["watching"] == [] and s["skipped"] == []
    assert s["last_tick_age_s"] is None


def test_the_engine_watches_new_alerts_and_refuses_test_data_with_a_reason(client):
    r = client.post("/api/alerts", json={"symbol": "SYN0001", "op": ">", "unit": "price", "value": 0.0001})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    assert client.get("/api/alerts/engine").json()["watching"] == ["SYN0001"]
    end, s = time.time() + 5, {}
    while time.time() < end:  # the synthetic stream ticks SYN0001, which satisfies the rule; the engine must refuse it
        s = client.get("/api/alerts/engine").json()
        if s["skipped"]:
            break
        time.sleep(0.05)
    assert s["skipped"] and s["skipped"][0]["key"] == f"price:{aid}" and s["skipped"][0]["reason"] == "FIXTURE MODE"
    assert s["last_tick_age_s"] is not None
    assert client.get("/api/alerts").json()["alerts"][0]["status"] == "active"  # not fired
    assert client.delete(f"/api/alerts/{aid}").status_code == 200
    s = client.get("/api/alerts/engine").json()
    assert s["watching"] == [] and s["skipped"] == []


def test_rearm_puts_the_symbol_back_under_watch(client):
    aid = client.post("/api/alerts", json={"symbol": "SYN0002", "op": ">", "unit": "price", "value": 1e9}).json()["id"]
    assert client.post(f"/api/alerts/{aid}/trigger", json={"price": 5, "at": T0, "synthetic": True}).json()["changed"] is True
    assert client.get("/api/alerts/engine").json()["watching"] == []
    assert client.post(f"/api/alerts/{aid}/rearm").status_code == 200
    assert client.get("/api/alerts/engine").json()["watching"] == ["SYN0002"]


def test_a_browser_trigger_on_test_data_is_never_pushed_to_delivery(client, monkeypatch):
    """The route used by the browser: labelled SYNTHETIC firing stays in-app, a real report still goes to delivery."""
    pushed = []
    monkeypatch.setattr("openterm.delivery.spawn", lambda app, kind, ref, subject, text, extra=None: pushed.append(kind))
    mk = lambda: client.post("/api/alerts", json={"symbol": "SYN0003", "op": ">", "unit": "price", "value": 1e9}).json()["id"]
    a, b = mk(), mk()
    assert client.post(f"/api/alerts/{a}/trigger", json={"price": 5, "at": T0, "synthetic": True}).json()["changed"] is True
    assert pushed == []
    assert client.post(f"/api/alerts/{b}/trigger", json={"price": 5, "at": T0}).json()["changed"] is True
    assert pushed == ["alert"]
    assert client.post(f"/api/alerts/{b}/trigger", json={"price": 6, "at": T0}).json()["changed"] is False  # once per arm
    assert pushed == ["alert"]


# ---------------------------------------------------------------- per-alert channels (ALRT ... VIA TG,EMAIL)


def delivery_rig(rig, senders):
    """Wires the engine to the real delivery path (alert_channels.spawn -> delivery.dispatch) with injected senders."""
    app = SimpleNamespace(state=SimpleNamespace(
        userdata=SimpleNamespace(db=rig.db), keys=FakeKeys(), settings=SimpleNamespace(openterm_fixtures=False),
        delivery_senders=senders))
    rig.deliver = lambda *a, **kw: alert_channels.spawn(app, *a, **kw)
    return app


def recorder(sent, name):
    async def send(app, values, cfg, subject, text, extra):
        sent.append(name)

    return send


def senders_for(sent):
    return {c: recorder(sent, c) for c in ("email", "telegram", "webhook")}


async def enable(rig, **channels):
    await dsettings.put(rig.db, {"channels": channels, "telegram_chat_id": "12345", "email_to": "me@example.com"})


async def fire_price_alert(rig, app, **create):
    await rig.alerts.create({"symbol": "AAPL", "op": ">", "unit": "price", "value": 200, **create})
    await rig.sync()
    rig.on_tick(tick(clock=rig.clock))
    await settle(rig)
    await asyncio.gather(*list(app.state.delivery_tasks))


async def log_rows(rig):
    return await (await rig.db.execute("SELECT kind, channel, status, detail FROM deliveries ORDER BY id")).fetchall()


async def test_via_sends_only_to_the_chosen_channels(rig):
    sent = []
    app = delivery_rig(rig, senders_for(sent))
    await enable(rig, email=True, telegram=True, webhook=True)
    await fire_price_alert(rig, app, channels=["tg"])  # the TG alias is stored as telegram
    assert sent == ["telegram"]
    assert (await rig.alerts.all())[0]["channels"] == ["telegram"]
    assert await log_rows(rig) == [("alert", "telegram", "sent", None)]


async def test_no_via_sends_to_every_enabled_channel_as_before(rig):
    sent = []
    app = delivery_rig(rig, senders_for(sent))
    await enable(rig, email=True, telegram=True, webhook=False)
    await fire_price_alert(rig, app)
    assert sorted(sent) == ["email", "telegram"]
    assert (await rig.alerts.all())[0]["channels"] is None
    assert all(r[2] == "sent" for r in await log_rows(rig))  # and no CHANNEL OFF noise for a default alert


async def test_a_channel_that_is_switched_off_is_logged_as_skipped_channel_off(rig):
    sent = []
    app = delivery_rig(rig, senders_for(sent))
    await enable(rig, telegram=True, webhook=False)
    await fire_price_alert(rig, app, channels=["telegram", "webhook"])
    assert sent == ["telegram"]
    rows = await log_rows(rig)
    assert ("alert", "webhook", "skipped", "CHANNEL OFF") in rows and ("alert", "telegram", "sent", None) in rows


async def test_if_every_chosen_channel_is_off_nothing_is_sent_and_each_is_logged(rig):
    sent = []
    app = delivery_rig(rig, senders_for(sent))
    await enable(rig, telegram=True)  # telegram is on, but this alert asked only for email and webhook
    await fire_price_alert(rig, app, channels=["email", "webhook"])
    assert sent == []
    assert sorted(await log_rows(rig)) == [("alert", "email", "skipped", "CHANNEL OFF"), ("alert", "webhook", "skipped", "CHANNEL OFF")]


async def test_a_news_alert_honours_via_too(rig):
    sent = []
    app = delivery_rig(rig, senders_for(sent))
    await enable(rig, email=True, telegram=True, webhook=True)
    a = await rig.news.create({"word": "RECALL", "symbol": "AAPL", "channels": ["WEBHOOK"]})
    await rig.db.execute("UPDATE news_alerts SET created_at=? WHERE id=?", (T0, a["id"]))
    await rig.db.commit()
    rig.news_env["env"] = {"data": {"items": [headline("Apple recall widens", T0 + 60)]}, "stale": False, "age_s": 1, "source": "rss"}
    assert await rig.poll_news() == 1
    await asyncio.gather(*list(app.state.delivery_tasks))
    assert sent == ["webhook"]
    assert (await rig.news.all())[0]["channels"] == ["webhook"]


# ---- the validation and the HTTP routes


def test_parse_normalises_aliases_and_rejects_unknown_names():
    assert alert_channels.parse(None) is None
    assert alert_channels.parse(["tg", "TELEGRAM", "Email"]) == ["telegram", "email"]  # alias and full name are one channel
    for bad in ([], ["sms"], "telegram", [1], ["tg", ""]):
        with pytest.raises(UserDataError):
            alert_channels.parse(bad)


def test_the_create_routes_store_channels_and_answer_400_for_an_unknown_one(client):
    base = {"symbol": "SYN0004", "op": ">", "unit": "price", "value": 1e9}
    ok = client.post("/api/alerts", json={**base, "channels": ["TG", "email"]})
    assert ok.status_code == 200 and ok.json()["channels"] == ["telegram", "email"]
    assert client.post("/api/alerts", json=base).json()["channels"] is None
    bad = client.post("/api/alerts", json={**base, "channels": ["sms"]})
    assert bad.status_code == 400 and "SMS" in bad.text
    assert len(client.get("/api/alerts").json()["alerts"]) == 2  # the rejected one was not saved

    n = client.post("/api/newsalerts", json={"word": "RECALL", "symbol": None, "channels": ["webhook"]})
    assert n.status_code == 200 and n.json()["channels"] == ["webhook"]
    assert client.post("/api/newsalerts", json={"word": "RECALL", "channels": ["fax"]}).status_code == 400
    assert client.get("/api/newsalerts").json()["alerts"][0]["channels"] == ["webhook"]


def test_the_browser_trigger_routes_pass_the_alerts_channels_to_delivery(client, monkeypatch):
    pushed = []
    monkeypatch.setattr("openterm.alert_channels.spawn", lambda app, kind, ref, subject, text, extra=None, channels=None: pushed.append((kind, channels)))
    base = {"symbol": "SYN0005", "op": ">", "unit": "price", "value": 1e9}
    a = client.post("/api/alerts", json={**base, "channels": ["telegram"]}).json()["id"]
    b = client.post("/api/alerts", json=base).json()["id"]
    n = client.post("/api/newsalerts", json={"word": "RECALL", "channels": ["email"]}).json()["id"]
    for aid in (a, b):
        assert client.post(f"/api/alerts/{aid}/trigger", json={"price": 5, "at": T0}).json()["changed"] is True
    assert client.post(f"/api/newsalerts/{n}/trigger", json={"headline": "x", "url": None, "at": T0}).json()["changed"] is True
    assert pushed == [("alert", ["telegram"]), ("alert", None), ("news", ["email"])]
