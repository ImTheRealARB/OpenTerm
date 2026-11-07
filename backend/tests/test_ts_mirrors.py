"""Constants that are written twice, once in the backend (Python) and once in the frontend (TypeScript), must stay equal.

Why a test: the frontend cannot import Python, so each side keeps its own copy. When one copy is edited alone the app
breaks quietly (e.g. the frontend offered the chart type HEIKIN while the backend refused to save it, so `SETTINGS CHART
HEIKIN` failed on sync). This file reads the TypeScript source as plain text and compares every copy with the backend value.
Add a check here whenever you copy a backend constant into the frontend.
"""

import re
from pathlib import Path

from openterm import ranges
from openterm import settings_store as ss
from openterm.providers import news_feeds
from openterm.world import energy

SRC = Path(__file__).parents[2] / "frontend" / "src"


def _ts(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _strings(src: str, name: str) -> list[str]:
    """The double-quoted strings inside `NAME ... = [ ... ]` (an `as const` tuple or a plain array)."""
    m = re.search(rf"\b{name}\b[^=\n]*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, f"{name} not found"
    return re.findall(r'"([^"]*)"', m.group(1))


def _int(src: str, name: str) -> int:
    m = re.search(rf"\b{name}\b[^=\n]*=\s*(\d+)", src)
    assert m, f"{name} not found"
    return int(m.group(1))


def _regex(src: str, name: str) -> str:
    """The body of `NAME = /.../;` with the anchors and the `/` escapes taken off, so it compares with Python's."""
    m = re.search(rf"\b{name}\b[^=\n]*=\s*/(.*)/[a-z]*;", src)
    assert m, f"{name} not found"
    return m.group(1).removeprefix("^").removesuffix("$").replace("\\/", "/").replace("\\-", "-")


def _py_regex(rx: re.Pattern) -> str:
    return rx.pattern.removeprefix("^").removesuffix("\\Z").replace("\\-", "-")


def test_settings_lists_match_the_backend():
    ts = _ts("settings/schema.ts")
    assert _strings(ts, "MODES") == list(ss.MODES)
    assert _strings(ts, "STARTUPS") == list(ss.STARTUPS)
    assert _strings(ts, "THOUSANDS") == list(ss.THOUSANDS)
    assert _strings(ts, "DECIMALS") == list(ss.DECIMALS)
    assert _strings(ts, "AI_PROVIDERS") == list(ss.AI_PROVIDERS)
    assert _strings(_ts("settings/themes.ts"), "THEMES") == list(ss.THEMES)
    assert _int(ts, "TAPE_MAX") == ss.TAPE_MAX
    assert _int(ts, "MAX_CLOCKS") == ss.MAX_CLOCKS


def test_chart_ranges_and_types_match_the_backend():
    # schema.ts re-exports these from two tiny files, so those files are the copies to check.
    assert _strings(_ts("chart/gpRanges.ts"), "CHART_RANGES") == list(ss.CHART_RANGES)
    assert _strings(_ts("chart/chartTypes.ts"), "CHART_TYPES") == list(ss.CHART_TYPES)
    assert set(ss.CHART_RANGES) <= set(ranges.RANGES)  # every range the settings allow is one the history route accepts


def test_settings_patterns_match_the_backend():
    ts = _ts("settings/schema.ts")
    assert _regex(ts, "TAPE_SYMBOL_RE") == _py_regex(ss.TAPE_SYMBOL_RE)
    assert _regex(ts, "AI_MODEL_RE") == _py_regex(ss.AI_MODEL_RE)
    assert _regex(ts, "ZONE_RE") == _py_regex(ss.ZONE_RE)
    assert _regex(ts, "ACTION_RE") == _py_regex(ss.ACTION_RE)


def test_poll_bounds_match_the_backend():
    ts = _ts("settings/schema.ts")
    m = re.search(r"POLL_BOUNDS\s*=\s*\{(.*?)\}\s*as const", ts, re.DOTALL)
    assert m, "POLL_BOUNDS not found"
    found = {k: (int(lo), int(hi)) for k, lo, hi in re.findall(r"(\w+):\s*\[(\d+),\s*(\d+)\]", m.group(1))}
    assert found == ss.POLL_BOUNDS


def test_gp_range_days_match_ranges_py():
    ts = _ts("functions/gpArgs.ts")
    m = re.search(r"\bRANGE_DAYS\b[^=\n]*=\s*\{(.*?)\};", ts, re.DOTALL)
    assert m, "RANGE_DAYS not found"
    found = {(q or bare): int(n.replace("_", "")) for q, bare, n in re.findall(r'(?:"([^"]+)"|(\w+)):\s*([\d_]+)', m.group(1))}
    assert found, "RANGE_DAYS is empty"
    for label, days in found.items():
        assert ranges._RANGE_DAYS[ranges.RANGES[label]] == days, label


def test_news_sections_match_the_backend():
    ts = _ts("functions/newsArgs.ts")
    # The panel adds one extra word on top of the feed sections: ALL (no filter).
    assert _strings(ts, "NEWS_SECTIONS") == [s.upper() for s in news_feeds.SECTIONS] + ["ALL"]


def test_energy_series_aliases_match_the_backend():
    ts = _ts("functions/energyArgs.ts")
    m = re.search(r"\bNRG_IDS\b[^=\n]*=\s*\{(.*?)\};", ts, re.DOTALL)
    assert m, "NRG_IDS not found"
    found = dict(re.findall(r'(\w+):\s*"([^"]+)"', m.group(1)))
    assert found == {s.alias: s.id for s in energy.SERIES}
