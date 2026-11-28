"""OpenTerm Script conformance suite (spec docs/specs/PHASE_25.md section 3).

`fixtures/script_conformance.json` is ONE contract for two engines: this file runs it through the Python port, and the
frontend's vitest runs the same file through the TypeScript engine. The expected answers were worked out by hand from the spec
(small bar sets, simple numbers), not copied from an engine, so a disagreement means one of the engines has a bug.

Case format (all keys but name, source, bars and expect are optional):
  { name, source, bars: {o,h,l,c,v,t}, inputs, requests: {"SYM|TF": bars}, chart_timeframe, ts_only,
    expect: {
      plots:         {<title>: [number|null ...]}   values of the plot with that title (kind "plot")
      outputs:       [ {partial entry} ...]         entry j is matched against result.plots[j] (listed keys only);
                                                    "absent": ["color", ...] lists keys that must NOT be present
      drawings:      {labels|lines|boxes|tables: [ {partial} ...]}   same length as the result, each matched partially
      alerts:        [ {bar, message} ...]          the whole list, in order
      conditions:    {<title>: [0|1 ...]}
      compile_error: "<substring of one compile error message>"
      runtime_error: "<substring of the run's error message>",  error_bar: <bar index>
    } }
Numbers match within 1e-9 relative or 1e-12 absolute. `null` is na. Cases with "ts_only": true use lib.*, which only the
TypeScript engine has in version 1: here they must fail to compile with the lib message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openterm.script import ScriptCompileError, compile_script

CASES = json.loads((Path(__file__).parent / "fixtures" / "script_conformance.json").read_text(encoding="utf-8"))


def same_number(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    diff = abs(a - b)
    return diff <= 1e-12 or diff <= 1e-9 * max(abs(a), abs(b))


def matches(expected, actual, path: str = "") -> str | None:
    """None when `actual` fits `expected` (dicts: only the listed keys), else a sentence saying where it does not."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{path}: expected an object, got {actual!r}"
        for k, v in expected.items():
            if k not in actual:
                return f"{path}.{k}: missing in {sorted(actual)}"
            bad = matches(v, actual[k], f"{path}.{k}")
            if bad:
                return bad
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return f"{path}: expected {len(expected)} items, got {actual!r}"
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            bad = matches(e, a, f"{path}[{i}]")
            if bad:
                return bad
        return None
    if isinstance(expected, bool | str):
        return None if expected == actual else f"{path}: expected {expected!r}, got {actual!r}"
    if expected is None or isinstance(expected, int | float):
        if actual is not None and not isinstance(actual, int | float):
            return f"{path}: expected a number or null, got {actual!r}"
        return None if same_number(expected, actual) else f"{path}: expected {expected!r}, got {actual!r}"
    return f"{path}: cannot compare {expected!r}"


def check(case: dict, result: dict) -> None:
    exp = case["expect"]
    if "runtime_error" in exp:
        assert "error" in result, "expected a runtime error, the run finished"
        assert exp["runtime_error"] in result["error"]["msg"], result["error"]
        if "error_bar" in exp:
            assert result["error"]["bar"] == exp["error_bar"], result["error"]
    else:
        assert "error" not in result, result.get("error")
    for title, values in exp.get("plots", {}).items():
        found = [p for p in result["plots"] if p["kind"] == "plot" and p["title"] == title]
        assert found, f"no plot titled {title!r}"
        bad = matches(values, found[0]["values"], title)
        assert bad is None, bad
    for j, want in enumerate(exp.get("outputs", [])):
        assert j < len(result["plots"]), f"no output {j}"
        entry = result["plots"][j]
        want = dict(want)
        for key in want.pop("absent", []):
            assert key not in entry, f"output {j} should not have {key!r}: {entry}"
        bad = matches(want, entry, f"outputs[{j}]")
        assert bad is None, bad
    for kind, want in exp.get("drawings", {}).items():
        bad = matches(want, result["drawings"][kind], kind)
        assert bad is None, bad
    if "alerts" in exp:
        assert result["alerts"] == exp["alerts"]
    for title, values in exp.get("conditions", {}).items():
        found = [c for c in result["conditions"] if c["title"] == title]
        assert found, f"no condition titled {title!r}"
        assert found[0]["values"] == values


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_conformance_case(case):
    exp = case["expect"]
    if case.get("ts_only"):
        with pytest.raises(ScriptCompileError) as info:
            compile_script(case["source"])
        assert any("RUNS ONLY ON THE CHART IN V1" in e["msg"] for e in info.value.errors)
        return
    if "compile_error" in exp:
        with pytest.raises(ScriptCompileError) as info:
            compile_script(case["source"])
        msgs = [e["msg"] for e in info.value.errors]
        assert any(exp["compile_error"] in m for m in msgs), msgs
        for e in info.value.errors:
            assert e["line"] >= 1 and e["col"] >= 1
        return
    program = compile_script(case["source"])
    result = program.run(case["bars"], case.get("inputs"), case.get("requests"), case.get("chart_timeframe"))
    check(case, result)


def test_contract_is_big_enough_and_well_formed():
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names)), "case names must be unique"
    assert len(CASES) >= 45
    assert 3 <= sum(1 for c in CASES if c.get("ts_only")) <= 8
    for c in CASES:
        assert {"name", "source", "bars", "expect"} <= set(c), c["name"]
        n = len(c["bars"]["c"])
        for k in "ohlcvt":
            assert len(c["bars"][k]) == n, c["name"]
