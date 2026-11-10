"""Chart-pattern detection for the AI `patterns` tool: candlestick patterns, smart-money structure and the Ichimoku cloud state.

A line-for-line port of the GP overlay code in `frontend/src/chart/patterns.ts` (candlePatterns, smc) and `ichimoku` in `frontend/src/chart/studies.ts`,
so the AI names the same marks the chart draws. These are PATTERNS read off price rules, not signals or forecasts. Pure functions on lists of floats.
Keep this file and the TypeScript in step: `tests/test_ai_patterns.py` pins the thresholds with hand-built bars.
"""

from __future__ import annotations

# code -> (name, short, direction): 1 bullish, -1 bearish, 0 neutral. Same table as PATTERN_INFO in patterns.ts.
PATTERN_INFO: dict[int, tuple[str, int]] = {
    1: ("DOJI", 0), 2: ("HAMMER", 1), 3: ("SHOOTING STAR", -1), 4: ("BULL ENGULFING", 1), 5: ("BEAR ENGULFING", -1),
    6: ("MORNING STAR", 1), 7: ("EVENING STAR", -1), 8: ("BULL HARAMI", 1), 9: ("BEAR HARAMI", -1),
}


def candle_patterns(o: list[float], h: list[float], low: list[float], c: list[float]) -> list[int]:
    """One code per bar (0 = none), see PATTERN_INFO. Reversal patterns need a trend before them: the close of the bar before the pattern is below
    (above) the close three bars earlier for bullish (bearish) ones. The pattern is stamped on its LAST bar."""
    n = len(c)
    out = [0] * n

    def down(i0: int) -> bool:
        return i0 >= 4 and c[i0 - 1] < c[i0 - 4]

    def up(i0: int) -> bool:
        return i0 >= 4 and c[i0 - 1] > c[i0 - 4]

    def body(i: int) -> float:
        return abs(c[i] - o[i])

    def rng(i: int) -> float:
        return h[i] - low[i]

    def green(i: int) -> bool:
        return c[i] > o[i]

    def red(i: int) -> bool:
        return c[i] < o[i]

    def long_body(i: int) -> bool:
        return rng(i) > 0 and body(i) >= 0.6 * rng(i)

    for i in range(n):
        code = 0
        if i >= 2:
            a, b = i - 2, i - 1
            b_mid = (o[b] + c[b]) / 2
            if down(a) and red(a) and long_body(a) and body(b) <= 0.3 * body(a) and b_mid <= c[a] and green(i) and c[i] > (o[a] + c[a]) / 2:
                code = 6
            elif up(a) and green(a) and long_body(a) and body(b) <= 0.3 * body(a) and b_mid >= c[a] and red(i) and c[i] < (o[a] + c[a]) / 2:
                code = 7
        if not code and i >= 1:
            p = i - 1
            if down(p) and red(p) and green(i) and o[i] <= c[p] and c[i] >= o[p] and body(i) > body(p):
                code = 4
            elif up(p) and green(p) and red(i) and o[i] >= c[p] and c[i] <= o[p] and body(i) > body(p):
                code = 5
            elif down(p) and red(p) and long_body(p) and green(i) and o[i] >= c[p] and c[i] <= o[p] and body(i) < body(p):
                code = 8
            elif up(p) and green(p) and long_body(p) and red(i) and o[i] <= c[p] and c[i] >= o[p] and body(i) < body(p):
                code = 9
        if not code and rng(i) > 0:
            r = rng(i)
            upper = h[i] - max(o[i], c[i])
            lower = min(o[i], c[i]) - low[i]
            b = body(i)
            if b >= 0.1 * r and lower >= 2 * b and upper <= 0.1 * r and down(i):
                code = 2
            elif b >= 0.1 * r and upper >= 2 * b and lower <= 0.1 * r and up(i):
                code = 3
            elif b <= 0.1 * r:
                code = 1
        out[i] = code
    return out


def smc(o: list[float], h: list[float], low: list[float], c: list[float], k: int = 3) -> dict:
    """Swings (stamped on the swing bar, known k bars later), break of structure (+-1) / change of character (+-2) on the breaking bar, and fair
    value gap / order block zones: {swing, bos, zones: [{kind, dir, i0, i1, top, bot, filled}]}."""
    n = len(c)
    swing = [0] * n
    bos = [0] * n
    zones: list[dict] = []
    for i in range(k, n - k):
        hi = lo = True
        for j in range(1, k + 1):
            if not (h[i] > h[i - j]) or not (h[i] >= h[i + j]):
                hi = False
            if not (low[i] < low[i - j]) or not (low[i] <= low[i + j]):
                lo = False
        swing[i] = 1 if hi else (-1 if lo else 0)
    last_high: dict | None = None
    last_low: dict | None = None
    trend = 0
    for i in range(n):
        s = i - k
        if s >= 0 and swing[s] == 1:
            last_high = {"idx": s, "val": h[s], "broken": False}
        elif s >= 0 and swing[s] == -1:
            last_low = {"idx": s, "val": low[s], "broken": False}
        if last_high and not last_high["broken"] and c[i] > last_high["val"]:
            bos[i] = 2 if trend == -1 else 1
            trend = 1
            last_high["broken"] = True
            start = last_low["idx"] if last_low else 0
            for j in range(i - 1, start - 1, -1):
                if c[j] < o[j]:
                    z = {"kind": "OB", "dir": 1, "i0": j, "i1": n - 1, "top": h[j], "bot": low[j], "filled": False}
                    zones.append(z)
                    for t in range(i + 1, n):
                        if c[t] < z["bot"]:
                            z["filled"], z["i1"] = True, t
                            break
                    break
        elif last_low and not last_low["broken"] and c[i] < last_low["val"]:
            bos[i] = -2 if trend == 1 else -1
            trend = -1
            last_low["broken"] = True
            start = last_high["idx"] if last_high else 0
            for j in range(i - 1, start - 1, -1):
                if c[j] > o[j]:
                    z = {"kind": "OB", "dir": -1, "i0": j, "i1": n - 1, "top": h[j], "bot": low[j], "filled": False}
                    zones.append(z)
                    for t in range(i + 1, n):
                        if c[t] > z["top"]:
                            z["filled"], z["i1"] = True, t
                            break
                    break
    for i in range(2, n):
        if low[i] > h[i - 2]:
            z = {"kind": "FVG", "dir": 1, "i0": i - 1, "i1": n - 1, "top": low[i], "bot": h[i - 2], "filled": False}
            for t in range(i + 1, n):
                if low[t] <= z["bot"]:
                    z["filled"], z["i1"] = True, t
                    break
            zones.append(z)
        elif h[i] < low[i - 2]:
            z = {"kind": "FVG", "dir": -1, "i0": i - 1, "i1": n - 1, "top": low[i - 2], "bot": h[i], "filled": False}
            for t in range(i + 1, n):
                if h[t] >= z["top"]:
                    z["filled"], z["i1"] = True, t
                    break
            zones.append(z)
    return {"swing": swing, "bos": bos, "zones": zones}


def ichimoku_state(h: list[float], low: list[float], c: list[float], tn: int = 9, kn: int = 26, bn: int = 52, shift: int = 26) -> dict | None:
    """The cloud at the LAST bar, from the same maths as `ichimoku` in studies.ts (spans are drawn `shift` bars ahead, so the cloud under the last bar
    was computed `shift` bars ago). None when there are not enough bars for it."""
    n = len(c)

    def mid(i: int, w: int) -> float | None:
        return (max(h[i - w + 1:i + 1]) + min(low[i - w + 1:i + 1])) / 2 if i >= w - 1 else None

    if n - 1 - shift < max(kn, bn) - 1:
        return None
    src = n - 1 - shift
    tenkan, kijun = mid(n - 1, tn), mid(n - 1, kn)
    a_t, a_k, b = mid(src, tn), mid(src, kn), mid(src, bn)
    if None in (tenkan, kijun, a_t, a_k, b):
        return None
    span_a = (a_t + a_k) / 2
    top, bot = max(span_a, b), min(span_a, b)
    px = c[-1]
    pos = "ABOVE THE CLOUD" if px > top else ("BELOW THE CLOUD" if px < bot else "INSIDE THE CLOUD")
    return {"tenkan": tenkan, "kijun": kijun, "span_a": span_a, "span_b": b, "cloud_top": top, "cloud_bottom": bot, "price": pos,
            "tenkan_vs_kijun": "TENKAN ABOVE KIJUN" if tenkan > kijun else ("TENKAN BELOW KIJUN" if tenkan < kijun else "TENKAN EQUALS KIJUN")}
