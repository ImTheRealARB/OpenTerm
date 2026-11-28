"""The two error types of OpenTerm Script.

A compile error is raised once, by `compile_script`, and carries every problem found (`errors`, a list of
`{"msg", "line", "col"}`, 1-based). A runtime error stops one run; `Program.run` catches it and reports it in the result,
so the host can still draw everything that was computed before the failing bar.
"""

from __future__ import annotations


class ScriptCompileError(Exception):
    """The script cannot be compiled. `.errors` is a list of {"msg", "line", "col"} (messages are short, ALL CAPS)."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        first = errors[0] if errors else {"msg": "COMPILE ERROR", "line": 0, "col": 0}
        super().__init__(f"{first['msg']} (LINE {first['line']})")


class ScriptRuntimeError(Exception):
    """Raised while a script runs. The statement that was running adds its line and column on the way out."""

    def __init__(self, msg: str, line: int | None = None, col: int | None = None):
        super().__init__(msg)
        self.msg = msg
        self.line = line
        self.col = col


def err(msg: str, line: int, col: int) -> dict:
    """One compile error record."""
    return {"msg": msg, "line": line, "col": col}
