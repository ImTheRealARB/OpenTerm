"""Phase 19 step 7: CDEP / FUND / LIQ / STBL / DEFI. Depth maths, funding annualisation (8h / 4h / 1h), basis (perp not annualised, quarterly annualised),
liquidation parse and aggregation, DefiLlama parsers (the yields pre-filter on a large built payload), Binance HTTP 451 -> OKX fallback, the UNLK probe
(DefiLlama emissions answer 402: not built) and the `/api/world/cdep|fund|liq|stbl|defi` routes on recorded answers. No network."""

import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from openterm.providers.base import ProviderError
from openterm.providers.binance_deriv import BinanceDerivProvider
from openterm.providers.defillama import DefiLlamaProvider
from openterm.providers.fixtures import fixture_transport
from openterm.providers.okx import OkxProvider
from openterm.router import Router
from openterm.world import cryptodepth as cd

FIX = Path(__file__).parent / "fixtures"


def rec(name: str):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["body"]


def run(coro):
    return asyncio.run(coro)


# --- pair / symbol arguments ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [("BTCUSDT", ("BTC", "USDT")), ("btc-usdt", ("BTC", "USDT")), ("eth/usdc", ("ETH", "USDC")), ("SOL", ("SOL", "USDT")),
                                       ("", ("BTC", "USDT")), ("ETHBTC", ("ETH", "BTC"))])
def test_parse_pair(text, want):
    assert cd.parse_pair(text) == want


def test_parse_pair_rejects_junk():
    with pytest.raises(ValueError):
        cd.parse_pair("$$$")


@pytest.mark.parametrize("text,want", [("BTC", "BTC"), ("btcusdt", "BTC"), ("BTC-USDT-SWAP", "BTC"), ("", ""), ("eth", "ETH")])
def test_parse_base(text, want):
    assert cd.parse_base(text) == want


# --- depth maths ----------------------------------------------------------------------------------------------------------------
def test_depth_cumulates_from_the_best_price_and_measures_spread_and_imbalance():
    bids = [(99.0, 2.0), (100.0, 1.0), (98.0, 3.0)]  # unsorted on purpose
    asks = [(102.0, 1.0), (101.0, 1.0)]
    s = cd.depth_summary(bids, asks, "USDT")
    assert s["best_bid"] == 100.0 and s["best_ask"] == 101.0 and s["mid"] == 100.5
    assert s["spread"] == 1.0 and s["spread_pct"] == pytest.approx(1 / 100.5 * 100)
    assert [r[0] for r in s["bids"]] == [100.0, 99.0, 98.0]
    assert s["bids"][-1][2] == 6.0 and s["bids"][-1][3] == 100 + 198 + 294
    assert s["asks"][-1][2] == 2.0 and s["asks"][-1][3] == 203.0
    assert s["imbalance_pct"] == pytest.approx((6 - 2) / 8 * 100)
    one = next(b for b in s["bands"] if b["pct"] == 1.0)  # mid +- 1 % = 99.495 .. 101.505
    assert one["bid"] == 100.0 and one["ask"] == 101.0
    assert s["usd"] is True and s["levels"] == [3, 2]


def test_depth_with_an_empty_side_is_an_error_never_a_zero_spread():
    with pytest.raises(ProviderError):
        cd.depth_summary([(1.0, 1.0)], [], "USDT")


def test_recorded_binance_and_okx_books_parse():
    bids, asks, ts = cd.parse_binance_book(rec("binance_depth_btcusdt"))
    assert len(bids) == len(asks) == 100 and ts is None
    s = cd.depth_summary(bids, asks, "USDT")
    assert s["best_ask"] > s["best_bid"] and 0 < s["spread_pct"] < 0.1
    bids, asks, ts = cd.parse_okx_book(rec("okx_books_btcusdt"))
    assert bids and asks and ts and ts > 1_700_000_000_000
    assert bids[0][0] > bids[-1][0]


def test_okx_error_answer_is_read_not_mistaken_for_data():
    with pytest.raises(ProviderError) as e:
        cd.parse_okx_book({"code": "51001", "msg": "Instrument ID does not exist", "data": []})
    assert e.value.kind == "not_found"


# --- funding and basis ----------------------------------------------------------------------------------------------------------
def test_annualisation_uses_the_interval():
    assert cd.annualise(0.0001, 8) == pytest.approx(10.95)  # 0.01 % x 3 x 365
    assert cd.annualise(0.0001, 4) == pytest.approx(21.9)
    assert cd.annualise(0.0001, 1) == pytest.approx(87.6)


def test_quarterly_basis_is_annualised_and_perp_basis_is_not():
    assert cd.quarterly_expiry("BTCUSDT_261225") == date(2026, 12, 25)
    assert cd.quarterly_expiry("BTCUSDT") is None
    assert cd.annualised_basis(1.0, date(2026, 9, 26), date(2026, 12, 25)) == pytest.approx(365 / 90)
    assert cd.annualised_basis(1.0, date(2026, 12, 25), date(2026, 12, 25)) is None
    prem = [{"symbol": "BTCUSDT", "markPrice": "101", "indexPrice": "100", "lastFundingRate": "0.0001", "nextFundingTime": 1},
            {"symbol": "BTCUSDT_261225", "markPrice": "102", "indexPrice": "100"}]
    rows = cd.binance_board(prem, {"BTCUSDT": 8.0}, date(2026, 9, 26))
    perp, q = rows
    assert perp["kind"] == "PERP" and perp["basis_pct"] == pytest.approx(1.0) and perp["ann_basis_pct"] is None and perp["ann_pct"] == pytest.approx(10.95)
    assert q["kind"] == "QUARTERLY" and q["basis_pct"] == pytest.approx(2.0) and q["days"] == 90 and q["ann_basis_pct"] == pytest.approx(2 * 365 / 90)


def test_recorded_binance_board_has_majors_and_live_quarterlies():
    rows = cd.binance_board(rec("binance_premium_all"), cd.binance_intervals(rec("binance_funding_info")), date(2026, 10, 18))
    perps = [r for r in rows if r["kind"] == "PERP"]
    assert perps[0]["base"] == "BTC" and len(perps) >= 10
    assert all(r["interval_h"] in (1.0, 4.0, 8.0) for r in perps)
    quarters = [r for r in rows if r["kind"] == "QUARTERLY"]
    assert quarters and all(r["days"] > 0 and r["ann_basis_pct"] is not None for r in quarters)


def test_binance_intervals_read_non_8h_symbols():
    iv = cd.binance_intervals(rec("binance_funding_info"))
    assert iv and set(iv.values()) <= {1.0, 2.0, 4.0, 8.0}


def test_recorded_okx_board_and_interval_from_settlement_gap():
    rows = cd.okx_board(rec("okx_funding_any"), rec("okx_mark_swap"), rec("okx_index_usdt"))
    btc = rows[0]
    assert btc["sym"] == "BTC-USDT-SWAP" and btc["interval_h"] == 8.0 and btc["mark"] and btc["index"] and btc["source"] == "okx"
    assert cd._interval_okx({"fundingTime": "14400000", "prevFundingTime": "0"}) == 8.0  # 0 is no time: default
    assert cd._interval_okx({"fundingTime": str(3_600_000 * 5), "prevFundingTime": str(3_600_000 * 4)}) == 1.0


def test_funding_history_mean_and_annualised_prints():
    h = cd.funding_history([(1, 0.0001), (2, 0.0003)], 8.0)
    assert h["mean_rate_pct"] == pytest.approx(0.02) and h["mean_ann_pct"] == pytest.approx(21.9)
    assert h["prints"][1]["ann_pct"] == pytest.approx(32.85)
    assert cd.funding_history([], 8.0)["mean_rate_pct"] is None


def test_recorded_funding_histories_parse_oldest_first():
    b = cd.parse_binance_history(rec("binance_funding_history_btcusdt"))
    o = cd.parse_okx_history(rec("okx_funding_history_btc"))
    for rows in (b, o):
        assert len(rows) >= 20 and [t for t, _ in rows] == sorted(t for t, _ in rows)


# --- liquidations ---------------------------------------------------------------------------------------------------------------------
def test_liquidation_parse_converts_contracts_and_names_the_liquidated_side():
    body = {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "details": [
        {"bkPx": "100", "sz": "2", "posSide": "long", "side": "sell", "ts": "2000"},
        {"bkPx": "110", "sz": "1", "posSide": "", "side": "buy", "ts": "1000"},
        {"bkPx": "", "sz": "1", "ts": "3000"}]}]}
    ev = cd.parse_okx_liquidations(body, 0.01, True)
    assert [e["t"] for e in ev] == [1000, 2000]
    assert ev[0]["side"] == "SHORT" and ev[0]["base"] == pytest.approx(0.01) and ev[0]["usd"] == pytest.approx(1.1)
    assert ev[1]["side"] == "LONG" and ev[1]["usd"] == pytest.approx(2.0)
    agg = cd.aggregate_liquidations(ev)
    assert agg["long"] == {"n": 1, "usd": pytest.approx(2.0)} and agg["short"]["n"] == 1
    assert agg["span_s"] == 1.0 and agg["largest"]["usd"] == pytest.approx(2.0) and agg["recent"][0]["t"] == 2000


def test_recorded_okx_liquidations_aggregate():
    inst = rec("okx_instruments_btcusdt")["data"][0]
    ev = cd.parse_okx_liquidations(rec("okx_liq_btcusdt"), float(inst["ctVal"]), inst["ctType"] == "linear")
    assert len(ev) == 100
    agg = cd.aggregate_liquidations(ev)
    assert agg["long"]["n"] + agg["short"]["n"] == 100 and agg["span_s"] > 0 and len(agg["recent"]) == 40
    assert agg["long"]["usd"] + agg["short"]["usd"] > 0


def test_empty_liquidations_aggregate_without_inventing_a_span():
    agg = cd.aggregate_liquidations([])
    assert agg["events"] == 0 and agg["largest"] is None and agg["since_ms"] is None


# --- DefiLlama -------------------------------------------------------------------------------------------------------------------------------
def test_recorded_stablecoins_by_coin_and_chain():
    s = cd.parse_stablecoins(rec("llama_stablecoins"))
    assert s["coins"][0]["symbol"] == "USDT" and s["coins"][0]["circulating"] > 1e10
    assert s["chains"][0]["usd"] >= s["chains"][-1]["usd"] and s["total_usd"] > 1e10
    assert sum(c["share_pct"] for c in s["chains"]) <= 100.0001
    usdt = s["coins"][0]
    assert usdt["peg_dev_pct"] is not None and abs(usdt["peg_dev_pct"]) < 2


def test_stablecoins_for_one_chain_and_an_unknown_chain():
    s = cd.parse_stablecoins(rec("llama_stablecoins"), "tron")
    assert s["chain"] == "tron" and all(c["value"] is not None for c in s["coins"])
    assert s["total_usd"] < cd.parse_stablecoins(rec("llama_stablecoins"))["total_usd"]
    with pytest.raises(ProviderError) as e:
        cd.parse_stablecoins(rec("llama_stablecoins"), "nochainhere")
    assert e.value.kind == "not_found"


def test_stablecoin_change_is_none_without_a_previous_value():
    body = {"peggedAssets": [{"name": "X", "symbol": "X", "pegType": "peggedUSD", "circulating": {"peggedUSD": 10}, "circulatingPrevDay": {}, "price": 1.01,
                              "chainCirculating": {"Ethereum": {"current": {"peggedUSD": 10}}}}]}
    c = cd.parse_stablecoins(body)["coins"][0]
    assert c["chg_1d"] is None and c["peg_dev_pct"] == pytest.approx(1.0)


def test_yield_prefilter_keeps_tvl_over_one_million_and_few_fields_on_a_large_payload():
    data = [{"chain": "Ethereum", "project": f"p{i % 50}", "symbol": "USDC", "tvlUsd": float(i * 100), "apy": i % 37, "pool": str(i),
             "underlyingTokens": ["0x" + "0" * 40] * 4, "predictions": {"x": 1}} for i in range(25_000)]
    pools = cd.filter_pools({"data": data})
    assert len(pools) == sum(1 for i in range(25_000) if i * 100 > 1_000_000)
    assert set(pools[0]) == {"chain", "project", "symbol", "tvl", "apy", "apy_base", "apy_reward", "stable", "il", "apy_30d", "pool"}
    assert len(json.dumps(pools)) < len(json.dumps(data)) / 2


def test_recorded_yields_select_by_chain_then_project():
    pools = cd.filter_pools(rec("llama_yields"))
    assert pools and all(p["tvl"] > cd.MIN_TVL for p in pools)
    by_chain = cd.select_pools(pools, "ethereum")
    assert by_chain["mode"] == "CHAIN" and all(p["chain"] == "Ethereum" for p in by_chain["rows"])
    apys = [p["apy"] for p in by_chain["rows"]]
    assert apys == sorted(apys, reverse=True) and len(by_chain["rows"]) <= cd.YIELD_ROWS
    lido = cd.select_pools(pools, "lido")
    assert lido["mode"] == "PROJECT" and all("lido" in p["project"] for p in lido["rows"])
    with pytest.raises(ProviderError):
        cd.select_pools(pools, "zzqqxxvv")


# --- adapters: Binance HTTP 451 -> OKX ---------------------------------------------------------------------------------------------------------
def _fixture_client(block_binance: bool) -> httpx.AsyncClient:
    fx = fixture_transport()

    async def handler(request: httpx.Request) -> httpx.Response:
        if block_binance and request.url.host.endswith("binance.com"):
            return httpx.Response(451, json={"code": 0, "msg": "Service unavailable from a restricted location"})
        return await fx.handle_async_request(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _router(block_binance: bool) -> Router:
    http = _fixture_client(block_binance)
    ps = {"binance_deriv": BinanceDerivProvider(http), "okx": OkxProvider(http)}
    return Router(ps, {"crypto_depth": ["binance_deriv", "okx"], "crypto_funding": ["binance_deriv", "okx"], "crypto_funding_detail": ["binance_deriv", "okx"]})


def test_binance_serves_depth_when_reachable():
    out, failed = run(_router(False).call("crypto_depth", lambda p: p.crypto_depth("BTC", "USDT")))
    assert out["venue"] == "BINANCE SPOT" and failed == []


def test_http_451_falls_back_to_okx_and_says_so():
    r = _router(True)
    out, failed = run(r.call("crypto_depth", lambda p: p.crypto_depth("BTC", "USDT")))
    assert out["venue"] == "OKX SPOT" and failed == ["binance_deriv"]
    assert "451" in r.health["binance_deriv"].last_error
    rows, failed = run(_router(True).call("crypto_funding", lambda p: p.crypto_funding()))
    assert rows[0]["source"] == "okx" and failed == ["binance_deriv"]
    one, _ = run(_router(True).call("crypto_funding_detail", lambda p: p.crypto_funding_detail("BTC")))
    assert one["row"]["sym"] == "BTC-USDT-SWAP" and len(one["history"]["prints"]) >= 20


def test_binance_funding_detail_on_recordings():
    out = run(BinanceDerivProvider(_fixture_client(False)).crypto_funding_detail("BTC"))
    assert out["row"]["sym"] == "BTCUSDT" and out["row"]["interval_h"] == 8.0 and out["history"]["mean_ann_pct"] is not None


def test_okx_unknown_instrument_is_not_found():
    with pytest.raises(ProviderError) as e:
        run(OkxProvider(_fixture_client(False)).crypto_depth("ZZZ", "USDT"))
    assert e.value.kind == "not_found"


def test_unlk_probe_emissions_are_paid_so_unlk_is_not_built():
    r = json.loads((FIX / "llama_emissions_probe.json").read_text(encoding="utf-8"))
    assert r["status"] == 402
    assert not hasattr(DefiLlamaProvider, "emissions")


def test_defillama_yields_adapter_never_returns_the_raw_list():
    pools = run(DefiLlamaProvider(_fixture_client(False)).yields())
    assert pools and set(pools[0]) == {"chain", "project", "symbol", "tvl", "apy", "apy_base", "apy_reward", "stable", "il", "apy_30d", "pool"}


# --- routes ---------------------------------------------------------------------------------------------------------------------------------------
def test_cdep_route(client):
    r = client.get("/api/world/cdep", params={"pair": "BTC-USDT"}).json()
    assert r["source"].startswith("binance_deriv") and r["data"]["venue"] == "BINANCE SPOT" and r["data"]["base"] == "BTC"
    assert len(r["data"]["bids"]) == 100 and r["data"]["bands"][0]["pct"] == 0.1
    assert client.get("/api/world/cdep", params={"pair": "$$$"}).status_code == 400


def test_cdep_unrecorded_pair_is_an_error_never_invented(client):
    r = client.get("/api/world/cdep", params={"pair": "DOGEUSDT"})
    assert r.status_code >= 400


def test_fund_board_and_detail_routes(client):
    b = client.get("/api/world/fund").json()["data"]
    assert b["mode"] == "BOARD" and b["venue"] == "BINANCE" and any(r["kind"] == "QUARTERLY" for r in b["rows"])
    d = client.get("/api/world/fund", params={"sym": "btc"}).json()["data"]
    assert d["mode"] == "DETAIL" and d["rows"][0]["base"] == "BTC" and d["detail"]["prints"]


def test_liq_route(client):
    d = client.get("/api/world/liq", params={"sym": "BTC"}).json()["data"]
    assert d["venue"] == "OKX" and d["events"] == 100 and "BINANCE" in d["note"]


def test_stbl_and_defi_routes(client):
    s = client.get("/api/world/stbl").json()
    assert s["source"].startswith("defillama") and s["data"]["coins"]
    d = client.get("/api/world/defi", params={"q": "ethereum"}).json()["data"]
    assert d["mode"] == "CHAIN" and d["rows"] and d["min_tvl"] == 1_000_000
    assert client.get("/api/world/defi", params={"q": "zzqqxxvv"}).status_code == 404
