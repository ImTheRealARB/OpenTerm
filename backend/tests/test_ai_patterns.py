"""The `patterns` AI tool: the GP overlay rules (candlesticks, smart-money structure, Ichimoku) ported to Python. Hand-built bars pin each rule; the
port was also checked against the TypeScript on a 400-bar random series (candle codes, BOS, swings, zones and cloud values all equal)."""

import json

from openterm.ai import patterns as P
from openterm.ai import tools
from openterm.ai.context import RESULT_LIMIT


def bars(rows):
    """rows of (open, high, low, close) -> four lists."""
    return tuple(list(x) for x in zip(*rows, strict=True))


def test_bull_engulfing_after_a_decline_is_found_on_its_last_bar():
    rows = [(10.5, 10.6, 9.9, 10), (10, 10.1, 8.9, 9), (9, 9.1, 7.9, 8), (8, 8.1, 6.9, 7), (7, 7.1, 5.9, 6), (5.9, 7.3, 5.8, 7.2)]
    o, h, low, c = bars(rows)
    codes = P.candle_patterns(o, h, low, c)
    assert codes[5] == 4 and P.PATTERN_INFO[4] == ("BULL ENGULFING", 1)
    assert not any(codes[:5][i] == 4 for i in range(5))


def test_the_same_candles_without_a_prior_trend_are_not_an_engulfing():
    rows = [(10, 10.1, 9.9, 10.05)] * 4 + [(7, 7.1, 5.9, 6), (5.9, 7.3, 5.8, 7.2)]
    o, h, low, c = bars(rows)
    assert P.candle_patterns(o, h, low, c)[5] != 4  # needs c[3] < c[0]-style decline before the pattern


def test_doji_hammer_and_shooting_star():
    flat = [(10, 11, 9, 10.05)]
    assert P.candle_patterns(*bars(flat))[0] == 1  # body 0.05 of range 2: doji
    down = [(12, 12.1, 11.9, 12), (11, 11.1, 10.9, 11), (10, 10.1, 9.9, 10), (9, 9.1, 8.9, 9), (8, 8.05, 7.9, 8), (7.7, 7.95, 6.5, 7.9)]
    o, h, low, c = bars(down)
    assert P.candle_patterns(o, h, low, c)[5] == 2  # small body at the top, long lower shadow after a decline
    up = [(8, 8.1, 7.9, 8), (9, 9.1, 8.9, 9), (10, 10.1, 9.9, 10), (11, 11.1, 10.9, 11), (12, 12.1, 11.9, 12), (12.1, 13.5, 12.05, 12.3)]
    o, h, low, c = bars(up)
    assert P.candle_patterns(o, h, low, c)[5] == 3  # small body at the bottom, long upper shadow after a rise


def test_smc_finds_swings_a_break_of_structure_and_a_fair_value_gap():
    # a peak at bar 3 (high 12), then a close above it at bar 8 -> BOS up; bars 7..9 leave a gap (low[9] > high[7])
    rows = [(9, 10, 8.5, 9.5), (9.5, 11, 9, 10.5), (10.5, 11.5, 10, 11), (11, 12, 10.5, 10.8), (10.8, 11, 9.8, 10), (10, 10.5, 9.5, 10.2),
            (10.2, 10.8, 9.9, 10.6), (10.6, 11.2, 10.4, 11), (11, 12.5, 10.9, 12.4), (12.4, 13.5, 12.3, 13.2), (13.2, 13.6, 13.0, 13.4)]
    o, h, low, c = bars(rows)
    m = P.smc(o, h, low, c, k=3)
    assert m["swing"][3] == 1
    assert m["bos"][8] == 1  # close 12.4 > swing high 12
    fvg = [z for z in m["zones"] if z["kind"] == "FVG" and z["dir"] == 1]
    assert any(z["bot"] == h[7] and z["top"] == low[9] and not z["filled"] for z in fvg)  # the gap between bar 7's high and bar 9's low is still open


def test_ichimoku_state_needs_enough_bars_and_reports_the_cloud_position():
    n = 120
    c = [100 + i * 0.5 for i in range(n)]
    h = [x + 1 for x in c]
    low = [x - 1 for x in c]
    st = P.ichimoku_state(h, low, c)
    assert st and st["price"] == "ABOVE THE CLOUD" and st["tenkan_vs_kijun"] == "TENKAN ABOVE KIJUN" and st["cloud_top"] >= st["cloud_bottom"]
    assert P.ichimoku_state(h[:60], low[:60], c[:60]) is None


def history_env(n=120, falling_then_engulf=False):
    t = [1_700_000_000 + 86400 * i for i in range(n)]
    c = [100 + (i % 7) * 0.4 + i * 0.1 for i in range(n)]
    o = [x - 0.2 for x in c]
    return {"source": "fixture", "age_s": 5.0, "data": {"symbol": "T", "interval": "1d", "t": t, "o": o, "h": [x + 1 for x in c], "l": [x - 1 for x in c], "c": c}}


def test_shape_patterns_is_compact_labelled_and_honours_kind():
    out = tools.shape_patterns(history_env(), {})
    assert out["n_bars"] == 120 and out["note"].startswith("RULE-BASED PATTERNS") and out["source"] == "fixture"
    assert set(out) >= {"candles", "smc", "ichimoku"}
    assert len(out["candles"]["recent"]) <= tools.PATTERN_RECENT
    assert set(tools.shape_patterns(history_env(), {"kind": "ichimoku"})) >= {"ichimoku"} and "candles" not in tools.shape_patterns(history_env(), {"kind": "ichimoku"})
    assert "ichimoku" not in tools.shape_patterns(history_env(), {"kind": "candles"})
    assert tools.shape_patterns({"data": {"symbol": "T", "t": [], "c": []}}, {}) == {"symbol": "T", "n_bars": 0}
    assert len(json.dumps(out)) < RESULT_LIMIT


def test_registry_entry_validates_and_reaches_the_mcp_list():
    from openterm.mcp import server

    t = tools.REGISTRY["patterns"]
    assert t.method == "GET" and t.path == "/api/history" and not t.doc_only
    assert tools.validate("patterns", {"symbol": "AAPL", "kind": "smc"}) is None
    assert "kind" in tools.validate("patterns", {"symbol": "AAPL", "kind": "orders"})
    assert "patterns" in {x.name for x in server.exposed_tools()}
    assert "patterns" in {s["function"]["name"] for s in tools.openai_tools()}


async def test_tool_runs_end_to_end_on_the_fixture_history_within_the_cap(client):
    runner = tools.ToolRunner(client.app)
    try:
        res = await runner("patterns", {"symbol": "AAPL", "range": "1Y"})
    finally:
        await runner.aclose()
    assert res.ok and len(res.text) <= RESULT_LIMIT + 200
    data = json.loads(res.text.split("\n")[0]) if res.text.startswith("{") and res.text.endswith("}") else None
    if data:  # an untruncated result is JSON
        assert data["symbol"] == "AAPL" and data["note"].startswith("RULE-BASED")
