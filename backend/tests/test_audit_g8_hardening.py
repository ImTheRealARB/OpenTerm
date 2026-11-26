"""Audit group 8, small hardening fixes: C-10, C-12, H-06, H-07, H-08, H-10, M-02, M-07, L-01, L-02.

One test (or two) per finding, each written to FAIL on the bug before the fix. Evidence: docs/review/verify_A.md and verify_B.md.
"""

import asyncio
import math
import multiprocessing as mp
import sqlite3
from types import SimpleNamespace

import aiosqlite
import httpx
import pytest

from openterm import db as dbmod
from openterm import smart_alerts
from openterm.errors import DataError
from openterm.jobs.runner import JobRunner
from openterm.journal import parsers
from openterm.keys import KeyStore, MemoryKeyring
from openterm.llm import client as llm_client
from openterm.llm import spend
from openterm.options import recorder as optrec
from openterm.recorder import Recorder, RecorderError
from openterm.userdata import UserData

# --- C-10: a broker trade id alone is not a unique key across imports --------------------------------------------------------

def _trade(time: str, trade_id: str = "T1", symbol: str = "INFY.NS", side: str = "buy", order_id: str = "O1"):
    return parsers.Trade(time, symbol, side, 10.0, 100.0, 0.0, "INR", "zerodha", order_id, trade_id)


def test_c10_same_trade_id_on_two_days_gets_two_keys_across_imports():
    day1, day2 = [_trade("2026-11-02T10:00:00")], [_trade("2026-11-03T10:00:00")]  # two files, one id reused (each file's own count is #1)
    parsers._keys(day1)
    parsers._keys(day2)
    assert day1[0].dkey != day2[0].dkey


def test_c10_a_reimport_of_the_same_trade_is_still_a_noop():
    a, b = [_trade("2026-11-02T10:00:00")], [_trade("2026-11-02T10:00:00")]
    parsers._keys(a)
    parsers._keys(b)
    assert a[0].dkey == b[0].dkey


# --- C-12: spend check must count prompt cost and calls already in flight ------------------------------------------------------

def test_c12_check_counts_prompt_cost_and_reserved_spend():
    price = {"input": 10.0, "output": 0.0}  # US$ per million tokens
    assert spend.check(0.0, 1.0, 10, price, False, prompt_tokens=50_000) is None  # 0.5 of 1.0
    assert spend.check(0.0, 1.0, 10, price, False, prompt_tokens=200_000) == "SPEND CAP REACHED"  # 2.0 > 1.0: a prompt alone passes the cap
    assert spend.check(0.0, 1.0, 10, price, False, reserved=0.9, prompt_tokens=50_000) == "SPEND CAP REACHED"  # 0.9 already promised


def _gateway(tmp_path, handler):
    store = KeyStore(env={"OPENAI_API_KEY": "sk-test-g8"}, dotenv=tmp_path / "k.env", keyring=MemoryKeyring())

    async def make():
        db = await aiosqlite.connect(tmp_path / "g.db")
        await db.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        prices = {"openai": {"gpt-test": {"input": 1.0, "output": 2.0}}}
        return llm_client.Gateway(store, http, db, {"prices": prices}), db

    return make


def test_c12_two_calls_in_flight_cannot_both_pass_a_cap_that_fits_one(tmp_path):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.sleep(0.05)  # call A is still streaming when call B checks the cap
        return httpx.Response(200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    make = _gateway(tmp_path, handler)

    async def go():
        gw, db = await make()
        try:
            await spend.set_cap(db, 0.0003)  # one call's worst case is ~0.0002, two are 0.0004
            msgs = [{"role": "user", "content": "hi"}]

            async def one():
                return [e async for e in gw.chat(msgs, model="gpt-test", provider="openai", max_tokens=100)]

            results = await asyncio.gather(one(), one())
            return results, gw._reserved
        finally:
            await gw.http.aclose()
            await db.close()

    results, reserved = asyncio.run(go())
    refused = [r for r in results if r and r[0].type == "error" and r[0].kind == "spend_cap"]
    assert len(refused) == 1 and len(calls) == 1
    assert reserved == pytest.approx(0.0)  # every reservation is released, also after a refusal or a finished stream


# --- H-06: a migration is all or nothing -------------------------------------------------------------------------------------

def test_h06_a_failed_migration_step_leaves_nothing_behind(tmp_path, monkeypatch):
    # Step 1 creates a table, then its second statement fails (a crash half way looks the same to the database).
    monkeypatch.setattr(dbmod, "MIGRATIONS", [["CREATE TABLE g8_a (x INTEGER)", "CREATE TABLE g8_a (x INTEGER)"]])
    path = tmp_path / "m.db"

    async def go():
        db = await aiosqlite.connect(path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                await dbmod.migrate(db)
            async with db.execute("PRAGMA user_version") as cur:
                (version,) = await cur.fetchone()
            async with db.execute("SELECT name FROM sqlite_master WHERE name='g8_a'") as cur:
                table = await cur.fetchone()
            return version, table
        finally:
            await db.close()

    version, table = asyncio.run(go())
    assert version == 0 and table is None  # before the fix the table stayed, so a retry failed forever with "already exists"


# --- H-07: two simultaneous starts of one symbol --------------------------------------------------------------------------

def test_h07_concurrent_starts_of_one_symbol_record_once(tmp_path):
    async def limits():
        return 10**9, 30

    async def settings():
        return {}

    async def go():
        rec = Recorder(tmp_path, None, settings)
        rec._limits = limits

        async def poll(base, quote):
            await asyncio.sleep(0.05)  # a slow first request: the window in which a second start used to slip through
            return {"venue": "TEST"}

        async def run(r, base, quote):
            await asyncio.sleep(3600)

        rec._poll_once, rec._ingest, rec._run = poll, (lambda r, first: None), run
        results = await asyncio.gather(rec.start("BTCUSDT"), rec.start("BTCUSDT"), return_exceptions=True)
        tasks = [a.task for a in rec.active.values()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return results, len(tasks), rec._starting

    results, running, starting = asyncio.run(go())
    errors = [r for r in results if isinstance(r, RecorderError)]
    assert len(errors) == 1 and errors[0].kind == "conflict" and running == 1
    assert not starting  # the reservation is released


# --- H-08: blocking work must not run on the event loop -------------------------------------------------------------------

def _on_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_h08_nb_start_and_stop_run_off_the_loop(client):
    seen = []
    nb = client.app.state.nb
    nb.start = lambda: seen.append(("start", _on_loop())) or {"running": False}
    nb.stop = lambda: seen.append(("stop", _on_loop())) or {"running": False}
    assert client.post("/api/nb/start").status_code == 200
    assert client.post("/api/nb/stop").status_code == 200
    assert seen == [("start", False), ("stop", False)]


def test_h08_bt_import_parses_the_csv_off_the_loop(client, monkeypatch):
    from openterm.bt import csvimport

    seen = []

    def spy(text, tz):
        seen.append(_on_loop())
        raise csvimport.CsvError("stop here")

    monkeypatch.setattr(csvimport, "parse_bars", spy)
    r = client.post("/api/bt/import?symbol=G8TEST", content=b"date,open,high,low,close\n2026-01-02,1,2,0.5,1.5\n",
                    headers={"content-type": "text/csv"})
    assert r.status_code == 400 and seen == [False]


# --- H-10: smart alerts ---------------------------------------------------------------------------------------------------

def test_h10_a_non_finite_price_never_fires_a_line_alert():
    a = {"kind": "HLINE", "pts": [{"t": 0, "p": 100.0}], "side": 1}  # created with the price above the line
    assert smart_alerts.fired(a, 90.0, 0.0) is True  # a real cross still fires
    for bad in (math.nan, math.inf, -math.inf):
        assert smart_alerts.fired(a, bad, 0.0) is False
    ch = {"kind": "PCHAN", "pts": [{"t": 0, "p": 1.0}, {"t": 10, "p": 2.0}, {"t": 0, "p": 3.0}]}
    assert smart_alerts.fired(ch, math.nan, 5.0) is False


def test_h10_check_one_refuses_stale_bars():
    async def history(sym, rng, interval):
        return {"data": {"t": [1.0], "c": [1.0], "tz": "UTC"}, "source": "yahoo", "stale": True}

    app = SimpleNamespace(state=SimpleNamespace(jobs=SimpleNamespace(on_done={}), service=SimpleNamespace(history=history)))
    with pytest.raises(DataError) as e:
        asyncio.run(smart_alerts.check_one(app, {"id": "a1", "symbol": "AAPL", "rule": "RSI14<30"}))
    assert e.value.kind == "unavailable" and "STALE" in str(e.value)


def test_h10_a_failed_first_check_does_not_leave_the_alert_saved(client, monkeypatch):
    async def boom(app, a):
        raise DataError("unavailable", "NO BARS")

    monkeypatch.setattr(smart_alerts, "check_one", boom)
    r = client.post("/api/smartalerts/indicator", json={"symbol": "AAPL", "rule": "RSI14<30"})
    assert r.status_code >= 400
    assert client.get("/api/smartalerts").json()["indicator"] == []  # before the fix: a saved alert stuck on "FIRST CHECK RUNNING"


# --- M-02: leaked handles -------------------------------------------------------------------------------------------------

def test_m02_close_closes_the_wake_pipes():
    r = JobRunner(None, lambda frame: None, workers=1)
    r._wake_r, r._wake_w = mp.get_context("spawn").Pipe(duplex=False)
    wake_r, wake_w = r._wake_r, r._wake_w
    r.close()
    assert wake_r.closed and wake_w.closed


def test_m02_replacing_a_worker_closes_the_old_task_pipe(monkeypatch):
    from openterm.jobs import runner

    class FakeWorker:
        def __init__(self, ctx, wid):
            self.wid = wid
            self.results, self.tasks = ctx.Pipe(duplex=False)  # any two real connections will do

    ctx = mp.get_context("spawn")
    monkeypatch.setattr(runner, "Worker", FakeWorker)
    r = JobRunner(None, lambda frame: None, workers=1)
    old = FakeWorker(ctx, 0)
    r.workers = [old]
    r._replace(old)
    assert old.tasks.closed and r.workers[0] is not old


def test_m02_a_failed_aisstream_subscribe_closes_the_socket(monkeypatch):
    import websockets

    from openterm.providers import aisstream
    from openterm.providers.base import ProviderError

    class FakeWs:
        closed = False

        async def send(self, data):
            raise OSError("connection reset")

        async def close(self):
            FakeWs.closed = True

    async def connect(*a, **k):
        return FakeWs()

    monkeypatch.setattr(websockets, "connect", connect)
    with pytest.raises(ProviderError):
        asyncio.run(aisstream._open("wss://example.test", "k", (0.0, 0.0, 1.0, 1.0), ("PositionReport",)))
    assert FakeWs.closed  # an OSError used to escape here and leak the open socket


# --- M-07: watchlist edits are read-modify-write -------------------------------------------------------------------------

def test_m07_concurrent_watchlist_edits_do_not_lose_a_symbol():
    async def go():
        db = await dbmod.open_db(":memory:")
        try:
            ud = UserData(db)
            await ud.save_watchlist("G8", ["AAPL"])
            await asyncio.gather(ud.edit_watchlist("G8", add=["MSFT"]), ud.edit_watchlist("G8", add=["NVDA"]))
            return (await ud.watchlist("G8"))["symbols"]
        finally:
            await db.close()

    assert set(asyncio.run(go())) == {"AAPL", "MSFT", "NVDA"}


# --- L-01: the chain recorder keeps growing ------------------------------------------------------------------------------

def test_l01_prune_drops_old_chain_rows_and_keeps_the_atm_history():
    async def go():
        db = await dbmod.open_db(":memory:")
        try:
            for day in ("2020-01-02", "2026-11-20"):
                await db.execute("INSERT INTO chain_snaps (day, symbol, expiry, kind, strike, iv, oi, volume) VALUES (?,?,?,?,?,?,?,?)",
                                 (day, "AAPL", 1, "call", 100.0, 0.3, 10, 5))
                await db.execute("INSERT INTO chain_atm (day, symbol, expiry, spot, atm_iv, em_pct) VALUES (?,?,?,?,?,?)",
                                 (day, "AAPL", 1, 100.0, 0.3, 2.0))
            await db.commit()
            removed = await optrec.prune(db, "2026-11-26")
            async with db.execute("SELECT day FROM chain_snaps") as cur:
                snaps = [r[0] async for r in cur]
            async with db.execute("SELECT day FROM chain_atm ORDER BY day") as cur:
                atm = [r[0] async for r in cur]
            return removed, snaps, atm
        finally:
            await db.close()

    removed, snaps, atm = asyncio.run(go())
    assert removed == 1 and snaps == ["2026-11-20"]
    assert atm == ["2020-01-02", "2026-11-20"]  # one small row per day: the IV rank history stays


# --- L-02: news alert routes keep the engine in step; recorder names stay readable -------------------------------------------

def test_l02_news_alert_create_and_delete_sync_the_engine(client):
    calls = []
    engine = client.app.state.alerts_engine
    real = engine.sync

    async def counting():
        calls.append(1)
        await real()

    engine.sync = counting
    made = client.post("/api/newsalerts", json={"word": "merger"})
    assert made.status_code == 200 and len(calls) == 1
    assert client.delete(f"/api/newsalerts/{made.json()['id']}").status_code == 200
    assert len(calls) == 2


def test_l02_recorder_refuses_a_name_the_session_route_could_not_read(tmp_path):
    async def settings():
        return {}

    rec = Recorder(tmp_path, None, settings, kite=object())
    with pytest.raises(RecorderError) as e:
        asyncio.run(rec.start("A" * 40 + ".NS"))
    assert e.value.kind == "bad_request" and "2-30" in str(e.value)  # refused for its name, not for the missing Kite ticker
