"""FMP as the last, keyed backup for MOV (2026-11-28): parsing the three recorded lists, its place in the order and the
key hint when no key is set. Fixtures are REAL recordings made with the owner's free key (scripts/record_fmp_movers.py)."""

from __future__ import annotations

import json

import httpx
import pytest

from openterm.providers.base import MOVERS, ProviderError
from openterm.providers.fixtures import FIXTURES, fixture_transport
from openterm.providers.fmp import MOVER_PATHS, FmpProvider, movers_from_lists
from openterm.providers.hierarchy import DEFAULT_ORDER
from openterm.router import AllFailed, Router

DOCSHAPE_KEY = "docshape-test"  # the fixture FMP host answers only keys that start with "docshape"


def recorded(tab: str) -> list:
    return json.loads((FIXTURES / f"fmp_real_movers_{tab.lower()}.json").read_text(encoding="utf-8"))["body"]


def test_fmp_is_last_in_the_movers_order_and_serves_the_capability():
    assert DEFAULT_ORDER["movers"][-1] == "fmp"
    assert MOVERS in FmpProvider.capabilities


def test_parse_maps_the_recorded_lists_and_leaves_what_fmp_does_not_send_empty():
    m = movers_from_lists({t: recorded(t) for t in MOVER_PATHS}, "fmp", 1.0)
    assert set(m.tables) == {"GAINERS", "LOSERS", "ACTIVE"}  # no $-volume or Nasdaq-100 list: MOV says NOT IN THIS SOURCE
    assert all(len(rows) == 12 for rows in m.tables.values())
    assert all((r.change_pct or 0) > 0 for r in m.tables["GAINERS"])
    assert all((r.change_pct or 0) < 0 for r in m.tables["LOSERS"])
    first = m.tables["GAINERS"][0]
    assert first.symbol == recorded("GAINERS")[0]["symbol"] and first.price == recorded("GAINERS")[0]["price"]
    # FMP gives no volume and no time: both stay empty (never guessed), so MOV labels the time FETCHED.
    assert all(r.volume is None for rows in m.tables.values() for r in rows)
    assert m.as_of_text is None and m.market_time is None and m.table_as_of == {} and m.source == "fmp"


def test_parse_fails_loudly_on_a_missing_list_or_no_rows():
    ok = {t: recorded(t) for t in MOVER_PATHS}
    with pytest.raises(ProviderError):
        movers_from_lists({**ok, "LOSERS": {"Error Message": "x"}}, "fmp", 1.0)  # not a list
    with pytest.raises(ProviderError):
        movers_from_lists({tab: [] for tab in MOVER_PATHS}, "fmp", 1.0)  # three empty lists


async def test_adapter_reads_the_three_endpoints_through_the_fixture_host():
    async with httpx.AsyncClient(transport=fixture_transport()) as http:
        p = FmpProvider(http, fixture=True)
        p.set_keys({"FMP_API_KEY": DOCSHAPE_KEY})
        m = await p.movers()
    assert set(m.tables) == {"GAINERS", "LOSERS", "ACTIVE"} and m.tables["ACTIVE"]


async def test_without_a_key_fmp_is_skipped_and_named_as_the_unlock():
    async with httpx.AsyncClient() as http:
        fmp = FmpProvider(http)  # no key
        assert not fmp.supports(MOVERS)
        router = Router({"fmp": fmp}, {"movers": ["fmp"]})
        with pytest.raises(AllFailed) as e:
            await router.call("movers", lambda p: p.movers())
    assert e.value.unlock == ["FMP_API_KEY"]
