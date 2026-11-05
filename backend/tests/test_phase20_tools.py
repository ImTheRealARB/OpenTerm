"""Phase 20 step 4: the wider read-only AI tool surface (desk tools). Pure maths checked directly; routes checked against the fixtures."""

import pytest

from openterm.ai import tools

DESK = ["indicators", "option_price", "option_payoff", "etf", "holders", "insiders", "calendar", "pred", "energy", "crypto_funding", "crypto_depth", "rigor"]
FORBIDDEN = ("order", "kite", "gtt", "margin", "holding", "trade", "buy", "sell", "kill")

# One valid argument set per routed tool (fixture-served).
ARGS = {
    "indicators": {"symbol": "AAPL", "range": "1Y"},
    "option_price": {"symbol": "AAPL", "k": 270, "type": "C", "exp": "2026-12-18", "iv": 30},
    "option_payoff": {"symbol": "AAPL", "legs": "+1C270@5,-1C290@2", "exp": "2026-12-18", "iv": 30},
    "etf": {"symbol": "SPY"},
    "holders": {"symbol": "AAPL"},
    "insiders": {"symbol": "AAPL"},
    "calendar": {"kind": "earnings", "date": "2026-10-15"},
    "pred": {"q": "fed"},
    "energy": {},
    "crypto_funding": {"sym": "BTC"},
    "crypto_depth": {"pair": "BTCUSDT"},
}


def test_desk_tools_exist_are_short_and_have_no_order_like_names_or_paths():
    for name in DESK:
        t = tools.REGISTRY[name]
        assert t.desk_only and len(t.description) <= 240, name
        assert not any(w in name.lower() or w in t.path.lower() for w in FORBIDDEN), name
        assert t.method == "GET" or t.local is not None, name  # every desk tool only reads


def test_plain_chat_does_not_get_the_desk_tools_but_a_role_can_ask_for_them():
    chat = {s["function"]["name"] for s in tools.openai_tools()}
    assert not chat & set(DESK)
    assert {s["function"]["name"] for s in tools.openai_tools(["indicators", "rigor"])} == {"indicators", "rigor"}


def test_arguments_are_validated():
    assert tools.validate("indicators", {"symbol": "AAPL"}) is None
    assert "symbol" in tools.validate("indicators", {})
    assert "type" in tools.validate("option_price", {"symbol": "AAPL", "k": 1, "type": "X"})
    assert tools.validate("rigor", {"parts": [1, 2], "total": 3}) is None
    assert "parts" in tools.validate("rigor", {"parts": "1,2", "total": 3})
    assert "kind" in tools.validate("calendar", {"kind": "orders"})


# ---------------------------------------------------------------- indicators (hand-checkable series)


def bars(closes):
    n = len(closes)
    return {"data": {"symbol": "T", "interval": "1d", "t": [1_700_000_000 + 86400 * i for i in range(n)], "c": closes,
                     "h": [c + 1 for c in closes], "l": [c - 1 for c in closes]}}


def test_sma_ema_rsi_on_known_series():
    out = tools.shape_indicators(bars([float(i) for i in range(1, 61)]), {})  # 1..60
    assert out["n_bars"] == 60 and out["close"] == 60.0
    assert out["sma"]["20"] == 50.5 and out["sma"]["50"] == 35.5 and out["sma"]["200"] is None  # too few bars: null, not invented
    assert out["rsi14"] == 100.0  # only gains
    assert out["atr14"] == pytest.approx(2.0, abs=0.01)  # each bar's range is 2 (high +1, low -1) and closes step by 1 -> TR = 2
    assert out["bollinger20"]["mid"] == 50.5 and out["bollinger20"]["upper"] > out["bollinger20"]["lower"]
    assert out["macd"]["line"] > 0


def test_flat_series_has_zero_width_bands_and_flat_macd():
    out = tools.shape_indicators(bars([10.0] * 40), {})
    assert out["bollinger20"] == {"mid": 10.0, "upper": 10.0, "lower": 10.0}
    assert out["macd"]["line"] == 0 and out["ema"]["12"] == 10.0


def test_a_short_history_leaves_the_long_indicators_null_and_empty_history_says_so():
    short = tools.shape_indicators(bars([1.0, 2.0, 3.0]), {})
    assert short["rsi14"] is None and short["macd"] is None and short["bollinger20"] is None and short["atr14"] is None
    assert tools.shape_indicators({"data": {"symbol": "T", "t": [], "c": []}}, {}) == {"symbol": "T", "n_bars": 0}


# ---------------------------------------------------------------- rigor


def test_rigor_reconciles_within_tolerance_and_flags_unit_mixes():
    ok = tools._rigor({"parts": [60, 30, 10], "total": 100}, {})
    assert ok["reconciles"] and ok["difference"] == 0 and not ok["possible_unit_mix"]
    off = tools._rigor({"parts": [60, 30, 12], "total": 100}, {})
    assert not off["reconciles"] and off["difference_pct"] == 2.0
    assert tools._rigor({"parts": [60, 30, 12], "total": 100, "tolerance_pct": 3}, {})["reconciles"]
    mix = tools._rigor({"parts": [1200, 5_000_000], "total": 5_001_200}, {})
    assert mix["reconciles"] and mix["possible_unit_mix"]
    assert tools._rigor({"parts": [-5, 10], "total": 5}, {})["negative_parts"] == 1
    assert tools._rigor({"parts": [1], "total": 0}, {})["reconciles"] is False


async def test_rigor_runs_as_a_local_tool_without_a_route():
    r = await tools.ToolRunner(app=None).call("rigor", {"parts": [1, 2], "total": 3})
    assert r.ok and '"reconciles":true' in r.text and r.source == "local:rigor"


# ---------------------------------------------------------------- the routed tools, served by the fixtures


@pytest.mark.parametrize("name", sorted(ARGS))
def test_each_routed_tool_reaches_a_route_and_its_shaper_accepts_the_answer(client, name):
    t = tools.REGISTRY[name]
    assert tools.validate(name, ARGS[name]) is None
    spec = {"path": t.path, **t.build(ARGS[name])}
    r = client.get(spec["path"], params=spec.get("params"))
    assert r.status_code == 200, (name, r.status_code, r.text[:200])
    shaped = t.shape(r.json(), ARGS[name])
    assert shaped not in (None, {}, []), name
    assert len(str(shaped)) < 20_000  # shaped small enough for the model's context budget (the runner truncates further)
