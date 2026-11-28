"""OpenTerm Script, Python port (spec: docs/specs/PHASE_25.md).

    program = compile_script(source)            # raises ScriptCompileError (.errors = [{msg, line, col}, ...])
    result = program.run(bars, inputs=None, requests=None, chart_timeframe=None)

`bars` is a dict of equally long lists: o, h, l, c (required) and v, t (optional; t = bar open time in epoch seconds).
`inputs` maps an input's title to the value the user chose. `requests` maps "SYMBOL|TIMEFRAME" to the bars of that
symbol, for `request(...)` calls on another symbol. The result has the same shape as the TypeScript engine's, with plain
lists and `None` where the TypeScript side has NaN. This package is pure standard library: it never imports pandas or numpy.

`lib.*` (the chart's indicator catalog) exists only in the TypeScript engine in version 1; here it is a compile error.
"""

from __future__ import annotations

from . import checker, interp, parser
from .errors import ScriptCompileError, ScriptRuntimeError, err
from .names import LIMITS

__all__ = ["Program", "ScriptCompileError", "ScriptRuntimeError", "compile_script"]


class Program:
    """A checked script. It can be run any number of times; every run starts from a clean state."""

    def __init__(self, stmts: list, meta: dict):
        self._stmts = stmts
        self.meta = meta

    def run(self, bars: dict, inputs: dict | None = None, requests: dict | None = None, chart_timeframe: str | None = None) -> dict:
        cols = interp.normalise_cols(bars)
        return interp.execute(self._stmts, cols, inputs, requests, chart_timeframe)


def compile_script(src: str) -> Program:
    """Parse and check `src`. Raises ScriptCompileError when the script is not valid."""
    if len(src) > LIMITS["sourceChars"]:
        raise ScriptCompileError([err(f"SCRIPT IS TOO LONG (MAX {LIMITS['sourceChars']} CHARACTERS)", 1, 1)])
    try:
        stmts = parser.parse(src)
        errors = checker.check(stmts)
        if errors:
            raise ScriptCompileError(errors)
        built = interp.validate(stmts)
    except RecursionError:
        raise ScriptCompileError([err("EXPRESSION IS TOO DEEP", 1, 1)]) from None
    seen: set[tuple[str, str]] = set()
    requests = []
    for site in built.requests:
        key = (site.sym, site.tf)
        if key not in seen:
            seen.add(key)
            requests.append({"symbol": site.sym, "timeframe": site.tf})
    meta = {
        "title": built.title,
        "overlay": built.overlay,
        "inputs": built.input_defs,
        "requests": requests,
        "conditions": [{"title": c["title"], "message": c["message"]} for c in built.conds],
        "usesLib": False,
    }
    return Program(stmts, meta)
