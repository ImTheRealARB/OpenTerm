"""Untangle pass B (Phase 1 of SUPER_PROMPT_NEXT): B6 alert-fired path, B8 bar pacing, B9 identifier regexes, B12 cache keys.

Behaviour-preserving refactor: the first half of each section pins what the code did BEFORE the move (these assertions were
written and run against the old code), the rest tests the new single home. No network, no real sleeping.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from openterm.errors import DataError

T0 = 1_800_000_000.0


# ================================================================== B6: one "alert fired" path
def test_trigger_routes_deliver_in_the_browsers_words_and_never_broadcast(client, monkeypatch):
    """The HTTP trigger routes (used by a browser) send "checked in the browser" text and push NO `A` frame: the browser that
    fired the alert already knows. Only the server engine broadcasts (its tabs must refresh)."""
    sent: list[tuple] = []
    monkeypatch.setattr("openterm.alert_channels.spawn",
                        lambda app, kind, ref, subject, text, extra=None, channels=None: sent.append((kind, ref, subject, text, extra, channels)))
    frames: list = []
    monkeypatch.setattr(client.app.state.hub, "broadcast", lambda frame: frames.append(frame))
    a = client.post("/api/alerts", json={"symbol": "SYN0007", "op": ">", "unit": "price", "value": 1e9}).json()["id"]
    n = client.post("/api/newsalerts", json={"word": "RECALL", "symbol": None}).json()["id"]
    assert client.post(f"/api/alerts/{a}/trigger", json={"price": 5, "at": T0}).json()["changed"] is True
    assert client.post(f"/api/newsalerts/{n}/trigger", json={"headline": "Big recall", "url": "http://x", "at": T0}).json()["changed"] is True
    assert [s[0] for s in sent] == ["alert", "news"]
    assert sent[0][1] == a and sent[0][4] == {"kind": "alert", "symbol": "SYN0007"} and "in the browser" in sent[0][3]
    assert sent[1][1] == n and sent[1][4] == {"kind": "news", "word": "RECALL"} and "Big recall" in sent[1][3]
    assert not [f for f in frames if f and f[0] == "A"]  # no alert frame from a route


# ================================================================== B8: bar pacing
class _Svc:
    """history() that fails `fail_first` times with a DataError kind, then answers."""

    def __init__(self, kind="unavailable", fail_first=0):
        self.kind, self.fail_first, self.calls = kind, fail_first, 0

    async def history(self, symbol, range_, interval):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise DataError(self.kind, "boom")
        return {"data": {"c": [1.0]}, "symbol": symbol, "range": range_, "interval": interval}


def _req(svc):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(service=svc)))


@pytest.fixture
def sleeps(monkeypatch):
    """Records every asyncio.sleep the pacing asks for, without waiting."""
    asked: list[float] = []
    real = asyncio.sleep

    async def fake(s, *a, **k):
        asked.append(s)
        await real(0)

    monkeypatch.setattr(asyncio, "sleep", fake)
    return asked


async def test_bars_retries_an_unavailable_answer_three_times_with_a_pause(sleeps):
    from openterm import quant_routes as qr

    svc = _Svc(fail_first=3)
    ok, bad = await qr._bars(_req(svc), ["SYN0001"], "1Y")
    assert svc.calls == 4 and list(ok) == ["SYN0001"] and bad == {}
    assert sleeps == [0.6, 0.6, 0.6]  # synthetic symbols are not paced; only the retry pauses sleep


async def test_bars_gives_up_after_the_fourth_unavailable_answer(sleeps):
    from openterm import quant_routes as qr

    svc = _Svc(fail_first=99)
    with pytest.raises(DataError) as e:
        await qr._bars(_req(svc), ["SYN0001"], "1Y")
    assert svc.calls == 4 and e.value.kind == "unavailable" and str(e.value) == "SYN0001: boom"


async def test_bars_does_not_retry_other_errors_and_tolerate_collects_them(sleeps):
    from openterm import quant_routes as qr

    svc = _Svc(kind="not_found", fail_first=99)
    with pytest.raises(DataError) as e:
        await qr._bars(_req(svc), ["SYN0001"], "1Y")
    assert svc.calls == 1 and e.value.kind == "not_found" and sleeps == []
    ok, bad = await qr._bars(_req(_Svc(kind="not_found", fail_first=99)), ["SYN0001"], "1Y", tolerate=True)
    assert ok == {} and list(bad) == ["SYN0001"]


async def test_bars_spaces_real_symbols_after_the_first_five(sleeps):
    """Real symbol number i (from 0) waits (i - 5) * 0.26 s, so the first six start at once and a long list stays under Yahoo's 4 requests/s."""
    from openterm import quant_routes as qr

    syms = [f"S{n}" for n in range(8)]
    await qr._bars(_req(_Svc()), syms, "1Y")
    assert sorted(s for s in sleeps if s) == pytest.approx([0.26, 0.52])  # indexes 6 and 7 of 0..7 wait; index 5 waits 0


# ================================================================== B9: one identifier module
# The accepted / rejected sets, written against the old regexes. Note `$` (not `\Z`) in the AI ones: "AAPL\n" passes today.
SYMBOL_OK = ["AAPL", "aapl", "^GSPC", "BRK-B", "EURUSD=X", "RELIANCE.NS", "A" * 12, "AAPL\n"]
SYMBOL_BAD = ["", "A" * 13, "AA PL", "AA;PL", "AA/PL", "AAPL\nX"]


@pytest.mark.parametrize("s", SYMBOL_OK)
def test_ai_symbol_accepts(s):
    from openterm import idents

    assert idents.AI_SYMBOL_RE.match(s)


@pytest.mark.parametrize("s", SYMBOL_BAD)
def test_ai_symbol_rejects(s):
    from openterm import idents

    assert not idents.AI_SYMBOL_RE.match(s)


def test_the_three_ai_modules_share_one_symbol_pattern():
    """ai/routes (and routes_filing through it), ai/routes_run and ai/store used to carry identical copies."""
    from openterm import idents
    from openterm.ai import routes, routes_filing, routes_run, store

    assert routes.AI_SYMBOL_RE is idents.AI_SYMBOL_RE
    assert routes_filing.AI_SYMBOL_RE is idents.AI_SYMBOL_RE
    assert routes_run.AI_SYMBOL_RE is idents.AI_SYMBOL_RE
    assert store.AI_SYMBOL_RE is idents.AI_SYMBOL_RE


@pytest.mark.parametrize("s,ok", [("AAPL", True), ("^GSPC", True), ("TCS.NS", True), ("A" * 24, True), ("A" * 25, False), ("aapl", False),
                                  ("", False), ("AA PL", False), ("AAPL\n", False), (".X", False), ("BRK-B", True), ("M&M.NS", True)])
def test_stored_symbol_pattern_is_unchanged(s, ok):
    """User-data symbols (portfolio, drawings, news alerts, world routes): upper case only, up to 24 characters, `\\Z` anchored."""
    from openterm import idents

    assert bool(idents.STORED_SYMBOL_RE.match(s)) is ok


@pytest.mark.parametrize("s,ok", [("MAIN", True), ("my-layout_1", False), ("A" * 32, True), ("A" * 33, False), ("1X", True), ("-X", False), ("X\n", False)])
def test_stored_name_pattern_is_unchanged(s, ok):
    from openterm import idents

    assert bool(idents.STORED_NAME_RE.match(s)) is ok


def test_run_id_is_twelve_lowercase_hex_characters():
    from openterm import idents

    assert idents.RUN_ID_RE.match("0123456789ab") and not idents.RUN_ID_RE.match("0123456789AB") and not idents.RUN_ID_RE.match("0123456789a")


# ================================================================== B12: one cache-key namespace
def test_history_populates_the_key_the_helper_builds(client):
    """Pins the live key format (`h:<SYMBOL>:<range, lower case>:<interval>`) the service has always used, through a real request."""
    svc = client.app.state.service
    assert client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "1d"}).status_code == 200
    assert any(k == "h:AAPL:1y:1d" for k in svc.cache.mem), list(svc.cache.mem)  # the range is normalised to lower case


def test_cache_key_builders_keep_their_format():
    from openterm import cachekeys as ck

    assert ck.quote("AAPL") == "q:AAPL"
    assert ck.history("AAPL", "1Y", "1d") == "h:AAPL:1Y:1d"
    assert ck.history("RELIANCE.NS", "1Y", "1d", gated=["kite"]) == "h:RELIANCE.NS:1Y:1d:k"  # first letter of each key-gated source
    assert ck.history("X", "1Y", "1d", gated=["kite", "alpaca"]) == "h:X:1Y:1d:k:a"
    assert ck.quant("fundsectors", "SPY") == "q:fundsectors:SPY" and ck.quant("kenfrench") == "q:kenfrench"


def test_cached_quote_reads_what_apply_tick_writes(client):
    """main.py's previous-close reader no longer builds a "q:" key by hand: DataService.cached_quote owns it."""
    from openterm import cachekeys as ck

    svc = client.app.state.service
    assert svc.cached_quote("ZZZZ") is None
    svc.cache.mem[ck.quote("ZZZZ")] = ({"data": {"price": 1.0, "prev_close": 0.9}, "fallback_from": []}, time.time())
    assert svc.cached_quote("ZZZZ")["prev_close"] == 0.9
