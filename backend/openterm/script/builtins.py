"""Values and the plain (stateless) built-in functions of OpenTerm Script.

Value model (all Python, nothing fancy):
  number  -> float, with `na` as NaN          bool   -> bool           text and colour -> str
  array   -> `Arr` (a list)                   map    -> `MapObj` (a dict)
  tuple   -> tuple (what `[a, b] = f()` unpacks)

The functions in `make_pure` take already-evaluated arguments and return a value. Anything that needs the bar data, the
call site's own memory or the output lists (ta.*, plot, label.new ...) lives in `ta.py` and `interp.py` instead.
"""

# `x != x` is the standard test for NaN (na) in Python and JavaScript; ruff's PLR0124 would reject it.
# ruff: noqa: PLR0124

from __future__ import annotations

import math
import weakref
from collections.abc import Callable

from .errors import ScriptRuntimeError
from .names import COLORS, LIMITS

NA = float("nan")
INF = float("inf")


def fail(msg: str):
    raise ScriptRuntimeError(msg)


# --------------------------------------------------------------------------------------------------- basic values


def num(v) -> float:
    """The value as a float, or a runtime error. A bool counts as 1 or 0."""
    c = v.__class__
    if c is float:
        return v
    if c is bool:
        return 1.0 if v else 0.0
    if c is int:
        return float(v)
    return fail("EXPECTED A NUMBER")


def truthy(v) -> bool:
    """Spec 1.2: a number is true when it is not na and not 0; `na` is false."""
    c = v.__class__
    if c is bool:
        return v
    if c is float:
        return v == v and v != 0.0
    if c is str:
        return len(v) > 0
    return v is not None


def is_na(v) -> bool:
    return v.__class__ is float and v != v


def text(v, decimals: float = -1.0) -> str:
    """`str.tostring`: shortest round-trip number text (whole numbers without `.0`), or a fixed number of decimals."""
    c = v.__class__
    if c is str:
        return v
    if c is bool:
        return "true" if v else "false"
    if c is float or c is int:
        v = float(v)
        if v != v:
            return "na"
        if v in (INF, -INF):
            return "Infinity" if v > 0 else "-Infinity"
        d = num(decimals)
        if d >= 0:
            return f"{v:.{int(d)}f}"
        if v == math.floor(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return fail("CANNOT TURN THIS VALUE INTO TEXT")


# --------------------------------------------------------------------------------------------------- arrays and maps


class Arr(list):
    """A script array. A list subclass so it can be weakly referenced (see Tracker)."""


class MapObj(dict):
    """A script map. Keys are numbers or text."""


class Tracker:
    """Counts the elements held by live arrays (or maps) and enforces the cap of spec 1.7.

    Arrays that the script drops are not subtracted one by one: when the running count goes over the cap we recount only the
    arrays that are still alive (weak references), and fail only if the live total is really over the cap.
    """

    def __init__(self, cap: int):
        self.cap = cap
        self.count = 0
        self.refs: list[weakref.ref] = []

    def register(self, obj) -> None:
        self.refs.append(weakref.ref(obj))
        if len(self.refs) % 4096 == 0:
            self.refs = [r for r in self.refs if r() is not None]
        self.add(len(obj))

    def add(self, k: int) -> None:
        self.count += k
        if self.count > self.cap:
            live_refs = [r for r in self.refs if r() is not None]
            self.refs = live_refs
            self.count = sum(len(r()) for r in live_refs if r() is not None)
            if self.count > self.cap:
                fail("MEMORY LIMIT")


def as_arr(v) -> Arr:
    if v.__class__ is not Arr:
        fail("EXPECTED A LIST")
    return v


def as_map(v) -> MapObj:
    if v.__class__ is not MapObj:
        fail("EXPECTED A MAP")
    return v


def _index(a: Arr, i) -> int:
    k = num(i)
    if k != k or k < 0 or k >= len(a) or k != math.floor(k):
        fail("LIST INDEX OUT OF RANGE")
    return int(k)


def _numbers(a: Arr) -> list[float]:
    """The numbers of an array, skipping na."""
    out = []
    for x in a:
        f = num(x)
        if f == f:
            out.append(f)
    return out


def _key(k):
    if k.__class__ is bool:
        return fail("A MAP KEY MUST BE A NUMBER OR TEXT")
    if k.__class__ is float:
        if k != k:
            fail("A MAP KEY CANNOT BE NA")
        return k
    if k.__class__ is str:
        return k
    return fail("A MAP KEY MUST BE A NUMBER OR TEXT")


# --------------------------------------------------------------------------------------------------- colours


def _hex_alpha(transp: float) -> str:
    """Transparency 0 (solid) to 100 (invisible) as the two hex digits of an alpha channel ("" when fully solid)."""
    t = min(100.0, max(0.0, transp))
    a = int((100.0 - t) * 255.0 / 100.0 + 0.5)
    return "" if a >= 255 else f"{a:02x}"


def color_new(c, transp) -> str | float:
    if is_na(c):
        return NA
    if c.__class__ is not str or not c.startswith("#") or len(c) not in (7, 9):
        fail("EXPECTED A COLOUR")
    t = num(transp)
    if t != t:
        return NA
    return c[:7] + _hex_alpha(t)


def color_rgb(r, g, b, transp=0.0) -> str | float:
    parts = []
    for v in (r, g, b):
        x = num(v)
        if x != x:
            return NA
        parts.append(int(min(255.0, max(0.0, x)) + 0.5))
    t = num(transp)
    if t != t:
        return NA
    return "#{:02x}{:02x}{:02x}".format(*parts) + _hex_alpha(t)


# --------------------------------------------------------------------------------------------------- math


def _safe(fn: Callable[[float], float]) -> Callable[[float], float]:
    """Wrap a one-argument math function so na stays na and a domain error gives na (like a spreadsheet), not a crash."""

    def run(x) -> float:
        x = num(x)
        if x != x:
            return NA
        try:
            return fn(x)
        except (ValueError, OverflowError):
            return NA

    return run


def _ceil(x: float) -> float:
    return x if x in (INF, -INF) else float(math.ceil(x))


def _floor(x: float) -> float:
    return x if x in (INF, -INF) else float(math.floor(x))


def _round(x, digits=0.0) -> float:
    x = num(x)
    d = num(digits)
    if x != x or d != d or x in (INF, -INF):
        return NA if (x != x or d != d) else x
    s = 10.0 ** int(d)
    r = math.floor(abs(x) * s + 0.5) / s
    return r if x >= 0 else -r


def _sqrt(x: float) -> float:
    return math.sqrt(x) if x >= 0 else NA


def _log(x: float) -> float:
    if x == 0:
        return -INF
    return math.log(x) if x > 0 else NA


def _log10(x: float) -> float:
    if x == 0:
        return -INF
    return math.log10(x) if x > 0 else NA


def _exp(x: float) -> float:
    try:
        return math.exp(x)
    except OverflowError:
        return INF


def _pow(x, y) -> float:
    x, y = num(x), num(y)
    if x != x or y != y:
        return NA
    try:
        return math.pow(x, y)
    except OverflowError:
        return INF
    except (ValueError, ZeroDivisionError):
        return INF if x == 0 else NA


def _sign(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def _nums_or_na(args) -> list[float] | None:
    out = [num(a) for a in args]
    return None if any(v != v for v in out) else out


def _max(*args) -> float:
    v = _nums_or_na(args)
    return NA if v is None else max(v)


def _min(*args) -> float:
    v = _nums_or_na(args)
    return NA if v is None else min(v)


def _avg(*args) -> float:
    v = _nums_or_na(args)
    return NA if v is None else sum(v) / len(v)


# --------------------------------------------------------------------------------------------------- the table


def make_pure(arrays: Tracker, maps: Tracker) -> dict[str, Callable]:
    """Every stateless built-in, by name, as a plain Python function of its (evaluated) arguments."""

    def new_array(items) -> Arr:
        a = Arr(items)
        arrays.register(a)
        return a

    # ---- arrays
    def a_new(size=0.0, init=NA):
        n = num(size)
        if n != n or n < 0:
            fail("LIST SIZE MUST BE 0 OR MORE")
        if n + arrays.count > arrays.cap:
            fail("MEMORY LIMIT")
        return new_array([init] * int(n))

    def a_push(a, v):
        as_arr(a).append(v)
        arrays.add(1)
        return NA

    def a_pop(a):
        as_arr(a)
        if not a:
            return NA
        arrays.add(-1)
        return a.pop()

    def a_shift(a):
        as_arr(a)
        if not a:
            return NA
        arrays.add(-1)
        return a.pop(0)

    def a_unshift(a, v):
        as_arr(a).insert(0, v)
        arrays.add(1)
        return NA

    def a_get(a, i):
        return as_arr(a)[_index(a, i)]

    def a_set(a, i, v):
        as_arr(a)[_index(a, i)] = v
        return NA

    def a_clear(a):
        arrays.add(-len(as_arr(a)))
        a.clear()
        return NA

    def a_sum(a):
        return float(sum(_numbers(as_arr(a))))

    def a_avg(a):
        v = _numbers(as_arr(a))
        return sum(v) / len(v) if v else NA

    def a_min(a):
        v = _numbers(as_arr(a))
        return min(v) if v else NA

    def a_max(a):
        v = _numbers(as_arr(a))
        return max(v) if v else NA

    def a_includes(a, v):
        return any(x == v for x in as_arr(a))

    def a_indexof(a, v):
        for i, x in enumerate(as_arr(a)):
            if x == v:
                return float(i)
        return -1.0

    def a_sort(a, descending=False):
        as_arr(a)
        missing = [x for x in a if is_na(x)]
        rest = [x for x in a if not is_na(x)]
        try:
            rest.sort(reverse=truthy(descending))
        except TypeError:
            fail("CANNOT SORT A MIX OF TEXT AND NUMBERS")
        a[:] = rest + missing
        return NA

    def a_reverse(a):
        as_arr(a).reverse()
        return NA

    # ---- maps
    def m_new():
        m = MapObj()
        maps.register(m)
        return m

    def m_put(m, k, v):
        as_map(m)
        k = _key(k)
        if k not in m:
            maps.add(1)
        m[k] = v
        return NA

    def m_get(m, k):
        return as_map(m).get(_key(k), NA)

    def m_contains(m, k):
        return _key(k) in as_map(m)

    def m_remove(m, k):
        as_map(m)
        k = _key(k)
        if k in m:
            del m[k]
            maps.add(-1)
        return NA

    def m_keys(m):
        return new_array(as_map(m).keys())

    def m_values(m):
        return new_array(as_map(m).values())

    # ---- text
    def s_length(s):
        if s.__class__ is not str:
            fail("EXPECTED TEXT")
        return float(len(s))

    def s_contains(s, part):
        if s.__class__ is not str or part.__class__ is not str:
            fail("EXPECTED TEXT")
        return part in s

    return {
        "na": is_na,
        "nz": lambda x, y=0.0: y if is_na(x) else x,
        "math.abs": _safe(abs),
        "math.ceil": _safe(_ceil),
        "math.floor": _safe(_floor),
        "math.round": _round,
        "math.sqrt": _safe(_sqrt),
        "math.pow": _pow,
        "math.exp": _safe(_exp),
        "math.log": _safe(_log),
        "math.log10": _safe(_log10),
        "math.max": _max,
        "math.min": _min,
        "math.avg": _avg,
        "math.sign": _safe(_sign),
        "color.new": color_new,
        "color.rgb": color_rgb,
        "str.tostring": text,
        "str.length": s_length,
        "str.contains": s_contains,
        "array.new": a_new,
        "array.from": lambda *vals: new_array(vals),
        "array.push": a_push,
        "array.pop": a_pop,
        "array.shift": a_shift,
        "array.unshift": a_unshift,
        "array.get": a_get,
        "array.set": a_set,
        "array.size": lambda a: float(len(as_arr(a))),
        "array.clear": a_clear,
        "array.sum": a_sum,
        "array.avg": a_avg,
        "array.min": a_min,
        "array.max": a_max,
        "array.includes": a_includes,
        "array.indexof": a_indexof,
        "array.sort": a_sort,
        "array.reverse": a_reverse,
        "map.new": m_new,
        "map.put": m_put,
        "map.get": m_get,
        "map.contains": m_contains,
        "map.remove": m_remove,
        "map.size": lambda m: float(len(as_map(m))),
        "map.keys": m_keys,
        "map.values": m_values,
    }


# Constants read without a call: `math.pi`, `color.red`.
VALUE_CONSTANTS: dict[str, object] = {"math.pi": math.pi, "math.e": math.e}
for _k, _v in COLORS.items():
    VALUE_CONSTANTS[f"color.{_k}"] = _v

ARRAY_CAP = LIMITS["arrayElements"]
MAP_CAP = LIMITS["mapEntries"]
