"""Pinning one data source: `?source=` on the routes, `SETTINGS SOURCE` preferences, and the cache keys that keep them apart.

A pinned source answers alone. When it cannot, the answer names it and says why; it never falls back to another source.
"""

import httpx
import pytest

from openterm import cachekeys as ck
from openterm.pin import PIN, clean
from openterm.providers.base import HISTORY, QUOTES, Provider, ProviderError
from openterm.router import AllFailed, Router
from openterm.settings_store import source_prefs, validate


class Fake(Provider):
    capabilities = frozenset({HISTORY, QUOTES})

    def __init__(self, name, *, covers=lambda s: True, error=None, caps=None):
        super().__init__(httpx.AsyncClient())
        self.name, self.covers, self.error = name, covers, error
        if caps is not None:
            self.capabilities = frozenset(caps)

    def supports(self, capability, symbol=None):
        return capability in self.capabilities and (symbol is None or self.covers(symbol))

    async def history(self, symbol, range_, interval):
        if self.error:
            raise self.error
        return self.name


def make(**over):
    ps = {"yahoo": Fake("yahoo"), "nasdaq": Fake("nasdaq"), **over}
    return Router(ps, {"history": ["yahoo", "nasdaq"], "quotes": ["yahoo", "nasdaq"]})


async def hist(router, symbol="AAPL"):
    return await router.call("history", lambda p: p.history(symbol, "1Y", "1d"), symbol)


def pinned(name):
    return PIN.set(name)


async def test_a_pinned_source_answers_alone_and_nothing_failed_before_it():
    r = make()
    tok = pinned("nasdaq")
    try:
        assert await hist(r) == ("nasdaq", [])
    finally:
        PIN.reset(tok)
    assert (await hist(r))[0] == "yahoo"  # the pin ended with the request


async def test_a_pinned_source_that_fails_is_an_error_naming_it_and_the_other_source_is_never_asked():
    asked = []

    class Spy(Fake):
        async def history(self, *a):
            asked.append(self.name)
            return await super().history(*a)

    r = make(nasdaq=Spy("nasdaq", error=ProviderError("unavailable", "HTTP 503")), yahoo=Spy("yahoo"))
    tok = pinned("nasdaq")
    try:
        with pytest.raises(AllFailed) as e:
            await hist(r)
    finally:
        PIN.reset(tok)
    assert str(e.value) == "SRC=NASDAQ: PROVIDER DOWN" and e.value.kind == "unavailable" and e.value.pinned == "nasdaq"
    assert asked == ["nasdaq"]  # no silent fallback


async def test_a_pinned_source_without_the_capability_or_coverage_says_why():
    r = make(nasdaq=Fake("nasdaq", caps={QUOTES}), yahoo=Fake("yahoo", covers=lambda s: s != "RELIANCE.NS"))
    tok = pinned("nasdaq")
    try:
        with pytest.raises(AllFailed) as e:
            await hist(r)
        assert e.value.kind == "bad_request" and "DOES NOT SERVE HISTORY" in str(e.value) and str(e.value).startswith("SRC=NASDAQ")
    finally:
        PIN.reset(tok)
    tok = pinned("yahoo")
    try:
        with pytest.raises(AllFailed) as e:
            await hist(r, "RELIANCE.NS")
        assert "DOES NOT COVER RELIANCE.NS" in str(e.value)
    finally:
        PIN.reset(tok)


async def test_a_pinned_keyed_source_without_a_key_is_key_required_with_the_key_name():
    class Keyed(Fake):
        key_name = "FOO_KEY"
        has_key = False

        def supports(self, capability, symbol=None):
            return False

    r = make(foo=Keyed("foo"))
    tok = pinned("foo")
    try:
        with pytest.raises(AllFailed) as e:
            await hist(r)
    finally:
        PIN.reset(tok)
    assert e.value.kind == "key_required" and e.value.key == "FOO_KEY" and str(e.value) == "SRC=FOO: KEY REQUIRED"


async def test_pinned_quotes_report_each_symbol_on_its_own():
    class Q(Fake):
        async def quotes(self, symbols):
            from openterm.models import Quote

            return [Quote(symbol=s, price=1.0, source=self.name, as_of=0) for s in symbols if s != "ZZZ"]

    r = make(nasdaq=Q("nasdaq", covers=lambda s: s != "NOPE"))
    tok = pinned("nasdaq")
    try:
        found, errors = await r.quotes(["AAPL", "NOPE", "ZZZ"])
    finally:
        PIN.reset(tok)
    assert set(found) == {"AAPL"} and found["AAPL"][1] == []
    assert "DOES NOT COVER NOPE" in str(errors["NOPE"]) and str(errors["ZZZ"]) == "SRC=NASDAQ: NO DATA FOR SYMBOL"


async def test_a_saved_preference_goes_first_but_the_default_order_still_backs_it_up():
    r = make(nasdaq=Fake("nasdaq", error=ProviderError("unavailable", "down")))
    assert (await hist(r))[0] == "yahoo"
    r.prefs = {"history": "nasdaq"}
    assert [p.name for p in r.candidates("history", "AAPL")] == ["nasdaq", "yahoo"]
    assert await hist(r) == ("yahoo", ["nasdaq"])  # a preference is not a pin: it falls back, and the panel says from whom


def test_cache_keys_never_share_an_answer_between_sources():
    base = ck.history("AAPL", "1Y", "1d")
    assert ck.scoped(base, None) == base and ck.scoped(base, None, {}) == base
    assert ck.scoped(base, "nasdaq") != ck.scoped(base, "yahoo") != base
    assert ck.scoped(base, "nasdaq") == f"{base}@src=nasdaq"
    assert ck.scoped(base, None, {"history": "nasdaq"}) != ck.scoped(base, None, {"history": "yahoo"})
    assert ck.scoped(base, "nasdaq", {"history": "yahoo"}) == ck.scoped(base, "nasdaq")  # a pin outranks a preference


def test_names_are_cleaned_and_settings_validate_the_preference_map():
    assert clean(" NASDAQ ") == "nasdaq" and clean("") is None and clean(None) is None
    with pytest.raises(ValueError):
        clean("a b")
    assert validate({"sources": {"history": "nasdaq"}}) == {"sources": {"history": "nasdaq"}}
    assert source_prefs({"sources": {"quotes": "yahoo"}}) == {"quotes": "yahoo"} and source_prefs(None) == {}
    from openterm.userdata import UserDataError

    for bad in ({"sources": {"nope": "yahoo"}}, {"sources": {"history": "No Way"}}, {"sources": []}):
        with pytest.raises(UserDataError):
            validate(bad)


# --- over HTTP (fixture mode: no network) --------------------------------------------------------------------------------------
def test_http_pin_does_not_borrow_the_cached_answer_of_another_source(client):
    plain = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y"})
    assert plain.status_code == 200 and plain.json()["source"].startswith("yahoo")
    yahoo = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "source": "yahoo"})
    assert yahoo.status_code == 200 and yahoo.json()["fallback_from"] == []
    # The fixture NASDAQ has no AAPL bars: pinned, that is an error naming NASDAQ, not Yahoo's cached bars.
    pin = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "source": "nasdaq"})
    assert pin.status_code == 404 and pin.json()["error"] == "SRC=NASDAQ: NO DATA FOR SYMBOL", pin.text
    assert "nasdaq" in pin.json()["detail"]
    assert client.get("/api/history", params={"symbol": "AAPL", "range": "1Y"}).json()["source"].startswith("yahoo")


def test_http_pin_that_cannot_serve_names_the_source_and_never_falls_back(client):
    r = client.get("/api/fa", params={"symbol": "AAPL", "source": "nasdaq"})
    assert r.status_code == 400 and r.json()["error"].startswith("SRC=NASDAQ") and "DOES NOT SERVE FUNDAMENTALS" in r.json()["error"]
    q = client.get("/api/quote", params={"symbols": "RELIANCE.NS", "source": "kite"}).json()["results"]["RELIANCE.NS"]
    assert q["error"].startswith("SRC=KITE")


def test_http_unknown_source_is_a_400_before_any_work(client):
    r = client.get("/api/history", params={"symbol": "AAPL", "source": "nosuch"})
    assert r.status_code == 400 and r.json()["error"].startswith("SRC=NOSUCH: UNKNOWN SOURCE")
    assert client.get("/api/history", params={"symbol": "AAPL", "source": ""}).status_code == 200  # empty = no pin


def test_http_settings_source_preference_reaches_the_router(client):
    body = {"settings": {"sources": {"history": "nasdaq"}}}
    assert client.put("/api/settings", json=body).status_code == 200
    from openterm.main import app

    assert app.state.service.router.prefs == {"history": "nasdaq"}
    r = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y"})
    assert r.status_code == 200 and r.json()["source"].startswith("yahoo") and r.json()["fallback_from"] == ["nasdaq"]
    assert client.put("/api/settings", json={"settings": {"sources": {"bogus": "x"}}}).status_code == 400
