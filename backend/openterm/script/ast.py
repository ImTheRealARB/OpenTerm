"""The syntax tree of OpenTerm Script: plain dataclasses, one per kind of node.

Every node keeps its `line` and `col` (1-based) so errors can point at the source. The checker fills in a few extra
fields (`ref`, `decl`, ...) while it walks the tree; the interpreter reads them instead of looking names up again.

Note for readers: this module is called `ast` like Python's standard module, but it lives inside the `openterm.script`
package and is only imported as `from . import ast as A`, so the two never clash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Decl:
    """One declared variable (a `name = ...` line, a loop variable, a function parameter or a destructured name).

    The interpreter makes a fresh storage cell per Decl per call site of a user function, which is how every call site gets
    its own state. `eq=False` semantics: two Decls are equal only when they are the same object.
    """

    __slots__ = ("col", "fn", "is_input", "keep_hist", "line", "name", "persistent")

    def __init__(self, name: str, fn: Any, persistent: bool, line: int, col: int):
        self.name = name
        self.fn = fn  # the FuncDef it belongs to, or None for the main script
        self.persistent = persistent  # declared with `var`
        self.keep_hist = False  # read with x[n] somewhere, so its past values must be kept
        self.is_input = False  # assigned straight from an input.* call (constant for the whole run)
        self.line = line
        self.col = col


# ---------------------------------------------------------------------------------------------------- expressions


@dataclass
class Num:
    value: float
    line: int = 0
    col: int = 0


@dataclass
class Str:
    value: str
    line: int = 0
    col: int = 0


@dataclass
class Color:
    value: str
    line: int = 0
    col: int = 0


@dataclass
class Bool:
    value: bool
    line: int = 0
    col: int = 0


@dataclass
class NaLit:
    line: int = 0
    col: int = 0


@dataclass
class Name:
    name: str
    line: int = 0
    col: int = 0
    # Set by the checker: ("var", Decl) | ("builtin", Builtin) | ("func", FuncDef)
    ref: Any = None


@dataclass
class Unary:
    op: str  # "-" or "not"
    operand: Any
    line: int = 0
    col: int = 0


@dataclass
class Binary:
    op: str  # + - * / % == != < <= > >= and or
    left: Any
    right: Any
    line: int = 0
    col: int = 0


@dataclass
class Ternary:
    cond: Any
    then: Any
    other: Any
    line: int = 0
    col: int = 0


@dataclass
class Arg:
    """One call argument; `name` is set for named arguments (`color=color.red`)."""

    value: Any
    name: str | None = None
    line: int = 0
    col: int = 0


@dataclass
class Call:
    callee: Any  # Name or Member
    args: list[Arg] = field(default_factory=list)
    line: int = 0
    col: int = 0
    # Set by the checker:
    #   ref   = ("builtin", Builtin) | ("func", FuncDef) | ("method", method name)
    #   bound = for builtins and user functions: one entry per parameter, an expression node or None (use the default)
    ref: Any = None
    bound: Any = None


@dataclass
class Index:
    """History read `x[n]`."""

    obj: Any
    index: Any
    line: int = 0
    col: int = 0


@dataclass
class Member:
    obj: Any
    name: str
    line: int = 0
    col: int = 0
    ref: Any = None  # for `color.red` style reads: ("builtin", Builtin)


@dataclass
class TupleLit:
    items: list[Any]
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------------------------------- statements


@dataclass
class Assign:
    """`name = expr`, `var name = expr`, `name := expr`, `name += expr` (op is the operator text)."""

    name: str
    op: str  # "=", ":=", "+=", "-=", "*=", "/="
    value: Any
    is_var: bool = False
    line: int = 0
    col: int = 0
    decl: Any = None  # the Decl this statement declares (for "=") or changes (for the others)


@dataclass
class TupleAssign:
    names: list[str]
    value: Any
    name_pos: list[tuple[int, int]] = field(default_factory=list)
    line: int = 0
    col: int = 0
    decls: Any = None


@dataclass
class If:
    cond: Any
    body: list[Any]
    orelse: list[Any] | None = None  # a list holding one If for `else if`, a list of statements for `else`
    line: int = 0
    col: int = 0


@dataclass
class For:
    var: str
    start: Any
    stop: Any
    step: Any | None
    body: list[Any]
    line: int = 0
    col: int = 0
    decl: Any = None


@dataclass
class While:
    cond: Any
    body: list[Any]
    line: int = 0
    col: int = 0


@dataclass
class Break:
    line: int = 0
    col: int = 0


@dataclass
class Continue:
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt:
    expr: Any
    line: int = 0
    col: int = 0


@dataclass
class Param:
    name: str
    default: Any | None = None
    line: int = 0
    col: int = 0
    decl: Any = None


@dataclass(eq=False)
class FuncDef:
    name: str
    params: list[Param]
    body: list[Any]  # a block; for `f(x) => expr` it is one ExprStmt
    line: int = 0
    col: int = 0
    # Set by the checker:
    contains_ta: bool = False  # the body (or a function it calls) has a ta.* call
    tuple_arity: int | None = None  # the size of the tuple the last expression builds, when known
