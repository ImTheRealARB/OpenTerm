"""The source hierarchy (providers/hierarchy.py) and the router rules it relies on.

Fake providers stand in for real ones, so these tests prove the ordering rules: best source first, a source with no key or no
coverage is skipped, a source that is too shallow or rate limited hands over to the next, and the limits report takes the
deepest source that is switched on for the symbol.
"""

import httpx
import pytest

from openterm import providers
from openterm.providers.base import HISTORY, QUOTES, Provider, ProviderError
from openterm.providers.hierarchy import HIERARCHY, order_for, rank_of
from openterm.router import AllFailed, Router


class Fake(Provider):
    capabilities = frozenset({HISTORY, QUOTES})

    def __init__(self, name, *, covers=lambda s: True, error=None, intraday=None):
        super().__init__(httpx.AsyncClient())
        self.name, self.covers, self.error, self.intraday_days = name, covers, error, intraday

    def supports(self, capability, symbol=None):
        return capability in self.capabilities and (symbol is None or self.covers(symbol))

    async def history(self, symbol, range_, interval):
        if self.error:
            raise self.error
        return self.name  # the router does not look inside; a name is enough to see who answered


def test_every_entry_names_a_real_adapter_and_gives_its_reasons():
    for cap, ranks in HIERARCHY.items():
        names = [r.provider for r in ranks]
        assert len(names) == len(set(names)), f"{cap}: a provider listed twice"
        for r in ranks:
            assert r.provider in providers.ADAPTERS, f"{cap}: {r.provider} is not a registered adapter"
            for field in ("covers", "depth", "freshness", "limits", "why"):
                assert getattr(r, field).strip(), f"{cap}/{r.provider}: {field} is empty (say why it sits here)"


def test_the_ranking_puts_deeper_real_time_sources_above_yahoo():
    hist = order_for("history")
    assert hist.index("kite") < hist.index("yahoo") < hist.index("nse_archive")
    assert hist.index("binance_klines") < hist.index("yahoo")


def test_rank_of_reports_position_and_reasons():
    r = rank_of("yahoo")
    assert r["history"]["rank"] == 3 and r["history"]["of"] == len(HIERARCHY["history"]) and r["quotes"]["rank"] == 2
    assert "20 years" in r["history"]["depth"]
    assert rank_of("gdelt") == {}


async def test_first_source_that_covers_the_symbol_answers_and_the_rest_are_the_fallbacks():
    india = Fake("regional", covers=lambda s: s.endswith(".NS"))
    world = Fake("yahoo")
    router = Router({"regional": india, "yahoo": world}, {"history": ["regional", "yahoo"]})
    assert (await router.call("history", lambda p: p.history("X", "1Y", "1d"), "RELIANCE.NS"))[0] == "regional"
    assert (await router.call("history", lambda p: p.history("X", "1Y", "1d"), "AAPL"))[0] == "yahoo"  # regional never sees AAPL


async def test_a_rate_limited_source_hands_over_and_the_panel_can_say_who_failed():
    router = Router({"regional": Fake("regional", error=ProviderError("rate_limited")), "yahoo": Fake("yahoo")},
                    {"history": ["regional", "yahoo"]})
    result, failed = await router.call("history", lambda p: p.history("X", "1Y", "1d"), "RELIANCE.NS")
    assert result == "yahoo" and failed == ["regional"]


async def test_too_shallow_hands_over_without_a_circuit_breaker_strike():
    shallow = Fake("regional", error=ProviderError("depth", "UDAPI1148 Invalid date range"))
    router = Router({"regional": shallow, "yahoo": Fake("yahoo")}, {"history": ["regional", "yahoo"]})
    for _ in range(5):  # five requests that are too deep must not take the source out for a cool-down
        await router.call("history", lambda p: p.history("X", "5Y", "5m"), "RELIANCE.NS")
    assert not router.health["regional"].down and router.health["regional"].errors == 0


async def test_when_every_source_is_too_shallow_the_user_gets_the_depth_message_as_a_bad_request():
    err = ProviderError("depth", "INTERVAL 15m ONLY AVAILABLE FOR THE LAST 60 DAYS")
    router = Router({"yahoo": Fake("yahoo", error=err)}, {"history": ["yahoo"]})
    with pytest.raises(AllFailed) as e:
        await router.call("history", lambda p: p.history("AAPL", "1Y", "15m"), "AAPL")
    assert e.value.kind == "bad_request" and "ONLY AVAILABLE FOR THE LAST 60 DAYS" in str(e.value)


async def test_other_failures_are_still_provider_down_or_no_data():
    router = Router({"a": Fake("a", error=ProviderError("not_found"))}, {"history": ["a"]})
    with pytest.raises(AllFailed) as e:
        await router.call("history", lambda p: p.history("X", "1Y", "1d"), "X")
    assert e.value.kind == "not_found"
    router = Router({"a": Fake("a", error=ProviderError("unavailable", "timeout"))}, {"history": ["a"]})
    with pytest.raises(AllFailed) as e:
        await router.call("history", lambda p: p.history("X", "1Y", "1d"), "X")
    assert e.value.kind == "unavailable"


def test_history_limits_take_the_deepest_source_that_is_on_for_the_symbol():
    yahoo = Fake("yahoo", intraday={"5m": 60, "1m": 7})
    regional = Fake("regional", covers=lambda s: s.endswith(".NS"), intraday={"5m": 1400})
    undeclared = Fake("nasdaq")  # declares nothing: ignored
    router = Router({"yahoo": yahoo, "regional": regional, "nasdaq": undeclared}, {"history": ["regional", "yahoo", "nasdaq"]})
    india = router.history_limits("RELIANCE.NS")
    assert india["intraday_days"] == {"5m": 1400, "1m": 7} and india["source"] == ["regional", "yahoo"]
    us = router.history_limits("AAPL")
    assert us["intraday_days"] == {"5m": 60, "1m": 7} and us["source"] == ["yahoo"]


def test_a_source_that_is_off_does_not_count_towards_the_limits():
    off = Fake("regional", covers=lambda s: False, intraday={"5m": 1400})
    router = Router({"yahoo": Fake("yahoo", intraday={"5m": 60}), "regional": off}, {"history": ["regional", "yahoo"]})
    assert router.history_limits("RELIANCE.NS")["intraday_days"] == {"5m": 60}


async def test_yahoo_declares_and_enforces_its_intraday_depth():
    """The 60-day / 7-day rule used to live in ranges.normalize for every symbol; it is Yahoo's own limit, so it lives in Yahoo."""
    from openterm.providers.yahoo import YahooProvider

    y = YahooProvider(httpx.AsyncClient())  # never reaches the network: the check comes first
    assert y.intraday_days["5m"] == 60 and y.intraday_days["1m"] == 7
    with pytest.raises(ProviderError) as e:
        await y.history("AAPL", "1y", "15m")
    assert e.value.kind == "depth" and "ONLY AVAILABLE FOR THE LAST 60 DAYS" in str(e.value)


def test_http_a_too_deep_request_still_answers_400_with_yahoos_message(client):
    r = client.get("/api/history", params={"symbol": "AAPL", "range": "1Y", "interval": "15m"})
    assert r.status_code == 400
    body = r.json()
    assert body["kind"] == "bad_request" and "ONLY AVAILABLE FOR THE LAST 60 DAYS" in body["error"]


def test_http_history_limits_report_what_the_best_source_can_do(client):
    us = client.get("/api/history/limits", params={"symbol": "AAPL"}).json()
    assert us["intraday_days"]["5m"] == 60 and us["intraday_days"]["1m"] == 7 and us["source"] == ["yahoo"]
    india = client.get("/api/history/limits", params={"symbol": "RELIANCE.NS"}).json()
    assert india["intraday_days"]["5m"] == 60  # no Kite login in the test app: Yahoo is still the deepest source switched on


def test_http_sources_lists_where_each_provider_sits_in_the_hierarchy(client):
    rows = {p["name"]: p for p in client.get("/api/sources").json()["providers"]}
    assert rows["kite"]["hierarchy"]["history"]["rank"] == 1 and rows["yahoo"]["hierarchy"]["quotes"]["rank"] == 2
    assert rows["gdelt"]["hierarchy"] == {}


# --- the one capability-order table (DEFAULT_ORDER) ---------------------------------------------------------------------------
def test_every_provider_in_the_default_order_exists_and_declares_the_capability():
    from openterm.providers.hierarchy import DEFAULT_ORDER

    problems = []
    for cap, names in DEFAULT_ORDER.items():
        for name in names:
            cls = providers.ADAPTERS.get(name)
            if cls is None:
                problems.append(f"{cap}: {name} is not in ADAPTERS")
            elif cap not in cls.capabilities:
                problems.append(f"{cap}: {name} does not declare that capability")
    assert not problems, problems


def test_quotes_and_history_in_the_default_order_are_the_ranked_hierarchy():
    from openterm.providers.hierarchy import DEFAULT_ORDER

    for cap in HIERARCHY:
        assert DEFAULT_ORDER[cap] == order_for(cap)


def test_synthetic_goes_last_for_exactly_the_capabilities_it_declares():
    from openterm.providers.hierarchy import SYNTHETIC_CAPABILITIES, build_order
    from openterm.providers.synthetic import SyntheticProvider

    assert set(SYNTHETIC_CAPABILITIES) == set(SyntheticProvider.capabilities)
    plain, with_syn = build_order({}, False), build_order({}, True)
    assert "synthetic" not in {n for names in plain.values() for n in names}
    for cap, names in with_syn.items():
        assert names == ([*plain[cap], "synthetic"] if cap in SYNTHETIC_CAPABILITIES else plain[cap])


def test_a_config_pin_wins_and_a_pin_on_a_ranked_capability_is_logged(caplog):
    from openterm.providers.hierarchy import DEFAULT_ORDER, build_order

    with caplog.at_level("WARNING", logger="openterm"):
        order = build_order({"quotes": ["nasdaq"], "news_top": ["rss"]}, False)
    assert order["quotes"] == ["nasdaq"] and order["news_top"] == ["rss"]
    assert order["search"] == DEFAULT_ORDER["search"]  # everything else keeps the default
    assert "pins the quotes order" in caplog.text and "news_top" not in caplog.text


def test_planned_keyed_rows_have_no_adapter_and_no_key_store_entry():
    # KEYED = SOURCES rows for providers that are planned but not built; anything built or in APIKEYS is listed from elsewhere.
    from openterm.keys import KEY_SPECS

    assert providers.KEYED
    for name in providers.KEYED:
        assert name not in providers.ADAPTERS and name not in KEY_SPECS
