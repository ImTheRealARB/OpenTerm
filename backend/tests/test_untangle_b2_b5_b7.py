"""Guards for the structural clean-ups B2 (KeyedProvider), B5 (public swr/attempt, errors.py) and B7 (one tick-source table).

These refactors must not change what users see, so the tests pin the OLD values as literals: if someone edits the shared table and a
label changes by accident, this fails.
"""

import httpx
import pytest

from openterm import alerts_engine, errors, service
from openterm.providers import keyed
from openterm.providers.alpaca import AlpacaProvider
from openterm.providers.companies_house import CompaniesHouseProvider
from openterm.providers.finnhub import FinnhubProvider
from openterm.providers.macro import FredApiProvider
from openterm.providers.marketaux import MarketauxProvider
from openterm.providers.usgov import CongressProvider, OpenFecProvider
from openterm.router import Router
from openterm.streaming import tick
from openterm.world import tickbuf


# --- B7: one tick-source table, three derived maps equal to the old literals ---------------------------------------------
def test_tick_source_maps_equal_the_old_literals():
    assert service.DataService.TICK_SOURCES == {"y": "yahoo:stream", "a": "alpaca:iex", "k": "kite:ticker", "s": "synthetic"}
    assert alerts_engine.SOURCE_NAMES == {"y": "yahoo stream", "p": "yahoo poll", "a": "alpaca iex", "k": "kite", "s": "synthetic"}
    assert tickbuf.SOURCE_LABEL == {"y": "YAHOO STREAM", "p": "YAHOO POLL", "s": "SYNTHETIC", "a": "RT IEX", "k": "RT KITE"}


def test_every_tick_source_code_has_one_row():
    codes = [s.code for s in tick.SOURCES]
    assert len(codes) == len(set(codes)) and all(len(c) == 1 for c in codes)


# --- B5: public names, one home for DataError ------------------------------------------------------------------------------
def test_swr_and_attempt_are_public_and_the_private_names_are_gone():
    assert callable(service.DataService.swr) and callable(Router.attempt)
    assert not hasattr(service.DataService, "_swr") and not hasattr(Router, "_attempt")


def test_data_error_lives_in_errors_and_service_reexports_the_same_class():
    assert service.DataError is errors.DataError
    e = errors.DataError("not_found", "x", "d", "K")
    assert (e.kind, e.detail, e.key, str(e)) == ("not_found", "d", "K", "x")


# --- B2: KeyedProvider --------------------------------------------------------------------------------------------------------
def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))


@pytest.mark.parametrize("cls", [FinnhubProvider, AlpacaProvider, FredApiProvider, CompaniesHouseProvider, MarketauxProvider,
                                 OpenFecProvider, CongressProvider])
def test_keyed_adapters_share_the_base(cls):
    assert issubclass(cls, keyed.KeyedProvider)


def test_user_visible_key_names_are_unchanged():
    # FRED says "FRED" (not its field name FRED_API_KEY): it is shown on SOURCES and in KEY REQUIRED hints.
    assert FredApiProvider.key_name == "FRED" and FredApiProvider.key_fields == ("FRED_API_KEY",)
    assert FinnhubProvider.key_name == "FINNHUB_API_KEY" and AlpacaProvider.key_name == "ALPACA_KEY_ID"


def test_fred_takes_its_key_through_set_keys_like_every_other_keyed_source():
    p = FredApiProvider(_http(), api_key="")
    assert not p.has_key and not p.supports("fred_series")
    p.set_keys({"FRED_API_KEY": "abcdefghij0123456789"})
    assert p.has_key and p.supports("fred_series")
    p.set_keys(None)
    assert not p.has_key


def test_supports_follows_the_key_only_where_it_did_before():
    assert not FinnhubProvider(_http(), api_key="").supports("news_top")
    assert CompaniesHouseProvider(_http()).supports("companies_house")  # no key, still "supported": answers KEY REQUIRED instead


@pytest.mark.asyncio
async def test_a_missing_key_raises_key_required_before_any_network_call():
    calls = []
    p = FinnhubProvider(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=[]))), api_key="")
    with pytest.raises(keyed.ProviderError) as e:
        await p._api("news", {})
    assert e.value.kind == "key_required" and str(e.value) == "FINNHUB_API_KEY is not set" and calls == []
    a = AlpacaProvider(_http())
    with pytest.raises(keyed.ProviderError) as e2:
        await a._api("v1beta1/news", {})
    assert str(e2.value) == "ALPACA_KEY_ID and ALPACA_SECRET_KEY are not set"


@pytest.mark.asyncio
async def test_status_mapping_of_the_keyed_request():
    def run(status: int, cls=FinnhubProvider):
        p = cls(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={}))), api_key="SECRETKEY123")
        return p._api("news", {})

    for status, kind in ((429, "rate_limited"), (401, "key_required"), (403, "key_required"), (404, "unavailable"), (500, "unavailable")):
        with pytest.raises(keyed.ProviderError) as e:
            await run(status)
        assert e.value.kind == kind, status
