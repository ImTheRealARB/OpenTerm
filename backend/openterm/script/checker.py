"""Checker: walks the syntax tree once, before anything runs, and reports every problem it can find.

What it checks (spec 1.3 to 1.5): names exist and are declared before use, `=` vs `:=`, call arities and named arguments,
break/continue only inside loops, `ta.*` never inside a loop (also through user functions), history `x[n]` only on a name,
no recursion, top-level-only built-ins, constant arguments where the spec asks for them, and the `request` restrictions.

It also does the bookkeeping the interpreter needs: every Name gets a `ref` that says what it means, every declaration gets
a Decl object, and every call gets `bound` (its arguments lined up with the parameters).
"""

# `x != x` is the standard test for NaN (na) in Python and JavaScript; ruff's PLR0124 would reject it.

from __future__ import annotations

import math

from . import ast as A
from .errors import ScriptCompileError, err
from .names import BY_NAME, COLORS, METHOD_NAMESPACES, NAMESPACES, SOURCES, Builtin

NAN = float("nan")

# Parameters that must be constants (literals), per built-in. They end up in the result as plain metadata.
CONST_PARAMS: dict[str, tuple[str, ...]] = {
    "indicator": ("title", "overlay", "max_labels"),
    "alertcondition": ("title", "message"),
    "plot": ("title", "linewidth", "style"),
    "hline": ("title", "linestyle"),
    "plotshape": ("title", "style", "location", "text"),
}
# Bar series that `x[n]` may read.
SERIES_NAMES = frozenset(["open", "high", "low", "close", "volume", "time", "hl2", "hlc3", "ohlc4", "bar_index", "last_bar_index"])
METHOD_NAMES = frozenset(b.name.split(".", 1)[1] for b in BY_NAME.values() if b.name.split(".")[0] in METHOD_NAMESPACES and "." in b.name)
# What `request(...)` may call inside its expression.
REQUEST_FN_PREFIXES = ("math.", "ta.", "lib.")
REQUEST_FNS = frozenset(["na", "nz"])


class NotConst(Exception):
    """Raised by const_eval when an expression is not a compile-time constant."""


def const_eval(n):
    """Value of a constant expression (a literal, a negative number, a colour name, `array.from(...)` of constants ...)."""
    if isinstance(n, A.Num | A.Str | A.Bool | A.Color):
        return n.value
    if isinstance(n, A.NaLit):
        return NAN
    if isinstance(n, A.Unary) and n.op == "-":
        v = const_eval(n.operand)
        if isinstance(v, float):
            return -v
        raise NotConst
    if isinstance(n, A.Binary) and n.op in ("+", "-", "*", "/"):
        a, b = const_eval(n.left), const_eval(n.right)
        if isinstance(a, str) and isinstance(b, str) and n.op == "+":
            return a + b
        if isinstance(a, float) and isinstance(b, float):
            if n.op == "+":
                return a + b
            if n.op == "-":
                return a - b
            if n.op == "*":
                return a * b
            return a / b if b != 0 else NAN
        raise NotConst
    if isinstance(n, A.Member | A.Name) and n.ref is not None and n.ref[0] == "builtin":
        name = n.ref[1].name
        if name.startswith("color."):
            return COLORS[name[6:]]
        if name == "math.pi":
            return math.pi
        if name == "math.e":
            return math.e
        raise NotConst
    if isinstance(n, A.TupleLit):
        return tuple(const_eval(i) for i in n.items)
    if isinstance(n, A.Call) and n.ref is not None and n.ref == ("builtin", BY_NAME["array.from"]):
        return tuple(const_eval(a.value) for a in n.args)
    raise NotConst


class Scope:
    """A block's names. `root` marks a function's own top scope: redeclaration checks stop there."""

    __slots__ = ("names", "parent", "root")

    def __init__(self, parent: Scope | None, root: bool = False):
        self.names: dict[str, A.Decl] = {}
        self.parent = parent
        self.root = root

    def lookup(self, name: str) -> A.Decl | None:
        s: Scope | None = self
        while s is not None:
            d = s.names.get(name)
            if d is not None:
                return d
            s = s.parent
        return None

    def declared_in_chain(self, name: str) -> bool:
        s: Scope | None = self
        while s is not None:
            if name in s.names:
                return True
            if s.root:
                return False
            s = s.parent
        return False


def dotted_path(n) -> list[str] | None:
    """`ta.sma` -> ["ta", "sma"]; None when the chain does not start at a plain name."""
    parts: list[str] = []
    while isinstance(n, A.Member):
        parts.append(n.name)
        n = n.obj
    if isinstance(n, A.Name):
        parts.append(n.name)
        return parts[::-1]
    return None


def plural(n: int) -> str:
    return f"{n} ARGUMENT" if n == 1 else f"{n} ARGUMENTS"


class Checker:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.funcs: dict[str, A.FuncDef] = {}
        self.global_scope = Scope(None)
        self.scope = self.global_scope
        self.fn: A.FuncDef | None = None
        self.loops = 0  # loops open around the current position (inside the current function body)
        self.depth = 0  # blocks open (if / for / while / function)
        self.input_titles: set[str] = set()
        self.alert_titles: set[str] = set()
        self.indicator_seen = False
        self.strategy_seen = False

    # ------------------------------------------------------------------------------------------ errors and scopes

    def error(self, msg: str, node) -> None:
        self.errors.append(err(msg, getattr(node, "line", 0), getattr(node, "col", 0)))

    def declare(self, name: str, node, persistent: bool = False) -> A.Decl:
        if name in BY_NAME or name in NAMESPACES or name in ("na", "strategy"):
            self.error(f"{name.upper()} IS A BUILT-IN NAME", node)
        elif name in self.funcs or self.scope.declared_in_chain(name):
            self.error(f"{name.upper()} IS ALREADY DECLARED", node)
        d = A.Decl(name, self.fn, persistent, getattr(node, "line", 0), getattr(node, "col", 0))
        self.scope.names[name] = d
        return d

    def push(self, root: bool = False) -> Scope:
        old = self.scope
        self.scope = Scope(old, root)
        self.depth += 1
        return old

    def pop(self, old: Scope) -> None:
        self.scope = old
        self.depth -= 1

    def at_top_level(self) -> bool:
        return self.fn is None and self.depth == 0

    # ------------------------------------------------------------------------------------------ statements

    def check_program(self, stmts: list) -> list[dict]:
        for i, s in enumerate(stmts):
            self.stmt(s, first_statement=(i == 0))
        # indicator(...) is optional (the title then defaults); when it IS there it must come first: the per-call check in
        # `call` below reports a late one. Same rule as the TS engine (checker.ts), so both pass the conformance JSON.
        seen: set = set()
        out = []
        for e in sorted(self.errors, key=lambda e: (e["line"], e["col"])):
            key = (e["msg"], e["line"], e["col"])
            if key not in seen:
                seen.add(key)
                out.append(e)
        return out

    def block(self, stmts: list) -> None:
        old = self.push()
        for s in stmts:
            self.stmt(s)
        self.pop(old)

    def stmt(self, s, first_statement: bool = False) -> None:
        if isinstance(s, A.Assign):
            self.assign(s)
        elif isinstance(s, A.TupleAssign):
            self.tuple_assign(s)
        elif isinstance(s, A.If):
            self.expr(s.cond)
            self.block(s.body)
            if s.orelse is not None:
                self.block(s.orelse)
        elif isinstance(s, A.For):
            self.expr(s.start)
            self.expr(s.stop)
            if s.step is not None:
                self.expr(s.step)
            old = self.push()
            s.decl = self.declare(s.var, s)
            self.loops += 1
            for b in s.body:
                self.stmt(b)
            self.loops -= 1
            self.pop(old)
        elif isinstance(s, A.While):
            self.expr(s.cond)
            old = self.push()
            self.loops += 1
            for b in s.body:
                self.stmt(b)
            self.loops -= 1
            self.pop(old)
        elif isinstance(s, A.Break):
            if self.loops == 0:
                self.error("BREAK OUTSIDE A LOOP", s)
        elif isinstance(s, A.Continue):
            if self.loops == 0:
                self.error("CONTINUE OUTSIDE A LOOP", s)
        elif isinstance(s, A.ExprStmt):
            self.allow_indicator = first_statement
            self.expr(s.expr)
            self.allow_indicator = False
        elif isinstance(s, A.FuncDef):
            self.func_def(s)

    allow_indicator = False

    def assign(self, s: A.Assign) -> None:
        self.expr(s.value)
        size = self.tuple_size(s.value)
        if size is not None and isinstance(s.value, A.Call):
            names = ", ".join(chr(ord("A") + i) for i in range(size))
            self.error(f"{self.call_name(s.value)} GIVES {size} VALUES (USE [{names}] = ...)", s.value.callee)
        if s.op == "=":
            s.decl = self.declare(s.name, s, persistent=s.is_var)
            v = s.value
            if (
                isinstance(v, A.Call)
                and v.ref is not None
                and v.ref[0] == "builtin"
                and v.ref[1].name.startswith("input.")
            ):
                s.decl.is_input = True
            return
        d = self.scope.lookup(s.name)
        if d is None:
            self.error(f"{s.name.upper()} IS NOT DECLARED (USE = FIRST)", s)
            return
        if d.fn is not self.fn:
            self.error("FUNCTIONS CANNOT CHANGE OUTER VARIABLES", s)
        s.decl = d

    def tuple_assign(self, s: A.TupleAssign) -> None:
        self.expr(s.value)
        size = self.tuple_size(s.value)
        if size is not None and size != len(s.names):
            what = self.call_name(s.value) if isinstance(s.value, A.Call) else "THIS"
            self.error(f"{what} GIVES {size} VALUES, NOT {len(s.names)}", s)
        elif isinstance(s.value, A.Call) and s.value.ref is not None and s.value.ref[0] == "builtin":
            if s.value.ref[1].ret in ("number", "bool", "string", "color"):
                self.error(f"{self.call_name(s.value)} GIVES ONE VALUE", s)
        decls = []
        for name, (line, col) in zip(s.names, s.name_pos, strict=True):
            decls.append(self.declare(name, A.Name(name, line, col)))
        s.decls = decls

    def func_def(self, fd: A.FuncDef) -> None:
        if not self.at_top_level():
            self.error("FUNCTIONS CAN ONLY BE DEFINED AT THE TOP LEVEL", fd)
            return
        n = fd.name
        if n in BY_NAME or n in NAMESPACES or n in ("na", "strategy"):
            self.error(f"{n.upper()} IS A BUILT-IN NAME", fd)
        elif n in self.funcs or self.global_scope.lookup(n):
            self.error(f"{n.upper()} IS ALREADY DECLARED", fd)
        self.funcs[n] = fd  # registered first so a call to itself is noticed
        saved = (self.fn, self.loops, self.scope, self.depth)
        self.fn = fd
        self.loops = 0
        # Default values may only use built-ins: check them in an empty scope.
        self.scope = Scope(None, root=True)
        for p in fd.params:
            if p.default is not None:
                self.expr(p.default)
        self.scope = Scope(self.global_scope, root=True)
        self.depth += 1
        seen: set[str] = set()
        for p in fd.params:
            if p.name in seen:
                self.error(f"PARAMETER {p.name.upper()} IS GIVEN TWICE", p)
            seen.add(p.name)
            if p.name in BY_NAME or p.name in NAMESPACES:
                self.error(f"{p.name.upper()} IS A BUILT-IN NAME", p)
            p.decl = A.Decl(p.name, fd, False, p.line, p.col)
            self.scope.names[p.name] = p.decl
        for b in fd.body:
            self.stmt(b)
        last = fd.body[-1] if fd.body else None
        if isinstance(last, A.ExprStmt) and isinstance(last.expr, A.TupleLit):
            fd.tuple_arity = len(last.expr.items)
        self.fn, self.loops, self.scope, self.depth = saved

    # ------------------------------------------------------------------------------------------ expressions

    def call_name(self, call: A.Call) -> str:
        p = dotted_path(call.callee)
        return ".".join(p).upper() if p else "THIS CALL"

    def tuple_size(self, e) -> int | None:
        if isinstance(e, A.Call) and e.ref is not None:
            if e.ref[0] == "builtin" and e.ref[1].ret.startswith("tuple:"):
                return int(e.ref[1].ret.split(":")[1])
            if e.ref[0] == "func":
                return e.ref[1].tuple_arity
        if isinstance(e, A.TupleLit):
            return len(e.items)
        return None

    def expr(self, e) -> None:
        if isinstance(e, A.Num | A.Str | A.Bool | A.Color | A.NaLit):
            return
        if isinstance(e, A.Name):
            self.name(e)
        elif isinstance(e, A.Unary):
            self.expr(e.operand)
        elif isinstance(e, A.Binary):
            self.expr(e.left)
            self.expr(e.right)
        elif isinstance(e, A.Ternary):
            self.expr(e.cond)
            self.expr(e.then)
            self.expr(e.other)
        elif isinstance(e, A.Index):
            self.index(e)
        elif isinstance(e, A.Member):
            self.member(e)
        elif isinstance(e, A.Call):
            self.call(e)
        elif isinstance(e, A.TupleLit):
            for i in e.items:
                self.expr(i)

    def name(self, n: A.Name) -> None:
        d = self.scope.lookup(n.name)
        if d is not None:
            n.ref = ("var", d)
            return
        if n.name in self.funcs:
            self.error(f"{n.name.upper()} IS A FUNCTION (CALL IT WITH PARENTHESES)", n)
            return
        b = BY_NAME.get(n.name)
        if b is not None and b.kind == "var":
            n.ref = ("builtin", b)
            return
        if b is not None:
            self.error(f"{n.name.upper()} IS A FUNCTION (CALL IT WITH PARENTHESES)", n)
            return
        self.error(f"UNKNOWN NAME {n.name.upper()}", n)

    def member(self, m: A.Member) -> None:
        path = dotted_path(m)
        if path is None:
            self.error(f"UNKNOWN FIELD {m.name.upper()}", m)
            return
        joined = ".".join(path)
        b = BY_NAME.get(joined)
        if b is not None and b.kind == "var" and self.scope.lookup(path[0]) is None:
            m.ref = ("builtin", b)
            return
        if self.scope.lookup(path[0]) is not None:
            self.error(f"UNKNOWN FIELD {m.name.upper()}", m)
        elif path[0] == "strategy":
            self.error("STRATEGIES COME IN PART 2 (NOT BUILT YET)", m)
            self.strategy_seen = True
        else:
            self.error(f"UNKNOWN NAME {joined.upper()}", m)

    def index(self, e: A.Index) -> None:
        if not isinstance(e.obj, A.Name):
            self.error("ASSIGN TO A VARIABLE FIRST", e)
            self.expr(e.obj)
            self.expr(e.index)
            return
        self.name(e.obj)
        ref = e.obj.ref
        if ref is not None:
            if ref[0] == "var":
                ref[1].keep_hist = True
            elif ref[1].name not in SERIES_NAMES:
                self.error("ASSIGN TO A VARIABLE FIRST", e)
        self.expr(e.index)

    # ------------------------------------------------------------------------------------------ calls

    def bind(self, name: str, params, variadic: bool, args: list[A.Arg], node) -> list | None:
        """Line the arguments up with the parameters. Returns one entry per parameter (node or None) + extras."""
        positional = [a for a in args if a.name is None]
        named = [a for a in args if a.name is not None]
        n_params = len(params)
        required = sum(1 for p in params if p[1] is None)
        bound: list = [None] * n_params
        extras: list = []
        for i, a in enumerate(positional):
            if i < n_params:
                bound[i] = a.value
            elif variadic:
                extras.append(a.value)
            else:
                self.arity_error(name, required, n_params, variadic, node)
                return None
        index = {p[0]: i for i, p in enumerate(params)}
        for a in named:
            i = index.get(a.name)
            if i is None:
                self.error(f"UNKNOWN ARGUMENT {a.name.upper()} FOR {name}", a)
                return None
            if bound[i] is not None:
                self.error(f"ARGUMENT {a.name.upper()} IS GIVEN TWICE", a)
                return None
            bound[i] = a.value
        for i, p in enumerate(params):
            if bound[i] is None and p[1] is None:
                self.arity_error(name, required, n_params, variadic, node)
                return None
        return bound + extras

    def arity_error(self, name: str, required: int, total: int, variadic: bool, node) -> None:
        if variadic:
            self.error(f"{name} TAKES AT LEAST {plural(required)}", node)
        elif required == total:
            self.error(f"{name} TAKES {plural(total)}", node)
        else:
            self.error(f"{name} TAKES {required} TO {plural(total)}", node)

    def call(self, c: A.Call) -> None:
        callee = c.callee
        at = callee  # error position
        path = dotted_path(callee)
        # --- which function is it?
        if isinstance(callee, A.Name):
            n = callee.name
            if n == "strategy":
                self.error("STRATEGIES COME IN PART 2 (NOT BUILT YET)", at)
                self.strategy_seen = True
                return
            if n in self.funcs:
                self.user_call(c, self.funcs[n])
                return
            if self.scope.lookup(n) is not None:
                self.error(f"{n.upper()} IS NOT A FUNCTION", at)
                return
            b = BY_NAME.get(n)
            if b is None or b.kind != "fn":
                self.error(f"UNKNOWN NAME {n.upper()}", at)
                return
            self.builtin_call(c, b)
            return
        if path is not None:
            head = path[0]
            joined = ".".join(path)
            if self.scope.lookup(head) is None:
                if head == "strategy":
                    self.error("STRATEGIES COME IN PART 2 (NOT BUILT YET)", at)
                    self.strategy_seen = True
                    return
                if head == "lib":
                    self.error(f"{joined.upper()} RUNS ONLY ON THE CHART IN V1", at)
                    return
                b = BY_NAME.get(joined)
                if b is not None and b.kind == "fn":
                    self.builtin_call(c, b)
                    return
                self.error(f"UNKNOWN NAME {joined.upper()}", at)
                return
        # --- a method on a value: `a.push(x)`, `lbl.delete()`
        if not isinstance(callee, A.Member):
            self.error("EXPECTED A FUNCTION NAME", at)
            return
        self.expr(callee.obj)
        if callee.name not in METHOD_NAMES:
            self.error(f"UNKNOWN METHOD {callee.name.upper()}", at)
        c.ref = ("method", callee.name)
        for a in c.args:
            self.expr(a.value)

    def user_call(self, c: A.Call, fd: A.FuncDef) -> None:
        name = fd.name.upper()
        if fd is self.fn:
            self.error(f"{name} CANNOT CALL ITSELF", c.callee)
            return
        params = [(p.name, "default" if p.default is not None else None) for p in fd.params]
        bound = self.bind(name, params, False, c.args, c.callee)
        if bound is None:
            return
        c.ref = ("func", fd)
        c.bound = bound
        for b in bound:
            if b is not None:
                self.expr(b)
        if fd.contains_ta:
            if self.loops > 0:
                self.error("TA CALLS CANNOT RUN INSIDE A LOOP", c.callee)
            if self.fn is not None:
                self.fn.contains_ta = True

    def builtin_call(self, c: A.Call, b: Builtin) -> None:
        name = b.name.upper()
        bound = self.bind(name, b.params, b.variadic, c.args, c.callee)
        if bound is None:
            return
        c.ref = ("builtin", b)
        c.bound = bound
        if b.top_level and not self.at_top_level():
            self.error(f"{name} CAN ONLY BE USED AT THE TOP LEVEL", c.callee)
        if b.name == "indicator":
            if not self.allow_indicator or self.indicator_seen:
                self.error("INDICATOR MUST BE THE FIRST STATEMENT", c.callee)
            self.indicator_seen = True
        if b.stateful:
            if self.loops > 0:
                self.error("TA CALLS CANNOT RUN INSIDE A LOOP", c.callee)
            if self.fn is not None:
                self.fn.contains_ta = True
        before = len(self.errors)
        for x in bound:
            if x is not None:
                self.expr(x)
        if len(self.errors) > before:
            return  # do not pile more errors on a broken argument
        # constants the spec asks for
        for pname in CONST_PARAMS.get(b.name, ()):
            idx = [p[0] for p in b.params].index(pname)
            node = bound[idx]
            if node is not None:
                try:
                    const_eval(node)
                except NotConst:
                    self.error(f"{pname.upper()} MUST BE A CONSTANT", node)
        if b.name.startswith("input."):
            self.input_call(c, b, bound)
        elif b.name == "alertcondition":
            title = const_eval(bound[1]) if bound[1] is not None else ""
            if title in self.alert_titles:
                self.error("DUPLICATE ALERT TITLE", c.callee)
            self.alert_titles.add(title)
        elif b.name == "request":
            self.request_call(c, bound)

    def input_call(self, c: A.Call, b: Builtin, bound: list) -> None:
        for i, x in enumerate(bound):
            if x is None:
                continue
            if b.name == "input.source" and i == 0:
                if not (isinstance(x, A.Name) and x.ref is not None and x.ref[0] == "builtin" and x.name in SOURCES):
                    self.error("INPUT.SOURCE NEEDS A PRICE SERIES (OPEN, HIGH, LOW, CLOSE, VOLUME, HL2, HLC3, OHLC4)", x)
                continue
            try:
                const_eval(x)
            except NotConst:
                self.error(f"{b.params[i][0].upper() if i < len(b.params) else 'ARGUMENT'} MUST BE A CONSTANT", x)
        title_node = bound[1] if len(bound) > 1 else None
        if title_node is not None:
            try:
                title = const_eval(title_node)
            except NotConst:
                return
            if title in self.input_titles:
                self.error("DUPLICATE INPUT TITLE", c.callee)
            self.input_titles.add(title)

    def request_call(self, c: A.Call, bound: list) -> None:
        for node in bound[:2]:
            ok = isinstance(node, A.Str) or (
                isinstance(node, A.Name) and node.ref is not None and node.ref[0] == "var" and node.ref[1].is_input
            )
            if not ok:
                self.error("REQUEST SYMBOL AND TIMEFRAME MUST BE CONSTANTS OR INPUTS", node)
                return
        if not self.request_ok(bound[2]):
            self.error("REQUEST CAN ONLY USE BAR DATA, INPUTS AND BUILT-INS", bound[2])

    def request_ok(self, e) -> bool:
        """True when `e` uses only bar data, constants, inputs and math / ta / lib built-ins."""
        if isinstance(e, A.Num | A.Str | A.Bool | A.Color | A.NaLit):
            return True
        if isinstance(e, A.Name):
            r = e.ref
            return r is not None and (r[0] == "builtin" or (r[0] == "var" and r[1].is_input))
        if isinstance(e, A.Member):
            return e.ref is not None
        if isinstance(e, A.Unary):
            return self.request_ok(e.operand)
        if isinstance(e, A.Binary):
            return self.request_ok(e.left) and self.request_ok(e.right)
        if isinstance(e, A.Ternary):
            return self.request_ok(e.cond) and self.request_ok(e.then) and self.request_ok(e.other)
        if isinstance(e, A.Index):
            # history only of a bar series (an input's past values live in the main script, not in the other data)
            obj_ok = isinstance(e.obj, A.Name) and e.obj.ref is not None and e.obj.ref[0] == "builtin"
            return obj_ok and self.request_ok(e.index)
        if isinstance(e, A.TupleLit):
            return all(self.request_ok(i) for i in e.items)
        if isinstance(e, A.Call):
            if e.ref is None or e.ref[0] != "builtin":
                return False
            nm = e.ref[1].name
            if not (nm.startswith(REQUEST_FN_PREFIXES) or nm in REQUEST_FNS):
                return False
            return all(self.request_ok(b) for b in (e.bound or []) if b is not None)
        return False


def check(stmts: list) -> list[dict]:
    """Check a parsed script. Returns the list of compile errors (empty when the script is fine)."""
    return Checker().check_program(stmts)


def check_or_raise(stmts: list) -> None:
    errors = check(stmts)
    if errors:
        raise ScriptCompileError(errors)
