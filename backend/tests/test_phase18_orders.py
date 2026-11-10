"""Phase 18: the order core (model, mandate, confirm tokens, kill switch, structural mode, ledger). A fake broker stands in for the network.

Nothing here touches the network. Broker-shaped data comes from FakeBroker or from the doc-shaped fixtures (NOT A RECORDING) in test_phase18_brokers.py.
"""

import pytest

from openterm.ai.audit import AuditLog
from openterm.db import open_db
from openterm.orders import mandate as md
from openterm.orders.brokers.base import Broker
from openterm.orders.confirm import ConfirmTokens
from openterm.orders.errors import OrderError
from openterm.orders.ledger import OrderLedger
from openterm.orders.model import Order, fingerprint
from openterm.orders.service import LIVE_PHRASE, OrderService

PAPER, LIVE = "alpaca-paper", "alpaca-live"


class FakeBroker(Broker):
    """In-memory broker. `mode` is what its account reports, like a real adapter's host-derived mode."""

    def __init__(self, bid=PAPER, mode="paper", ready=True, positions=None, fail_submit=None):
        self.id, self.label, self.mode, self.ready = bid, bid, mode, ready
        self._positions = positions if positions is not None else []
        self.fail_submit = fail_submit
        self.sent, self.cancelled, self.open, self.cancel_all_calls = [], [], [], 0

    def not_ready(self):
        return None if self.ready else OrderError("key_required", "KEY REQUIRED: set FAKE_KEY in APIKEYS")

    async def account(self):
        return {"broker": self.id, "id": "FAKE0001", "mode": self.mode, "currency": "USD", "equity": 1.0, "cash": 1.0, "buying_power": 1.0,
                "status": "ACTIVE", "trading_blocked": False, "host": "fake", "note": ""}

    async def positions(self):
        return self._positions

    async def open_orders(self):
        return self.open

    async def fills_today(self):
        return []

    async def submit(self, order, client_id):
        if self.fail_submit:
            raise self.fail_submit
        self.sent.append((order, client_id))
        row = {"id": f"B{len(self.sent)}", "client_id": client_id, "symbol": order.symbol, "side": order.side, "qty": order.qty, "status": "NEW"}
        self.open.append(row)
        return row

    async def cancel(self, order_id):
        self.cancelled.append(order_id)

    async def cancel_all(self):
        self.cancel_all_calls += 1
        rows = [{"id": o["id"], "ok": True, "detail": "x"} for o in self.open]
        self.open = []
        return rows


async def quote(symbol):
    return 100.0, "TEST QUOTE"


async def no_quote(symbol):
    return None, "NO FRESH QUOTE"


OPEN_DBS: list = []


@pytest.fixture(autouse=True)
async def close_dbs():
    yield
    while OPEN_DBS:
        await OPEN_DBS.pop().close()


async def make(tmp_path, *brokers, price=quote, allow=("AAPL",), **mandate):
    db = await open_db(tmp_path / "o.db")
    OPEN_DBS.append(db)
    svc = OrderService(db, OrderLedger(AuditLog(db)), {b.id: b for b in brokers or [FakeBroker()]}, price)
    await svc.set_mandate({"symbols": list(allow), "max_shares": 100, "max_notional": 10000, "max_gross": 50000, "max_trades_per_day": 5, **mandate})
    return svc


def body(**kw):
    return {"broker": PAPER, "symbol": "AAPL", "side": "buy", "qty": 10, "type": "market", "tif": "day", **kw}


async def confirmed(svc, **kw):
    pre = await svc.preview(body(**kw))
    assert pre["token"], pre["check"]
    return pre["token"]


async def ledger_events(svc):
    return [e for e in await svc.ledger.audit.entries(500) if e["kind"] == "order"][::-1]


# --- model --------------------------------------------------------------------------------------------------------------------------------
def test_order_validation():
    o = Order.from_body(body(type="limit", limit_price=190.5, symbol=" aapl "))
    assert (o.symbol, o.limit_price, o.type) == ("AAPL", 190.5, "limit")
    for bad in ({"side": "hold"}, {"qty": 0}, {"qty": -1}, {"qty": float("nan")}, {"qty": True}, {"type": "limit"}, {"type": "stop"},
                {"limit_price": 5}, {"tif": "forever"}, {"symbol": "A B"}, {"broker": "ibkr"}, {"product": "CNC"}, {"qty": 1.0000001}):
        with pytest.raises(OrderError) as e:
            Order.from_body(body(**bad))
        assert e.value.kind == "bad_request", bad


@pytest.mark.parametrize("word", ["mode", "live", "paper", "host", "base_url", "environment", "sandbox", "force"])
def test_a_request_can_never_set_paper_or_live(word):
    with pytest.raises(OrderError) as e:
        Order.from_body(body(**{word: "live"}))
    assert "NEVER SET BY A REQUEST" in str(e.value)


def test_kite_orders_need_whole_shares_a_suffix_and_no_gtc():
    ok = Order.from_body({"broker": "kite", "symbol": "RELIANCE.NS", "side": "buy", "qty": 3, "type": "limit", "limit_price": 2400, "product": "CNC"})
    assert ok.product == "CNC"
    for bad in ({"qty": 1.5}, {"symbol": "RELIANCE"}, {"tif": "gtc"}, {"product": "XYZ"}):
        with pytest.raises(OrderError):
            Order.from_body({"broker": "kite", "symbol": "RELIANCE.NS", "side": "buy", "qty": 3, **bad})


def test_fingerprint_binds_every_field_and_the_mode():
    o = Order.from_body(body())
    fp = fingerprint(o, "paper", "A1")
    assert fp != fingerprint(o, "live", "A1") and fp != fingerprint(o, "paper", "A2")
    assert fp != fingerprint(Order.from_body(body(qty=11)), "paper", "A1")
    assert fp == fingerprint(Order.from_body(body()), "paper", "A1")


# --- mandate (pure) ---------------------------------------------------------------------------------------------------------------------------
def m(**kw):
    return md.parse({"symbols": ["AAPL"], "max_shares": 100, "max_notional": 5000, "max_gross": 10000, "max_trades_per_day": 3, **kw})


def names_failed(res):
    return [c["name"] for c in res["checks"] if not c["ok"]]


def test_mandate_passes_and_fails_each_check_alone():
    o = Order.from_body(body(qty=10))
    assert md.check(o, m(), 100.0, 0.0, 0.0, 0)["ok"]
    assert names_failed(md.check(Order.from_body(body(symbol="MSFT")), m(), 100.0, 0.0, 0.0, 0)) == ["SYMBOL ALLOWED"]
    assert names_failed(md.check(Order.from_body(body(qty=101)), m(max_notional=1e9, max_gross=1e9), 1.0, 0.0, 0.0, 0)) == ["MAX SHARES"]
    assert names_failed(md.check(Order.from_body(body(qty=60)), m(), 100.0, 0.0, 0.0, 0)) == ["MAX NOTIONAL"]
    assert names_failed(md.check(o, m(), 100.0, 9500.0, 0.0, 0)) == ["MAX GROSS EXPOSURE"]
    assert names_failed(md.check(o, m(), 100.0, 0.0, 0.0, 3)) == ["DAILY TRADES"]


def test_mandate_boundaries_are_inclusive_and_zero_means_zero():
    o = Order.from_body(body(qty=50))
    assert md.check(o, m(), 100.0, 0.0, 0.0, 2)["ok"]  # exactly the notional cap, third trade of three
    assert not md.check(o, m(max_trades_per_day=0), 100.0, 0.0, 0.0, 0)["ok"]
    assert not md.check(o, m(max_shares=0), 100.0, 0.0, 0.0, 0)["ok"]
    assert not md.check(o, md.Mandate(), 100.0, 0.0, 0.0, 0)["ok"]  # the default mandate allows nothing (no symbols)


def test_mandate_fails_closed_on_missing_data():
    o = Order.from_body(body())
    assert not md.check(o, m(), None, 0.0, 0.0, 0)["ok"]  # no price
    assert not md.check(o, m(), 100.0, None, None, 0)["ok"]  # positions unreadable


def test_gross_exposure_counts_the_position_after_the_order():
    sell = Order.from_body(body(side="sell", qty=10))
    # holding 10 (value 1000), gross 9900; selling 10 closes it: 8900 after, fine. Selling 30 flips short 20: 9900 - 1000 + 2000
    assert md.check(sell, m(max_gross=9000), 100.0, 9900.0, 10.0, 0)["ok"]
    flip = Order.from_body(body(side="sell", qty=30))
    assert names_failed(md.check(flip, m(max_gross=10500), 100.0, 9900.0, 10.0, 0)) == ["MAX GROSS EXPOSURE"]


def test_mandate_parse_rejects_bad_documents():
    for bad in ([], {"nope": 1}, {"symbols": "AAPL"}, {"symbols": ["A B"]}, {"max_shares": -1}, {"max_trades_per_day": 1.5}, {"max_notional": float("inf")}):
        with pytest.raises(OrderError):
            md.parse(bad)


# --- confirm tokens ---------------------------------------------------------------------------------------------------------------------------
def test_token_is_single_use_exact_and_expires():
    now = [0.0]
    t = ConfirmTokens(clock=lambda: now[0], ttl=60)
    tok, _ = t.issue("fp1")
    t.consume(tok, "fp1")
    with pytest.raises(OrderError, match="UNKNOWN, USED OR EXPIRED"):
        t.consume(tok, "fp1")  # second use
    tok, _ = t.issue("fp1")
    with pytest.raises(OrderError, match="DIFFERENT ORDER"):
        t.consume(tok, "fp2")  # mismatch...
    with pytest.raises(OrderError):
        t.consume(tok, "fp1")  # ...burns the token
    tok, _ = t.issue("fp1")
    now[0] = 61
    with pytest.raises(OrderError, match="EXPIRED"):
        t.consume(tok, "fp1")
    for none in (None, "", 5):
        with pytest.raises(OrderError, match="NO CONFIRM TOKEN"):
            t.consume(none, "fp1")


# --- the service: confirm, mandate, kill, mode ---------------------------------------------------------------------------------------------------------
async def test_submit_needs_a_token_issued_for_exactly_that_order(tmp_path):
    svc = await make(tmp_path)
    b = svc.brokers[PAPER]
    with pytest.raises(OrderError) as e:
        await svc.submit(body(), None)
    assert e.value.kind == "confirm_required" and not b.sent
    tok = await confirmed(svc)
    with pytest.raises(OrderError, match="DIFFERENT ORDER"):
        await svc.submit(body(qty=11), tok)  # same token, changed quantity
    assert not b.sent
    with pytest.raises(OrderError):
        await svc.submit(body(), tok)  # the mismatch burned it
    res = await svc.submit(body(), await confirmed(svc))
    assert res["mode"] == "paper" and len(b.sent) == 1 and res["client_id"].startswith("OT")
    assert len(b.sent) == 1


async def test_a_used_token_cannot_send_a_second_order(tmp_path):
    svc = await make(tmp_path)
    tok = await confirmed(svc)
    await svc.submit(body(), tok)
    with pytest.raises(OrderError) as e:
        await svc.submit(body(), tok)
    assert e.value.kind == "confirm_required" and len(svc.brokers[PAPER].sent) == 1


async def test_preview_gives_no_token_when_the_mandate_refuses(tmp_path):
    svc = await make(tmp_path)
    pre = await svc.preview(body(symbol="MSFT"))
    assert pre["token"] is None and not pre["check"]["ok"] and "SYMBOL ALLOWED" in names_failed(pre["check"])
    with pytest.raises(OrderError) as e:  # and submit refuses even with a token minted for another order
        await svc.submit(body(symbol="MSFT"), await confirmed(svc))
    assert e.value.kind in ("mandate", "confirm_required")
    assert not svc.brokers[PAPER].sent


async def test_market_order_without_a_quote_is_refused(tmp_path):
    svc = await make(tmp_path, price=no_quote)
    assert (await svc.preview(body()))["token"] is None
    assert (await svc.preview(body(type="limit", limit_price=100)))["token"]  # a limit order names its own price


async def test_daily_trade_cap_counts_sent_orders(tmp_path):
    svc = await make(tmp_path, max_trades_per_day=2)
    for _ in range(2):
        await svc.submit(body(), await confirmed(svc))
    pre = await svc.preview(body())
    assert pre["token"] is None and "DAILY TRADES" in names_failed(pre["check"])
    with pytest.raises(OrderError):
        await svc.submit(body(), "whatever")
    assert len(svc.brokers[PAPER].sent) == 2


async def test_a_broker_refusal_still_counts_and_is_ledgered(tmp_path):
    bad = FakeBroker(fail_submit=OrderError("broker_rejected", "ALPACA: insufficient buying power"))
    svc = await make(tmp_path, bad)
    with pytest.raises(OrderError) as e:
        await svc.submit(body(), await confirmed(svc))
    assert e.value.kind == "broker_rejected" and await svc.store.trades_today() == 1
    ev = [x["manifest"]["event"] for x in await ledger_events(svc)]
    assert ev == ["mandate_changed", "confirm_issued", "submitted", "failed"]


async def test_kill_switch_blocks_new_orders_and_cancels_everything(tmp_path):
    paper, live, off = FakeBroker(), FakeBroker(LIVE, "live"), FakeBroker("kite", "live", ready=False)
    svc = await make(tmp_path, paper, live, off)
    await svc.submit(body(), await confirmed(svc))
    tok = await confirmed(svc)  # a token minted before the kill must be dead after it
    res = await svc.kill()
    assert res["kill"]["on"] and paper.cancel_all_calls == 1 and live.cancel_all_calls == 1 and off.cancel_all_calls == 0
    assert res["brokers"][PAPER]["cancelled"] == 1 and res["brokers"]["kite"]["ok"] is None
    with pytest.raises(OrderError) as e:
        await svc.submit(body(), tok)
    assert e.value.kind == "kill_switch"
    with pytest.raises(OrderError) as e:
        await svc.preview(body())
    assert e.value.kind == "kill_switch"
    assert (await svc.status())["kill"]["on"]
    await svc.unkill()
    assert not (await svc.status())["kill"]["on"]
    await svc.submit(body(), await confirmed(svc))  # works again after UNKILL
    assert len(paper.sent) == 2


async def test_kill_switch_survives_a_restart(tmp_path):
    svc = await make(tmp_path)
    await svc.kill()
    again = OrderService(svc.db, svc.ledger, svc.brokers, quote)  # a new service on the same database
    with pytest.raises(OrderError) as e:
        await again.preview(body())
    assert e.value.kind == "kill_switch"


async def test_kill_reports_a_broker_that_fails_and_still_blocks(tmp_path):
    class Boom(FakeBroker):
        async def cancel_all(self):
            raise OrderError("unavailable", "ALPACA TIMEOUT")

    svc = await make(tmp_path, Boom(), FakeBroker(LIVE, "live"))
    res = await svc.kill()
    assert res["brokers"][PAPER]["ok"] is False and "TIMEOUT" in res["brokers"][PAPER]["detail"] and res["brokers"][LIVE]["ok"]
    assert (await svc.status())["kill"]["on"]


async def test_live_is_structural_off_by_default_and_needs_a_typed_phrase(tmp_path):
    live = FakeBroker(LIVE, "live")
    svc = await make(tmp_path, FakeBroker(), live)
    lb = body(broker=LIVE)
    with pytest.raises(OrderError) as e:
        await svc.preview(lb)
    assert e.value.kind == "live_off"
    with pytest.raises(OrderError, match="TYPE"):
        await svc.set_live(True, "yes")
    await svc.set_live(True, LIVE_PHRASE)
    pre = await svc.preview(lb)
    assert pre["mode"] == "live" and pre["token"]
    await svc.submit(lb, pre["token"])
    assert len(live.sent) == 1
    await svc.set_live(False, None)
    with pytest.raises(OrderError) as e:
        await svc.submit(lb, svc.tokens.issue("x")[0])
    assert e.value.kind == "live_off"


async def test_mode_comes_from_the_broker_not_the_request(tmp_path):
    """A broker id whose account reports the other mode is refused, and no request field can change what the account reports."""
    liar = FakeBroker(PAPER, "live")  # 'alpaca-paper' answering with a live account
    svc = await make(tmp_path, liar)
    with pytest.raises(OrderError) as e:
        await svc.preview(body())
    assert e.value.kind == "mode_mismatch"
    with pytest.raises(OrderError):
        await svc.preview(body(mode="paper"))
    assert not liar.sent


async def test_missing_key_gives_key_required_not_a_crash(tmp_path):
    svc = await make(tmp_path, FakeBroker(ready=False))
    with pytest.raises(OrderError) as e:
        await svc.preview(body())
    assert e.value.kind == "key_required" and "KEY REQUIRED" in str(e.value)
    row = (await svc.status())["brokers"][0]
    assert row["ready"] is False and "KEY REQUIRED" in row["message"]


async def test_replace_checks_the_mandate_and_cannot_change_symbol(tmp_path):
    svc = await make(tmp_path)
    b = svc.brokers[PAPER]
    await svc.submit(body(type="limit", limit_price=100), await confirmed(svc, type="limit", limit_price=100))
    oid = b.open[0]["id"]
    with pytest.raises(OrderError, match="SYMBOL OR THE SIDE"):
        await svc.preview(body(symbol="MSFT"), replace=oid)
    with pytest.raises(OrderError) as e:
        await svc.preview(body(), replace="nope")
    assert e.value.kind == "not_found"
    big = await svc.preview(body(qty=500, type="limit", limit_price=100), replace=oid)
    assert big["token"] is None  # a replace cannot slip past the size cap


async def test_import_fills_adds_lots_once_with_broker_and_order_id(tmp_path):
    class Filled(FakeBroker):
        async def fills_today(self):
            return [{"fill_id": "F1", "order_id": "O1", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 189.5, "at": "t", "currency": "USD"},
                    {"fill_id": "F2", "order_id": "O2", "symbol": "AAPL", "side": "sell", "qty": 4, "price": 195.0, "at": "t", "currency": "USD"}]

    svc = await make(tmp_path, Filled())
    r = await svc.import_fills(PAPER, "PAPERACCT")
    assert r["added"] == 2
    from openterm.portfolio import Portfolios

    p = await Portfolios(svc.db).get("PAPERACCT")
    (pos,) = p["positions"]
    assert pos["symbol"] == "AAPL" and pos["qty"] == 6 and pos["cost"] == 189.5 and "order O2" in pos["notes"] and "paper" in pos["notes"]
    assert (await svc.import_fills(PAPER, "PAPERACCT"))["added"] == 0  # the same fills are never added twice


# --- ledger -----------------------------------------------------------------------------------------------------------------------------------
async def test_every_order_event_is_in_the_verified_hash_chain(tmp_path):
    svc = await make(tmp_path)
    await svc.preview(body(symbol="MSFT"))  # refused by the mandate
    await svc.submit(body(), await confirmed(svc))
    with pytest.raises(OrderError):
        await svc.submit(body(), "bogus")
    await svc.cancel(PAPER, "B1")
    await svc.kill()
    await svc.unkill()
    await svc.set_live(True, LIVE_PHRASE)
    events = await ledger_events(svc)
    assert [e["manifest"]["event"] for e in events] == [
        "mandate_changed", "refused", "confirm_issued", "submitted", "accepted", "refused", "cancel", "kill_on", "kill_cancel_all", "kill_off", "live_on"]
    assert all(e["kind"] == "order" for e in events)
    sub = next(e for e in events if e["manifest"]["event"] == "submitted")
    assert sub["meta"]["order"]["symbol"] == "AAPL" and sub["model"] == "alpaca-paper:paper" and sub["ref"].startswith("OT")
    assert (await svc.ledger.audit.verify())["ok"]


async def test_ledger_never_holds_a_secret_or_a_confirm_token(tmp_path):
    from openterm import redact

    redact.register(["sk-live-SECRETVALUE123456"])
    svc = await make(tmp_path, FakeBroker(fail_submit=OrderError("broker_rejected", "ALPACA: bad key sk-live-SECRETVALUE123456")))
    tok = await confirmed(svc)
    with pytest.raises(OrderError):
        await svc.submit(body(), tok)
    dump = str(await svc.ledger.audit.entries(100))
    assert "SECRETVALUE" not in dump and tok not in dump
    redact.unregister(["sk-live-SECRETVALUE123456"])


async def test_refusals_are_ledgered_with_their_reason(tmp_path):
    svc = await make(tmp_path)
    await svc.kill()
    with pytest.raises(OrderError):
        await svc.preview(body())
    refused = [e for e in await ledger_events(svc) if e["manifest"]["event"] == "refused"]
    assert refused and refused[0]["meta"]["kind"] == "kill_switch" and "KILL SWITCH" in refused[0]["meta"]["reason"]


async def test_tampering_with_an_order_entry_breaks_the_chain(tmp_path):
    svc = await make(tmp_path)
    await svc.submit(body(), await confirmed(svc))
    assert (await svc.ledger.audit.verify())["ok"]
    await svc.db.execute("UPDATE ai_ledger SET meta=replace(meta, 'AAPL', 'TSLA') WHERE manifest LIKE '%submitted%'")
    await svc.db.commit()
    bad = await svc.ledger.audit.verify()
    assert not bad["ok"] and "CHANGED" in bad["reason"] and bad["broken_at"]


async def test_ledger_view_lists_order_events_newest_first_with_the_verify_result(tmp_path):
    svc = await make(tmp_path)
    await svc.submit(body(), await confirmed(svc))
    v = await svc.ledger_view()
    assert v["verify"]["ok"] and v["entries"][0]["event"] == "accepted" and v["entries"][0]["order"]["symbol"] == "AAPL"
    assert [e["event"] for e in v["entries"]][-1] == "mandate_changed"


async def test_removing_an_order_entry_is_detected(tmp_path):
    svc = await make(tmp_path)
    await svc.submit(body(), await confirmed(svc))
    await svc.db.execute("DELETE FROM ai_ledger WHERE manifest LIKE '%confirm_issued%'")
    await svc.db.commit()
    bad = await svc.ledger.audit.verify()
    assert not bad["ok"] and "REMOVED" in bad["reason"]


async def test_fills_are_tagged_so_a_broker_sync_never_deletes_them(tmp_path):
    from openterm.portfolio import Portfolios

    class Filled(FakeBroker):
        async def fills_today(self):
            return [{"fill_id": "F1", "order_id": "O1", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 189.5, "at": "t", "currency": "USD"}]

    svc = await make(tmp_path, Filled())
    await svc.import_fills(PAPER, "PAPERACCT")
    (pos,) = (await Portfolios(svc.db).get("PAPERACCT"))["positions"]
    assert pos["source"] == "paper"  # the SYNC only replaces lots tagged with its own broker ("kite" or "ibkr")
