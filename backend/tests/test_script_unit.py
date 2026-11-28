"""Unit tests for the Python port of OpenTerm Script: lexer, parser, checker and interpreter edge cases, plus a timing print."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from openterm.script import ScriptCompileError, compile_script
from openterm.script.lexer import tokenize
from openterm.script.parser import parse


def bars(c, **kw):
    n = len(c)
    return {"o": c, "h": c, "l": c, "c": c, "v": [1] * n, "t": [i * 60 for i in range(n)], **kw}


def run(src, c=(1, 2, 3), **kw):
    return compile_script('indicator("t")\n' + src).run(bars(list(c)), **kw)


def errors(src, raw=False):
    with pytest.raises(ScriptCompileError) as info:
        compile_script(src if raw else 'indicator("t")\n' + src)
    return [e["msg"] for e in info.value.errors]


def test_lexer_indent_dedent_and_tab():
    kinds = [t.kind for t in tokenize("if a\n\tb\nc\n")]
    assert kinds == ["kw", "name", "nl", "indent", "name", "nl", "dedent", "name", "nl", "eof"]


def test_lexer_inconsistent_dedent_and_bad_character():
    with pytest.raises(ScriptCompileError) as e:
        tokenize("if a\n    b\n  c\n")
    assert e.value.errors[0]["msg"] == "INCONSISTENT INDENTATION"
    with pytest.raises(ScriptCompileError) as e:
        tokenize("x = 1 $\n")
    assert "UNEXPECTED CHARACTER" in e.value.errors[0]["msg"]
    with pytest.raises(ScriptCompileError) as e:
        tokenize('x = "abc\n')
    assert e.value.errors[0]["msg"] == "UNTERMINATED TEXT"


def test_lexer_continuation_after_operator_and_inside_brackets():
    kinds = [t.kind for t in tokenize("x = 1 +\n    2\ny = f(\n  3\n)\n")]
    assert kinds.count("nl") == 2 and "indent" not in kinds


def test_parser_errors_have_positions():
    with pytest.raises(ScriptCompileError) as e:
        parse("x = \n")
    err = e.value.errors[0]
    assert err["line"] >= 1 and err["col"] >= 1


def test_ternary_is_right_associative_and_not_binds_below_comparison():
    r = run('plot(close > 2 ? 10 : close > 1 ? 20 : 30, "a")\nplot(not close == 2 ? 1 : 0, "b")\n')
    vals = {p["title"]: p["values"] for p in r["plots"]}
    assert vals["a"] == [30, 20, 10]
    assert vals["b"] == [1, 0, 1]


def test_lib_is_a_compile_error_in_python():
    assert any("LIB.SMA RUNS ONLY ON THE CHART IN V1" in m for m in errors('plot(lib.SMA(3))\n'))


def test_source_too_long():
    assert any("TOO LONG" in m for m in errors("x = 1\n" * 4000))


def test_many_errors_are_collected():
    msgs = errors("plot(a)\nplot(b)\n")
    assert len(msgs) == 2


def test_function_cannot_change_outer_variable_and_reads_it():
    assert any("OUTER" in m for m in errors("x = 1\nf() =>\n    x := 2\n    x\ny = f()\n"))
    r = run('m = 5\nf(a) => a * m\nplot(f(close), "p")\n')
    assert r["plots"][0]["values"] == [5, 10, 15]


def test_runtime_error_has_line_and_keeps_earlier_bars():
    r = run('x = bar_index == 1 ? "a" + 1 : "a"\nplot(close, "p")\n')
    assert r["error"]["bar"] == 1 and r["error"]["line"] == 2
    assert r["plots"][0]["values"] == [1, None, None]


def test_run_twice_gives_the_same_result():
    p = compile_script('indicator("t")\nvar n = 0\nn += 1\nplot(n, "n")\n')
    assert p.run(bars([1, 2, 3]))["plots"][0]["values"] == p.run(bars([1, 2, 3]))["plots"][0]["values"] == [1, 2, 3]


def test_meta_reports_title_inputs_requests_conditions():
    p = compile_script(
        'indicator("My", overlay=true)\nn = input.int(5, "N", min=1)\n'
        'plot(request("MSFT", "1D", close))\nalertcondition(close > 1, "Up", "msg")\n'
    )
    m = p.meta
    assert m["title"] == "My" and m["overlay"] is True and m["usesLib"] is False
    assert m["inputs"][0]["title"] == "N" and m["inputs"][0]["min"] == 1
    assert m["requests"] == [{"symbol": "MSFT", "timeframe": "1D"}]
    assert m["conditions"] == [{"title": "Up", "message": "msg"}]


def test_missing_request_data_is_a_runtime_error():
    r = run('plot(request("MSFT", "1D", close))\n')
    assert "NO DATA FOR REQUEST" in r["error"]["msg"]


def test_request_shorter_than_chart_is_a_runtime_error():
    r = run('plot(request("", "1m", close))\n', chart_timeframe="1h")
    assert "SHORTER" in r["error"]["msg"]


def test_resample_week_and_month_buckets():
    from openterm.script.resample import resample

    day = 86400
    # 1970-01-01 is a Thursday: Mon 1969-12-29 .. Sun 1970-01-04 is one week, the next week starts at day 4.
    cols = {k: [1.0, 2.0, 3.0] for k in "ohlcv"}
    cols["t"] = [0.0, 3 * day, 4 * day]
    w = resample(cols, "1W")
    assert w["t"] == [-3 * day, 4 * day]
    m = resample({**cols, "t": [0.0, 30 * day, 31 * day]}, "1M")
    assert m["t"] == [0.0, 31 * day]


def test_names_py_has_every_builtin_and_no_lib():
    from openterm.script.names import BY_NAME

    assert "ta.sma" in BY_NAME and not any(n.startswith("lib.") for n in BY_NAME)


def test_package_never_imports_pandas_or_numpy():
    code = "import sys, openterm.script; print(any(m.split('.')[0] in ('pandas','numpy') for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "False"


def test_ten_thousand_bars_timing(capsys):
    src = (
        'indicator("t")\nlen = input.int(14, "Length")\nr = ta.rsi(close, len)\nm = ta.sma(close, 20)\ne = ta.ema(close, 50)\n'
        'plot(r, "r")\nplot(m, "m")\nplot(e, "e")\nvar c = 0\nif ta.crossover(close, m)\n    c += 1\nplot(c, "c")\n'
    )
    n = 10_000
    c = [100 + (i % 37) * 0.5 + (i % 11) for i in range(n)]
    p = compile_script(src)
    t0 = time.perf_counter()
    r = p.run(bars(c))
    ms = (time.perf_counter() - t0) * 1000
    with capsys.disabled():
        print(f"\n[script timing] 10k bars, 4 plots, 4 ta calls: {ms:.0f} ms")
    assert "error" not in r
    assert ms < 5000
