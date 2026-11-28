"""The interpreter: turns a checked syntax tree into a tree of Python closures, then runs it once per bar.

How it works, in plain words:
  * "Compiling" walks the tree once and builds, for every node, a small function (a closure) that computes its value.
    Names are bound to storage cells (`Var`) at this point, so running never looks anything up by name.
  * A user function is compiled again at EVERY call site. That is how each call site gets its own `var`s and its own `ta.*`
    state without any bookkeeping (spec 1.3). There is no recursion, so this always ends; the node cap bounds the size.
  * The closures keep their state (var cells, ta objects, drawings ...) inside themselves, so a `Builder` is single-use: a new
    run builds a fresh one. Building costs about a millisecond for a normal script.
"""

# `x != x` is the standard test for NaN (na) in Python and JavaScript; ruff's PLR0124 would reject it.
# ruff: noqa: PLR0124

from __future__ import annotations

import math
import operator
import statistics
import time as _time
from collections.abc import Callable

from . import ast as A
from . import builtins as B
from .builtins import NA, Arr, MapObj, fail, num, text, truthy
from .checker import NotConst, const_eval
from .errors import ScriptCompileError, ScriptRuntimeError, err
from .names import (
    BY_NAME,
    LIMITS,
    PLOT_STYLES,
    SHAPE_LOCATIONS,
    SHAPE_STYLES,
    SOURCES,
    TABLE_POSITIONS,
)
from .resample import bar_end, normalize, resample, seconds
from .ta import LOOKBACK, TA_FACTORIES

BRK = 1  # signals returned by statement closures
CNT = 2
RUN_STEP_CAP = LIMITS["stepsPerRun"]
BAR_STEP_CAP = LIMITS["stepsPerBar"]


# ---------------------------------------------------------------------------------------------------- run state


class Var:
    """One variable's storage: its current value and (only when the script reads `x[n]`) its past values."""

    __slots__ = ("cur", "hist")

    def __init__(self) -> None:
        self.cur = NA
        self.hist: list | None = None


class Env:
    """Where variables live while compiling: `glob` for the main script, `loc` for the function being compiled."""

    __slots__ = ("glob", "loc")

    def __init__(self, loc: dict, glob: dict):
        self.loc = loc
        self.glob = glob

    def get(self, decl: A.Decl) -> Var:
        return (self.glob if decl.fn is None else self.loc)[decl]


class Runtime:
    """Counters shared by every closure of one run."""

    __slots__ = ("cap", "steps")

    def __init__(self) -> None:
        self.steps = 0
        self.cap = RUN_STEP_CAP

    def limit(self):
        raise ScriptRuntimeError("STEP LIMIT")


class DS:
    """A data set the script's bar series read from: the chart's bars, or the bars a `request` looks at."""

    __slots__ = ("c", "h", "hl2", "hlc3", "i", "l", "n", "o", "ohlc4", "t", "v")

    def __init__(self) -> None:
        self.i = 0
        self.n = 0
        self.load({k: [] for k in "ohlcvt"})

    def load(self, cols: dict) -> None:
        self.o, self.h, self.l, self.c, self.v, self.t = (cols[k] for k in "ohlcvt")
        self.n = len(self.c)
        self.hl2 = [(h + lo) / 2 for h, lo in zip(self.h, self.l, strict=True)]
        self.hlc3 = [(h + lo + c) / 3 for h, lo, c in zip(self.h, self.l, self.c, strict=True)]
        self.ohlc4 = [(o + h + lo + c) / 4 for o, h, lo, c in zip(self.o, self.h, self.l, self.c, strict=True)]
        self.i = 0


SERIES_ATTR = {
    "open": "o", "high": "h", "low": "l", "close": "c", "volume": "v", "time": "t", "hl2": "hl2", "hlc3": "hlc3", "ohlc4": "ohlc4",
}


def series_getter(ds: DS, name: str) -> Callable[[], float]:
    """A closure reading the bar series `name` at the data set's current bar."""
    if name == "bar_index":
        return lambda: float(ds.i)
    if name == "last_bar_index":
        return lambda: float(ds.n - 1)
    attr = SERIES_ATTR[name]
    if attr == "o":
        return lambda: ds.o[ds.i]
    if attr == "h":
        return lambda: ds.h[ds.i]
    if attr == "l":
        return lambda: ds.l[ds.i]
    if attr == "c":
        return lambda: ds.c[ds.i]
    if attr == "v":
        return lambda: ds.v[ds.i]
    if attr == "t":
        return lambda: ds.t[ds.i]
    if attr == "hl2":
        return lambda: ds.hl2[ds.i]
    if attr == "hlc3":
        return lambda: ds.hlc3[ds.i]
    return lambda: ds.ohlc4[ds.i]


def series_at(ds: DS, name: str, j: int) -> float:
    """The bar series `name` at bar `j` of the data set (history reads `close[1]`)."""
    if j < 0:
        return NA
    if name == "bar_index":
        return float(j)
    if name == "last_bar_index":
        return float(ds.n - 1)
    return getattr(ds, SERIES_ATTR[name])[j]


# ---------------------------------------------------------------------------------------------------- values


def _add(a, b):
    ca, cb = a.__class__, b.__class__
    if ca is str and cb is str:
        return a + b
    if ca is str or cb is str:
        fail("CANNOT ADD TEXT AND NUMBER (USE STR.TOSTRING)")
    return num(a) + num(b)


def _sub(a, b):
    return num(a) - num(b)


def _mul(a, b):
    return num(a) * num(b)


def _div(a, b):
    a, b = num(a), num(b)
    return NA if b == 0 else a / b


def _mod(a, b):
    a, b = num(a), num(b)
    if b == 0 or a != a or b != b:
        return NA
    try:
        return math.fmod(a, b)
    except ValueError:
        return NA


ARITH = {"+": _add, "-": _sub, "*": _mul, "/": _div, "%": _mod}
FAST_CMP = {"<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge, "==": operator.eq}


def _cmp(op: str, a, b) -> bool:
    """Comparison for the slow path. Any na gives false (spec 1.2), for != too."""
    if (a.__class__ is float and a != a) or (b.__class__ is float and b != b):
        return False
    ca, cb = a.__class__, b.__class__
    if ca in (float, bool) and cb in (float, bool):
        a, b = num(a), num(b)
        if a != a or b != b:
            return False
    elif ca is not cb and op not in ("==", "!="):
        fail("CANNOT COMPARE THESE VALUES")
    try:
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b
    except TypeError:
        return fail("CANNOT COMPARE THESE VALUES")


def _colour(v):
    """A colour argument: na means "none" (None), a text is kept, anything else is an error."""
    c = v.__class__
    if c is str:
        return v
    if c is float and v != v:
        return None
    return fail("EXPECTED A COLOUR")


def _clean(v) -> float | None:
    """A number for the result: na becomes None."""
    return None if v != v else v


def default_const(src: str):
    """The value of a default written as source text in names.py ("0", "na", '"line"', "false")."""
    if src == "na":
        return NA
    if src == "true":
        return True
    if src == "false":
        return False
    if src.startswith(('"', "'")):
        return src[1:-1]
    return float(src)


# ---------------------------------------------------------------------------------------------------- outputs


class Out:
    """One entry of the result's `plots` list (a plot, hline, fill, shape or bgcolor)."""

    def __init__(self, kind: str, index: int, n: int, title: str = ""):
        self.kind = kind
        self.index = index
        self.title = title
        self.n = n
        self.style: str | None = None
        self.linewidth: float | None = None
        self.values: list | None = None
        self.cols: list | None = None
        self.price: float | None = None
        self.color: str | None = None
        self.linestyle: str | None = None
        self.a: int | None = None
        self.b: int | None = None
        self.location: str | None = None
        self.text: str | None = None
        self.fixed = False  # hline / fill: the one-time values were set

    def finish(self) -> dict:
        d: dict = {"kind": self.kind, "title": self.title}
        if self.style is not None:
            d["style"] = self.style
        if self.linewidth is not None:
            d["linewidth"] = self.linewidth
        if self.values is not None:
            d["values"] = self.values
        if self.kind == "hline":
            d["price"] = self.price
            # spec section 2 result shape: an hline's line style goes in `style`, like a plot's style (same key as the TS engine)
            d["style"] = self.linestyle
        if self.kind == "fill":
            d["a"] = self.a
            d["b"] = self.b
        if self.location is not None:
            d["location"] = self.location
        if self.text is not None:
            d["text"] = self.text
        if self.cols is not None:
            # One colour on every bar -> `color`; the colour changes from bar to bar -> `colors`.
            if len(set(self.cols)) <= 1:
                if self.cols and self.cols[0] is not None:
                    d["color"] = self.cols[0]
            else:
                d["colors"] = self.cols
        elif self.color is not None:
            d["color"] = self.color
        return d


class PlotHandle:
    __slots__ = ("index",)

    def __init__(self, index: int):
        self.index = index


class DrawList:
    """The drawings of one kind (labels, lines, boxes, tables): creating more than `cap` deletes the oldest."""

    def __init__(self, cap: int):
        self.cap = cap
        self.items: list = []
        self.alive = 0
        self.first = 0

    def add(self, h) -> None:
        h.owner = self
        h.alive = True
        self.items.append(h)
        self.alive += 1
        while self.alive > self.cap:
            while not self.items[self.first].alive:
                self.first += 1
            self.items[self.first].alive = False
            self.alive -= 1
        if self.first > 2000:
            del self.items[: self.first]
            self.first = 0

    def kill(self, h) -> None:
        if h.alive:
            h.alive = False
            self.alive -= 1

    def live(self) -> list:
        return [h for h in self.items if h.alive]


class Label:
    kind = "label"

    def __init__(self, x, y, txt, color, style, textcolor):
        self.x, self.y, self.text, self.color, self.style, self.textcolor = x, y, txt, color, style, textcolor
        self.alive = False
        self.owner: DrawList | None = None

    def out(self) -> dict:
        return {"x": _clean(self.x), "y": _clean(self.y), "text": self.text, "color": self.color, "style": self.style,
                "textcolor": self.textcolor}


class Line:
    kind = "line"

    def __init__(self, x1, y1, x2, y2, color, width):
        self.x1, self.y1, self.x2, self.y2, self.color, self.width = x1, y1, x2, y2, color, width
        self.alive = False
        self.owner: DrawList | None = None

    def out(self) -> dict:
        return {"x1": _clean(self.x1), "y1": _clean(self.y1), "x2": _clean(self.x2), "y2": _clean(self.y2),
                "color": self.color, "width": self.width}


class Box:
    kind = "box"

    def __init__(self, left, top, right, bottom, color, bgcolor):
        self.left, self.top, self.right, self.bottom, self.color, self.bgcolor = left, top, right, bottom, color, bgcolor
        self.alive = False
        self.owner: DrawList | None = None

    def out(self) -> dict:
        return {"left": _clean(self.left), "top": _clean(self.top), "right": _clean(self.right), "bottom": _clean(self.bottom),
                "color": self.color, "bgcolor": self.bgcolor}


class Table:
    kind = "table"

    def __init__(self, position, columns, rows):
        self.position, self.columns, self.rows = position, columns, rows
        self.cells: dict[tuple[int, int], dict] = {}
        self.alive = False
        self.owner: DrawList | None = None

    def out(self) -> dict:
        cells = [self.cells[k] for k in sorted(self.cells, key=lambda rc: (rc[0], rc[1]))]
        return {"position": self.position, "columns": self.columns, "rows": self.rows, "cells": cells}


def _drawing(v, cls, what: str):
    """Check that `v` is a drawing of the right kind. na is allowed (and means "do nothing")."""
    if v.__class__ is cls:
        return v
    if v.__class__ is float and v != v:
        return None
    return fail(f"EXPECTED A {what}")


class ReqSite:
    """One `request(...)` call: which data it needs, the closure that computes its expression, and the aligned result."""

    def __init__(self, sym: str, tf: str, ds: DS, ef: Callable, node):
        self.sym, self.tf, self.ds, self.ef, self.node = sym, tf, ds, ef, node
        self.series: list = []


# ---------------------------------------------------------------------------------------------------- the builder


class Builder:
    def __init__(self, stmts: list, n_bars: int, overrides: dict | None, main_ds: DS | None = None):
        self.stmts = stmts
        self.n = n_bars
        self.overrides = overrides or {}
        self.rt = Runtime()
        self.ds = main_ds if main_ds is not None else DS()
        self.main_ds = self.ds
        self.glob: dict = {}
        self.nodes = 0
        self.reset_vars: list[Var] = []
        self.hist_vars: list[Var] = []
        self.outs: list[Out] = []
        self.conds: list[dict] = []
        self.alerts: list[dict] = []
        self.input_defs: list[dict] = []
        self.input_vals: dict = {}
        self.requests: list[ReqSite] = []
        self.title = ""
        self.overlay = False
        self.max_labels = LIMITS["drawingsPerKind"]
        self.last_input = None
        self.arrays = B.Tracker(B.ARRAY_CAP)
        self.maps = B.Tracker(B.MAP_CAP)
        self.fns: dict[str, Callable] = B.make_pure(self.arrays, self.maps)
        self.labels = DrawList(self.max_labels)
        self.lines = DrawList(self.max_labels)
        self.boxes = DrawList(self.max_labels)
        self.tables = DrawList(self.max_labels)
        self._install_drawing_ops()
        self.special: dict[str, Callable] = {
            "indicator": self.c_indicator,
            "request": self.c_request,
            "plot": self.c_plot,
            "hline": self.c_hline,
            "fill": self.c_fill,
            "bgcolor": self.c_bgcolor,
            "plotshape": self.c_plotshape,
            "alert": self.c_alert,
            "alertcondition": self.c_alertcondition,
            "table.new": self.c_table_new,
        }
        for k in ("int", "float", "bool", "string", "source", "symbol", "timeframe"):
            self.special[f"input.{k}"] = self.c_input

    # ------------------------------------------------------------------------------------------ small helpers

    def cerr(self, msg: str, node):
        raise ScriptCompileError([err(msg, getattr(node, "line", 1), getattr(node, "col", 1))])

    def count(self, node) -> None:
        self.nodes += 1
        if self.nodes > LIMITS["nodes"]:
            self.cerr(f"SCRIPT IS TOO BIG (MAX {LIMITS['nodes']} NODES)", node)

    def new_var(self, decl: A.Decl, env: Env) -> Var:
        v = Var()
        if decl.keep_hist:
            v.hist = []
            self.hist_vars.append(v)
        if not decl.persistent:
            self.reset_vars.append(v)
        (env.glob if decl.fn is None else env.loc)[decl] = v
        return v

    def new_out(self, kind: str, node, title: str = "") -> Out:
        if len(self.outs) >= LIMITS["outputs"]:
            self.cerr(f"TOO MANY PLOTS, LINES AND SHAPES (MAX {LIMITS['outputs']})", node)
        o = Out(kind, len(self.outs), self.n, title)
        self.outs.append(o)
        return o

    def argf(self, node, default: str | None, env: Env) -> Callable:
        """The closure for one argument, or a constant closure for a default."""
        if node is not None:
            return self.ex(node, env)
        v = default_const(default) if default is not None else NA
        return lambda: v

    def const_arg(self, node, default: str | None):
        """The constant value of an argument that the checker already proved constant."""
        if node is None:
            return default_const(default) if default is not None else NA
        return const_eval(node)

    # ------------------------------------------------------------------------------------------ statements

    def build(self) -> Callable[[], None]:
        env = Env(self.glob, self.glob)
        main = self.block(self.stmts, env)
        return main

    def block(self, stmts: list, env: Env) -> Callable:
        ss = [c for c in (self.stmt(s, env) for s in stmts) if c is not None]
        if not ss:
            return lambda: None
        if len(ss) == 1:
            return ss[0]

        def run():
            for s in ss:
                r = s()
                if r:
                    return r
            return None

        return run

    def wrap(self, run: Callable, node) -> Callable:
        """Count one step and, when the statement fails, tell the error which line it was."""
        rt = self.rt
        line, col = node.line, node.col

        def go():
            try:
                rt.steps += 1
                if rt.steps > rt.cap:
                    rt.limit()
                return run()
            except ScriptRuntimeError as e:
                if e.line is None:
                    e.line, e.col = line, col
                raise

        return go

    def stmt(self, s, env: Env) -> Callable | None:
        self.count(s)
        if isinstance(s, A.FuncDef):
            return None
        if isinstance(s, A.Assign):
            return self.wrap(self.s_assign(s, env), s)
        if isinstance(s, A.TupleAssign):
            return self.wrap(self.s_tuple(s, env), s)
        if isinstance(s, A.If):
            return self.wrap(self.s_if(s, env), s)
        if isinstance(s, A.For):
            return self.wrap(self.s_for(s, env), s)
        if isinstance(s, A.While):
            return self.wrap(self.s_while(s, env), s)
        if isinstance(s, A.Break):
            return lambda: BRK
        if isinstance(s, A.Continue):
            return lambda: CNT
        if isinstance(s, A.ExprStmt):
            ef = self.ex(s.expr, env)

            def run():
                ef()

            return self.wrap(run, s)
        raise AssertionError(f"unknown statement {s!r}")

    def s_assign(self, s: A.Assign, env: Env) -> Callable:
        rf = self.ex(s.value, env)
        if s.op == "=":
            var = self.new_var(s.decl, env)
            if s.decl.is_input:
                self.input_vals[s.decl] = self.last_input
            if s.is_var:
                done = [False]

                def run_var():
                    if not done[0]:
                        done[0] = True
                        var.cur = rf()

                return run_var

            def run_set():
                var.cur = rf()

            return run_set
        var = env.get(s.decl)
        if s.op == ":=":

            def run_reassign():
                var.cur = rf()

            return run_reassign
        fn = ARITH[s.op[0]]

        def run_compound():
            var.cur = fn(var.cur, rf())

        return run_compound

    def s_tuple(self, s: A.TupleAssign, env: Env) -> Callable:
        rf = self.ex(s.value, env)
        vs = [self.new_var(d, env) for d in s.decls]
        k = len(vs)

        def run():
            vals = rf()
            if vals.__class__ is not tuple or len(vals) != k:
                fail(f"EXPECTED {k} VALUES")
            for v, x in zip(vs, vals, strict=True):
                v.cur = x

        return run

    def s_if(self, s: A.If, env: Env) -> Callable:
        cf = self.ex(s.cond, env)
        body = self.block(s.body, env)
        orelse = self.block(s.orelse, env) if s.orelse is not None else None

        def run():
            if truthy(cf()):
                return body()
            if orelse is not None:
                return orelse()
            return None

        return run

    def s_for(self, s: A.For, env: Env) -> Callable:
        f1 = self.ex(s.start, env)
        f2 = self.ex(s.stop, env)
        f3 = self.ex(s.step, env) if s.step is not None else None
        var = self.new_var(s.decl, env)
        body = self.block(s.body, env)
        rt = self.rt

        def run():
            a, b = num(f1()), num(f2())
            st = num(f3()) if f3 is not None else (1.0 if a <= b else -1.0)
            if a != a or b != b or st != st:
                fail("LOOP BOUNDS MUST BE NUMBERS")
            if st == 0:
                fail("LOOP STEP CANNOT BE 0")
            k = 0
            i = a
            while (i <= b) if st > 0 else (i >= b):
                rt.steps += 1
                if rt.steps > rt.cap:
                    rt.limit()
                var.cur = i
                if body() == BRK:
                    break
                k += 1
                i = a + k * st

        return run

    def s_while(self, s: A.While, env: Env) -> Callable:
        cf = self.ex(s.cond, env)
        body = self.block(s.body, env)
        rt = self.rt

        def run():
            while truthy(cf()):
                rt.steps += 1
                if rt.steps > rt.cap:
                    rt.limit()
                if body() == BRK:
                    break

        return run

    # ------------------------------------------------------------------------------------------ expressions

    def ex(self, n, env: Env) -> Callable:
        self.count(n)
        if isinstance(n, A.Num | A.Str | A.Color | A.Bool):
            v = n.value
            return lambda: v
        if isinstance(n, A.NaLit):
            return lambda: NA
        if isinstance(n, A.Name):
            return self.e_name(n, env)
        if isinstance(n, A.Member):
            return self.e_member(n)
        if isinstance(n, A.Unary):
            return self.e_unary(n, env)
        if isinstance(n, A.Binary):
            return self.e_binary(n, env)
        if isinstance(n, A.Ternary):
            cf, tf, of = self.ex(n.cond, env), self.ex(n.then, env), self.ex(n.other, env)
            return lambda: tf() if truthy(cf()) else of()
        if isinstance(n, A.Index):
            return self.e_index(n, env)
        if isinstance(n, A.TupleLit):
            fs = [self.ex(i, env) for i in n.items]
            return lambda: tuple([f() for f in fs])
        if isinstance(n, A.Call):
            return self.e_call(n, env)
        raise AssertionError(f"unknown expression {n!r}")

    def e_name(self, n: A.Name, env: Env) -> Callable:
        kind, ref = n.ref
        ds = self.ds
        if kind == "builtin":
            return series_getter(ds, ref.name)
        decl: A.Decl = ref
        if decl.is_input and not decl.keep_hist and decl in self.input_vals:
            val = self.input_vals[decl]
            if isinstance(val, SourceName):  # input.source: read that bar series of the data set being compiled
                return series_getter(ds, val.name)
            return lambda: val
        v = env.get(decl)
        return lambda: v.cur

    def e_member(self, n: A.Member) -> Callable:
        b = n.ref[1]
        ds = self.ds
        if b.name == "barstate.isfirst":
            return lambda: ds.i == 0
        if b.name == "barstate.islast":
            return lambda: ds.i == ds.n - 1
        val = B.VALUE_CONSTANTS[b.name]
        return lambda: val

    def e_unary(self, n: A.Unary, env: Env) -> Callable:
        f = self.ex(n.operand, env)
        if n.op == "not":
            return lambda: not truthy(f())

        def neg():
            x = f()
            return -x if x.__class__ is float else -num(x)

        return neg

    def e_binary(self, n: A.Binary, env: Env) -> Callable:
        lf, rf = self.ex(n.left, env), self.ex(n.right, env)
        op = n.op
        if op == "and":
            return lambda: truthy(lf()) and truthy(rf())
        if op == "or":
            return lambda: truthy(lf()) or truthy(rf())
        if op == "+":

            def add():
                a, b = lf(), rf()
                if a.__class__ is float and b.__class__ is float:
                    return a + b
                return _add(a, b)

            return add
        if op == "-":

            def sub():
                a, b = lf(), rf()
                if a.__class__ is float and b.__class__ is float:
                    return a - b
                return _sub(a, b)

            return sub
        if op == "*":

            def mul():
                a, b = lf(), rf()
                if a.__class__ is float and b.__class__ is float:
                    return a * b
                return _mul(a, b)

            return mul
        if op == "/":
            return lambda: _div(lf(), rf())
        if op == "%":
            return lambda: _mod(lf(), rf())
        if op == "!=":

            def ne():
                a, b = lf(), rf()
                if a.__class__ is float and b.__class__ is float:
                    return a == a and b == b and a != b  # any na makes it false
                return _cmp("!=", a, b)

            return ne
        pyop = FAST_CMP[op]

        def compare():
            a, b = lf(), rf()
            if a.__class__ is float and b.__class__ is float:
                return pyop(a, b)  # with a NaN every one of these gives False
            return _cmp(op, a, b)

        return compare

    def e_index(self, n: A.Index, env: Env) -> Callable:
        idx = self.ex(n.index, env)
        kind, ref = n.obj.ref
        ds = self.ds

        def offset() -> int | None:
            x = num(idx())
            if x != x:
                return None
            if x < 0:
                fail("HISTORY OFFSET CANNOT BE NEGATIVE")
            k = math.floor(x) if x != math.inf else LOOKBACK + 1
            if k > LOOKBACK:
                fail(f"LOOKBACK TOO FAR (MAX {LOOKBACK} BARS)")
            return int(k)

        if kind == "builtin":
            name = ref.name

            def read_series():
                k = offset()
                return NA if k is None else series_at(ds, name, ds.i - k)

            return read_series
        v = env.get(ref)

        def read_var():
            k = offset()
            if k is None:
                return NA
            if k == 0:
                return v.cur
            j = ds.i - k
            return NA if j < 0 else v.hist[j]

        return read_var

    # ------------------------------------------------------------------------------------------ calls

    def e_call(self, n: A.Call, env: Env) -> Callable:
        kind, ref = n.ref
        if kind == "func":
            return self.user_call(n, ref, env)
        if kind == "method":
            return self.method_call(n, ref, env)
        b = ref
        sp = self.special.get(b.name)
        if sp is not None:
            return sp(n, env)
        if b.name in TA_FACTORIES:
            return self.ta_call(n, b, env)
        fn = self.fns[b.name]
        fs = [self.argf(node, (b.params[i][1] if i < len(b.params) else None), env) for i, node in enumerate(n.bound)]
        return self.apply(fn, fs)

    @staticmethod
    def apply(fn: Callable, fs: list[Callable]) -> Callable:
        """A closure calling `fn` with the values of the argument closures (specialised for short argument lists)."""
        k = len(fs)
        if k == 0:
            return lambda: fn()
        if k == 1:
            f1 = fs[0]
            return lambda: fn(f1())
        if k == 2:
            f1, f2 = fs
            return lambda: fn(f1(), f2())
        if k == 3:
            f1, f2, f3 = fs
            return lambda: fn(f1(), f2(), f3())
        return lambda: fn(*[f() for f in fs])

    def ta_call(self, n: A.Call, b, env: Env) -> Callable:
        state = TA_FACTORIES[b.name](self.ds)  # this call site's own memory
        fs = [self.argf(node, b.params[i][1], env) for i, node in enumerate(n.bound)]
        return self.apply(state.step, fs)

    def user_call(self, n: A.Call, fd: A.FuncDef, env: Env) -> Callable:
        loc: dict = {}
        env2 = Env(loc, self.glob)
        # Arguments are evaluated in the caller's scope, defaults in an empty one (built-ins only).
        argfs = []
        for p, node in zip(fd.params, n.bound, strict=True):
            argfs.append(self.ex(node, env) if node is not None else self.ex(p.default, Env({}, self.glob)))
        pvars = [self.new_var(p.decl, env2) for p in fd.params]
        body = self.func_body(fd, env2)

        def call():
            vals = [f() for f in argfs]
            for pv, x in zip(pvars, vals, strict=True):
                pv.cur = x
            return body()

        return call

    def func_body(self, fd: A.FuncDef, env: Env) -> Callable:
        stmts = fd.body
        pre = [c for c in (self.stmt(s, env) for s in stmts[:-1]) if c is not None]
        last = stmts[-1]
        rt = self.rt
        if isinstance(last, A.ExprStmt):
            self.count(last)
            lastf = self.ex(last.expr, env)
        else:
            sf = self.stmt(last, env)
            var = env.get(last.decl) if isinstance(last, A.Assign) else None

            def lastf():
                if sf is not None:
                    sf()
                return var.cur if var is not None else NA

        def body():
            for s in pre:
                s()
            rt.steps += 1
            if rt.steps > rt.cap:
                rt.limit()
            return lastf()

        return body

    def method_call(self, n: A.Call, name: str, env: Env) -> Callable:
        recv = self.ex(n.callee.obj, env)
        fs = [self.ex(a.value, env) for a in n.args]
        fns = self.fns

        def call():
            r = recv()
            c = r.__class__
            prefix = "array" if c is Arr else "map" if c is MapObj else c.kind if hasattr(c, "kind") else None
            fn = fns.get(f"{prefix}.{name}") if prefix else None
            if fn is None:
                fail(f"{name.upper()} IS NOT A METHOD OF THIS VALUE")
            try:
                return fn(r, *[f() for f in fs])
            except TypeError:
                return fail(f"WRONG NUMBER OF ARGUMENTS FOR {name.upper()}")

        return call

    # ------------------------------------------------------------------------------------------ script header and inputs

    def c_indicator(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        self.title = str(const_eval(b[0]))
        self.overlay = bool(const_eval(b[1])) if b[1] is not None else False
        if b[2] is not None:
            m = num(const_eval(b[2]))
            if m != m or m < 0:
                self.cerr("MAX_LABELS MUST BE 0 OR MORE", b[2])
            cap = int(min(m, LIMITS["drawingsPerKind"]))
            self.max_labels = cap
            for dl in (self.labels, self.lines, self.boxes, self.tables):
                dl.cap = cap
        return lambda: None

    def c_input(self, n: A.Call, env: Env) -> Callable:
        b, kind = n.bound, n.ref[1].name[6:]
        params = n.ref[1].params
        vals = []
        for i, node in enumerate(b):
            if node is None:
                vals.append(default_const(params[i][1]) if params[i][1] is not None else NA)
            elif kind == "source" and i == 0:
                vals.append(node.name)  # the series name
            else:
                vals.append(const_eval(node))
        defval, title = vals[0], vals[1]
        if kind == "source" and defval not in SOURCES:
            self.cerr("INPUT.SOURCE NEEDS A PRICE SERIES", b[0])
        info = {"kind": kind, "title": title, "defval": defval, "min": None, "max": None, "step": None, "options": None}
        raw = self.overrides.get(title, defval)
        error: str | None = None
        value = defval
        if kind in ("int", "float"):
            lo, hi, step = vals[2], vals[3], vals[4]
            info.update(min=_clean(lo), max=_clean(hi), step=_clean(step))
            if raw.__class__ is bool or not isinstance(raw, int | float):
                error = f"INPUT {title.upper()} NEEDS A NUMBER"
            else:
                x = float(raw)
                if x != x:
                    error = f"INPUT {title.upper()} NEEDS A NUMBER"
                else:
                    if lo == lo:
                        x = max(x, lo)
                    if hi == hi:
                        x = min(x, hi)
                    value = float(math.floor(x + 0.5)) if kind == "int" else x
        elif kind == "bool":
            value = bool(raw)
        elif kind == "string":
            opts = vals[2] if isinstance(vals[2], tuple) else None
            info["options"] = list(opts) if opts else None
            if raw.__class__ is not str:
                error = f"INPUT {title.upper()} NEEDS TEXT"
            elif opts and raw not in opts:
                error = f"{raw!r} IS NOT ONE OF THE OPTIONS OF INPUT {title.upper()}"
            else:
                value = raw
        elif kind == "source":
            if raw not in SOURCES:
                error = f"INPUT {title.upper()} NEEDS A PRICE SERIES"
            else:
                value = SourceName(raw)
        elif kind == "symbol":
            if raw.__class__ is not str:
                error = f"INPUT {title.upper()} NEEDS TEXT"
            else:
                value = raw
        else:  # timeframe
            tf = normalize(raw) if raw.__class__ is str else None
            if tf is None:
                error = f"UNKNOWN TIMEFRAME FOR INPUT {title.upper()}"
            else:
                value = tf
        self.input_defs.append(info)
        self.last_input = value
        if error is not None:
            msg = error

            def bad():
                fail(msg)

            return bad
        if isinstance(value, SourceName):
            return series_getter(self.ds, value.name)
        return lambda: value

    # ------------------------------------------------------------------------------------------ request

    def c_request(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        parts = []
        for node in b[:2]:
            if isinstance(node, A.Str):
                parts.append(node.value)
            else:
                v = self.input_vals.get(node.ref[1])
                parts.append(v if v.__class__ is str else "")
        sym, tf_raw = parts
        tf = normalize(tf_raw)
        if tf is None:
            self.cerr(f"UNKNOWN TIMEFRAME {tf_raw.upper()}", b[1])
        rds = DS()
        saved = self.ds
        self.ds = rds
        ef = self.ex(b[2], env)
        self.ds = saved
        site = ReqSite(sym, tf, rds, ef, n)
        self.requests.append(site)
        main = self.main_ds
        return lambda: site.series[main.i]

    # ------------------------------------------------------------------------------------------ outputs

    def c_plot(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        title = self.const_arg(b[1], '""')
        style = self.const_arg(b[4], '"line"')
        if style not in PLOT_STYLES:
            self.cerr(f"UNKNOWN PLOT STYLE {str(style).upper()}", b[4])
        sf = self.ex(b[0], env)
        cf = self.ex(b[2], env) if b[2] is not None else None
        out = self.new_out("plot", n, str(title))
        out.style = style
        out.linewidth = num(self.const_arg(b[3], "1"))
        out.values = [None] * self.n
        out.cols = [None] * self.n
        handle = PlotHandle(out.index)
        ds = self.main_ds
        values, cols = out.values, out.cols

        def run():
            x = sf()
            i = ds.i
            if x.__class__ is not float:
                x = num(x) if x.__class__ in (bool, int) else fail("PLOT NEEDS A NUMBER")
            values[i] = None if x != x else x
            if cf is not None:
                cols[i] = _colour(cf())
            return handle

        return run

    def c_hline(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        title = self.const_arg(b[1], '""')
        out = self.new_out("hline", n, str(title))
        out.linestyle = str(self.const_arg(b[3], '"dashed"'))
        pf = self.ex(b[0], env)
        cf = self.ex(b[2], env) if b[2] is not None else None

        def run():
            if not out.fixed:
                out.fixed = True
                p = num(pf())
                out.price = None if p != p else p
                out.color = _colour(cf()) if cf is not None else None

        return run

    def c_fill(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        f1, f2 = self.ex(b[0], env), self.ex(b[1], env)
        cf = self.ex(b[2], env) if b[2] is not None else None
        out = self.new_out("fill", n)
        out.cols = [None] * self.n
        cols = out.cols
        ds = self.main_ds

        def run():
            h1, h2 = f1(), f2()
            if h1.__class__ is not PlotHandle or h2.__class__ is not PlotHandle:
                fail("FILL NEEDS TWO PLOTS")
            out.a, out.b = h1.index, h2.index
            if cf is not None:
                cols[ds.i] = _colour(cf())

        return run

    def c_bgcolor(self, n: A.Call, env: Env) -> Callable:
        cf = self.ex(n.bound[0], env)
        out = self.new_out("bgcolor", n)
        out.cols = [None] * self.n
        cols = out.cols
        ds = self.main_ds

        def run():
            cols[ds.i] = _colour(cf())

        return run

    def c_plotshape(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        title = str(self.const_arg(b[1], '""'))
        style = self.const_arg(b[2], '"triangleup"')
        loc = self.const_arg(b[3], '"abovebar"')
        txt = str(self.const_arg(b[5], '""'))
        if style not in SHAPE_STYLES:
            self.cerr(f"UNKNOWN SHAPE STYLE {str(style).upper()}", b[2])
        if loc not in SHAPE_LOCATIONS:
            self.cerr(f"UNKNOWN SHAPE LOCATION {str(loc).upper()}", b[3])
        cond = self.ex(b[0], env)
        cf = self.ex(b[4], env) if b[4] is not None else None
        out = self.new_out("shape", n, title)
        out.style, out.location, out.text = style, loc, txt
        out.values = [None] * self.n
        out.cols = [None] * self.n
        values, cols = out.values, out.cols
        ds = self.main_ds
        absolute = loc == "absolute"

        def run():
            v = cond()
            i = ds.i
            if truthy(v):
                values[i] = v if (absolute and v.__class__ is float) else 1.0
            if cf is not None:
                cols[i] = _colour(cf())  # evaluated on every bar, so a constant colour stays one `color`

        return run

    def c_alert(self, n: A.Call, env: Env) -> Callable:
        mf = self.ex(n.bound[0], env)
        last = [-1]
        ds = self.main_ds
        alerts = self.alerts
        cap = LIMITS["alerts"]

        def run():
            i = ds.i
            if last[0] != i:
                last[0] = i
                alerts.append({"bar": i, "message": text(mf())})
                if len(alerts) > cap:
                    del alerts[0]

        return run

    def c_alertcondition(self, n: A.Call, env: Env) -> Callable:
        b = n.bound
        cf = self.ex(b[0], env)
        entry = {"title": str(const_eval(b[1])), "message": str(self.const_arg(b[2], '""')), "values": [0] * self.n}
        self.conds.append(entry)
        values = entry["values"]
        ds = self.main_ds

        def run():
            values[ds.i] = 1 if truthy(cf()) else 0

        return run

    # ------------------------------------------------------------------------------------------ drawings

    def c_table_new(self, n: A.Call, env: Env) -> Callable:
        fs = [self.ex(x, env) for x in n.bound]
        tables = self.tables

        def run():
            pos, cols, rows = fs[0](), num(fs[1]()), num(fs[2]())
            if pos not in TABLE_POSITIONS:
                fail("UNKNOWN TABLE POSITION")
            if not (cols >= 1 and rows >= 1) or cols > 100 or rows > 100:
                fail("A TABLE NEEDS 1 TO 100 COLUMNS AND ROWS")
            # One table per screen corner (same rule as the TS engine): a new table at a position replaces the old one
            # there, so `t = table.new(...)` run on every bar still shows one table, the last bar's.
            for old in tables.live():
                if old.position == pos:
                    tables.kill(old)
            t = Table(pos, int(cols), int(rows))
            tables.add(t)
            return t

        return run

    def _install_drawing_ops(self) -> None:
        """label.* / line.* / box.* / table.cell, as plain functions of evaluated arguments (also reachable as methods)."""
        fns = self.fns

        def label_new(x, y, txt="", color=NA, style="label_down", textcolor=NA):
            h = Label(num(x), num(y), txt if txt.__class__ is str else text(txt), _colour(color), style, _colour(textcolor))
            self.labels.add(h)
            return h

        def line_new(x1, y1, x2, y2, color=NA, width=1.0):
            h = Line(num(x1), num(y1), num(x2), num(y2), _colour(color), num(width))
            self.lines.add(h)
            return h

        def box_new(left, top, right, bottom, color=NA, bgcolor=NA):
            h = Box(num(left), num(top), num(right), num(bottom), _colour(color), _colour(bgcolor))
            self.boxes.add(h)
            return h

        def deleter(cls, what):
            def delete(h):
                d = _drawing(h, cls, what)
                if d is not None and d.owner is not None:
                    d.owner.kill(d)
                return NA

            return delete

        def label_set_text(h, txt):
            d = _drawing(h, Label, "LABEL")
            if d is not None:
                d.text = txt if txt.__class__ is str else text(txt)
            return NA

        def label_set_xy(h, x, y):
            d = _drawing(h, Label, "LABEL")
            if d is not None:
                d.x, d.y = num(x), num(y)
            return NA

        def line_set_xy2(h, x, y):
            d = _drawing(h, Line, "LINE")
            if d is not None:
                d.x2, d.y2 = num(x), num(y)
            return NA

        def table_cell(t, column, row, txt="", color=NA, bgcolor=NA):
            d = _drawing(t, Table, "TABLE")
            if d is None:
                return NA
            c, r = num(column), num(row)
            if not (0 <= c < d.columns and 0 <= r < d.rows) or c != math.floor(c) or r != math.floor(r):
                fail("TABLE CELL OUT OF RANGE")
            d.cells[(int(r), int(c))] = {
                "column": int(c), "row": int(r), "text": txt if txt.__class__ is str else text(txt),
                "color": _colour(color), "bgcolor": _colour(bgcolor),
            }
            return NA

        fns.update(
            {
                "label.new": label_new,
                "label.delete": deleter(Label, "LABEL"),
                "label.set_text": label_set_text,
                "label.set_xy": label_set_xy,
                "line.new": line_new,
                "line.delete": deleter(Line, "LINE"),
                "line.set_xy2": line_set_xy2,
                "box.new": box_new,
                "box.delete": deleter(Box, "BOX"),
                "table.cell": table_cell,
            }
        )


class SourceName:
    """The value of an `input.source`: which bar series was chosen."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name


# ---------------------------------------------------------------------------------------------------- running


def _floats(values) -> list[float]:
    return [NA if x is None else float(x) for x in values]


def normalise_cols(cols: dict) -> dict:
    """Bars as a dict of float lists with keys o h l c v t. `v` and `t` may be missing (then they are all na)."""
    for k in "ohlc":
        if k not in cols:
            raise ValueError(f"bars need the key {k!r}")
    n = len(cols["c"])
    out = {}
    for k in "ohlcvt":
        if k in cols and cols[k] is not None:
            out[k] = _floats(cols[k])
        else:
            out[k] = [NA] * n
        if len(out[k]) != n:
            raise ValueError("every bar list needs the same length")
    return out


def _align(chart_t: list[float], other_t: list[float], vals: list, other_tf: str | None, chart_tf: str | None) -> list:
    """Spec 1.5, no look-ahead: on chart bar i take the newest other bar that had closed by the close of bar i."""
    n, m = len(chart_t), len(other_t)
    if any(t != t for t in chart_t) or any(t != t for t in other_t):
        fail("REQUEST NEEDS BAR TIMES")
    diffs = [chart_t[i + 1] - chart_t[i] for i in range(n - 1)]
    median = statistics.median(diffs) if diffs else (seconds(chart_tf) if chart_tf else 0.0)
    # When another bar closes: when the next one opens, or (for the newest) its own start plus its length.
    other_diffs = [other_t[i + 1] - other_t[i] for i in range(m - 1)]
    fallback = statistics.median(other_diffs) if other_diffs else median
    ends = [other_t[k + 1] if k + 1 < m else (bar_end(other_t[k], other_tf) if other_tf else other_t[k] + fallback) for k in range(m)]
    out = []
    k = -1
    for i in range(n):
        close_time = chart_t[i] + (diffs[i] if i < n - 1 else median)
        while k + 1 < m and ends[k + 1] <= close_time:
            k += 1
        out.append(vals[k] if k >= 0 else NA)
    return out


def prepare_requests(b: Builder, cols: dict, requests: dict | None, chart_timeframe: str | None) -> None:
    ctf = normalize(chart_timeframe) if chart_timeframe else None
    for site in b.requests:
        try:
            sym, tf = site.sym, site.tf
            if tf and ctf and seconds(tf) < seconds(ctf):
                fail(f"REQUEST TIMEFRAME {tf} IS SHORTER THAN THE CHART'S {ctf}")
            aligned = False
            if sym == "" and (tf == "" or tf == ctf):
                other, other_tf, aligned = cols, ctf, True
            elif sym == "":
                if any(t != t for t in cols["t"]):
                    fail("REQUEST NEEDS BAR TIMES")
                other, other_tf = resample(cols, tf), tf
            else:
                key = f"{sym}|{tf}"
                if not requests or key not in requests:
                    fail(f"NO DATA FOR REQUEST {key}")
                other, other_tf = normalise_cols(requests[key]), tf or ctf
            site.ds.load(other)
            vals = []
            for k in range(site.ds.n):
                site.ds.i = k
                vals.append(site.ef())
            site.series = vals if aligned else _align(cols["t"], other["t"], vals, other_tf, ctf)
        except ScriptRuntimeError as e:
            if e.line is None:
                e.line, e.col = site.node.line, site.node.col
            raise


def execute(stmts: list, cols: dict, overrides: dict | None, requests: dict | None, chart_timeframe: str | None) -> dict:
    """Run a checked script over `cols` (see normalise_cols) and return the result dict of spec 2."""
    started = _time.perf_counter()
    n = len(cols["c"])
    ds = DS()
    ds.load(cols)
    b = Builder(stmts, n, overrides, ds)
    error = None
    try:
        main = b.build()
    except RecursionError:
        raise ScriptCompileError([err("EXPRESSION IS TOO DEEP", 1, 1)]) from None
    rt = b.rt
    done = 0
    try:
        prepare_requests(b, cols, requests, chart_timeframe)
        reset, hist = b.reset_vars, b.hist_vars
        for i in range(n):
            ds.i = i
            for v in reset:
                v.cur = NA
            rt.cap = min(RUN_STEP_CAP, rt.steps + BAR_STEP_CAP)
            try:
                main()
            except ScriptRuntimeError as e:
                error = {"msg": e.msg, "line": e.line or 0, "col": e.col or 0, "bar": i}
            except RecursionError:
                error = {"msg": "EXPRESSION IS TOO DEEP", "line": 0, "col": 0, "bar": i}
            except (TypeError, ValueError, ArithmeticError, IndexError, KeyError, AttributeError) as e:
                error = {"msg": f"INTERNAL ERROR ({type(e).__name__}: {e})", "line": 0, "col": 0, "bar": i}
            if error is not None:
                _undo_bar(b, i)
                break
            for v in hist:
                v.hist.append(v.cur)
            done = i + 1
    except ScriptRuntimeError as e:  # a request failed before the first bar
        error = {"msg": e.msg, "line": e.line or 0, "col": e.col or 0, "bar": 0}
        _undo_bar(b, 0)
    result = {
        "plots": [o.finish() for o in b.outs],
        "drawings": {
            "labels": [h.out() for h in b.labels.live()],
            "lines": [h.out() for h in b.lines.live()],
            "boxes": [h.out() for h in b.boxes.live()],
            "tables": [h.out() for h in b.tables.live()],
        },
        "alerts": list(b.alerts),
        "conditions": [dict(c) for c in b.conds],
        "stats": {"steps": rt.steps, "ms": (_time.perf_counter() - started) * 1000.0, "bars": done},
    }
    if error is not None:
        result["error"] = error
    return result


def _undo_bar(b: Builder, i: int) -> None:
    """A run stopped in bar `i`: forget what that bar wrote, so the outputs hold only complete bars."""
    for o in b.outs:
        if o.values is not None and i < len(o.values):
            o.values[i] = None
        if o.cols is not None and i < len(o.cols):
            o.cols[i] = None
    for c in b.conds:
        if i < len(c["values"]):
            c["values"][i] = 0
    while b.alerts and b.alerts[-1]["bar"] == i:
        b.alerts.pop()


def validate(stmts: list) -> Builder:
    """Compile once with no bars, only to find compile errors and to read the script's metadata."""
    b = Builder(stmts, 0, None)
    try:
        b.build()
    except RecursionError:
        raise ScriptCompileError([err("EXPRESSION IS TOO DEEP", 1, 1)]) from None
    return b


__all__ = ["BY_NAME", "NotConst", "execute", "normalise_cols", "validate"]
