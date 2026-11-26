"""Custom fitness formulas for BT OPT (Phase 26 gap): `FIT=SHARPE-2*DD`, `FIT=CALMAR*MIN(1,TRADES/30)`.

A formula is a small arithmetic expression over a run's metrics. It is read by Python's `ast` parser (which only BUILDS a tree,
nothing runs) and then turned into closures by walking the tree and accepting ONLY the node kinds listed below. There is no
`eval`, no attribute access, no subscripts, no strings: anything else is refused with a plain message. Pure Python, no pandas
or numpy, so the server process (route validation) may import it.

Names (case does not matter; each is one metric of the run):
  SHARPE SORTINO CALMAR   risk-adjusted return ratios
  ANNUAL                  annualised return        RETURN  total return        NET  final account value
  DD                      depth of the worst fall from a peak, as a POSITIVE number (0.25 = 25%)
  PF                      profit factor            WIN     win rate            TRADES  number of trades
Operators: + - * / ** and unary minus. Functions: ABS(x) SQRT(x) LOG(x) MIN(a,b,..) MAX(a,b,..). Numbers: 12, 0.5.
A run whose formula cannot be computed (a missing metric, divide by zero, SQRT of a negative) gets NO fitness (None), never a
made-up number: the table shows it as "NO FITNESS".
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

MAX_LEN = 120  # characters; also keeps ast.parse far from its recursion limit

# formula name -> (metric key in the run's metrics, sign fix). DD is the one derived name: abs(max_drawdown).
NAMES: dict[str, str] = {
    "SHARPE": "sharpe", "SORTINO": "sortino", "CALMAR": "calmar", "ANNUAL": "annual_return", "RETURN": "total_return",
    "NET": "final_value", "DD": "max_drawdown", "PF": "profit_factor", "WIN": "win_rate", "TRADES": "trade_count",
}
# Names a walk-forward slice of bar returns cannot supply (trades are not sliced), so WF refuses a formula that uses them.
NOT_IN_SLICES = frozenset({"WIN", "TRADES"})

_NAN = math.nan


class FitError(ValueError):
    """A formula the parser refuses; the message is shown to the user as is."""


def _need(fn: str, args: list, lo: int, hi: int | None = None) -> None:
    if len(args) < lo or (hi is not None and len(args) > hi):
        want = f"{lo}" if hi == lo else (f"{lo} OR MORE" if hi is None else f"{lo}-{hi}")
        raise FitError(f"{fn}() TAKES {want} ARGUMENT{'S' if want != '1' else ''}")


def _fin(v: float) -> float:
    return v if math.isfinite(v) else _NAN


def _div(a: float, b: float) -> float:
    return _NAN if b == 0 else a / b


def _pow(a: float, b: float) -> float:
    try:
        return _fin(math.pow(a, b))  # math.pow never returns a complex number (the ** operator would)
    except (ValueError, OverflowError, ZeroDivisionError):
        return _NAN


def _sqrt(a: float) -> float:
    return math.sqrt(a) if a >= 0 else _NAN


def _log(a: float) -> float:
    return math.log(a) if a > 0 else _NAN


def _anynan(vals: tuple[float, ...]) -> bool:
    return any(math.isnan(v) for v in vals)


# NaN poisons MIN / MAX (Python's own min() ignores a leading NaN), so a missing metric always means "no fitness".
FUNCS: dict[str, tuple[Callable[..., float], int, int | None]] = {
    "ABS": (abs, 1, 1), "SQRT": (_sqrt, 1, 1), "LOG": (_log, 1, 1),
    "MIN": (lambda *v: _NAN if _anynan(v) else min(v), 2, 8), "MAX": (lambda *v: _NAN if _anynan(v) else max(v), 2, 8),
}


@dataclass(frozen=True)
class Fit:
    """A compiled formula: `text` as the user wrote it (upper-cased), `names` it reads, `run(values)` to score one run."""
    text: str
    names: frozenset[str]
    _fn: Callable[[Mapping[str, float]], float]

    def run(self, values: Mapping[str, float]) -> float:
        """Score one run. `values` maps formula NAMES (SHARPE, DD, ...) to numbers; a name that is absent or not finite
        makes the result NaN."""
        try:
            return _fin(float(self._fn(values)))
        except (ArithmeticError, ValueError):
            return _NAN

    def from_metrics(self, metrics: Mapping[str, object]) -> float:
        """Score one run from its metrics dict (keys like `sharpe`, `max_drawdown`; None allowed)."""
        values = {}
        for name in self.names:
            v = metrics.get(NAMES[name])
            values[name] = (abs(v) if name == "DD" else float(v)) if isinstance(v, int | float) and math.isfinite(v) else _NAN
        return self.run(values)


def _build(node: ast.AST, names: set[str]) -> Callable[[Mapping[str, float]], float]:
    if isinstance(node, ast.Expression):
        return _build(node.body, names)
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise FitError("ONLY NUMBERS, NAMES AND + - * / ** ( ) ARE ALLOWED")
        c = float(v)
        return lambda _vals: c
    if isinstance(node, ast.Name):
        name = node.id.upper()
        if name not in NAMES:
            raise FitError(f"UNKNOWN NAME {node.id.upper()}: USE {' '.join(NAMES)}")
        names.add(name)
        return lambda vals: vals.get(name, _NAN)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        inner = _build(node.operand, names)
        return (lambda vals: -inner(vals)) if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.BinOp):
        a, b = _build(node.left, names), _build(node.right, names)
        op = node.op
        if isinstance(op, ast.Add):
            return lambda vals: a(vals) + b(vals)
        if isinstance(op, ast.Sub):
            return lambda vals: a(vals) - b(vals)
        if isinstance(op, ast.Mult):
            return lambda vals: a(vals) * b(vals)
        if isinstance(op, ast.Div):
            return lambda vals: _div(a(vals), b(vals))
        if isinstance(op, ast.Pow):
            return lambda vals: _pow(a(vals), b(vals))
        raise FitError("ONLY + - * / ** ARE ALLOWED")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise FitError("ONLY ABS SQRT LOG MIN MAX CAN BE CALLED, WITH PLAIN ARGUMENTS")
        fn = node.func.id.upper()
        if fn not in FUNCS:
            raise FitError(f"UNKNOWN FUNCTION {fn}: USE {' '.join(FUNCS)}")
        impl, lo, hi = FUNCS[fn]
        _need(fn, node.args, lo, hi)
        args = [_build(a, names) for a in node.args]
        return lambda vals: impl(*(a(vals) for a in args))
    raise FitError("ONLY NUMBERS, NAMES, + - * / ** AND ABS SQRT LOG MIN MAX ARE ALLOWED")


def parse(text: str) -> Fit:
    """Compile a fitness formula, or raise FitError with a message for the user. Safe on any input string."""
    s = str(text).strip().upper()
    if not s:
        raise FitError("FIT= NEEDS A FORMULA, E.G. FIT=SHARPE OR FIT=SHARPE-2*DD")
    if len(s) > MAX_LEN:
        raise FitError(f"FIT FORMULA IS TOO LONG (AT MOST {MAX_LEN} CHARACTERS)")
    try:
        tree = ast.parse(s, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise FitError(f"FIT FORMULA IS NOT VALID ARITHMETIC: {s}") from e
    names: set[str] = set()
    try:
        fn = _build(tree, names)
    except RecursionError as e:
        raise FitError("FIT FORMULA IS TOO DEEPLY NESTED") from e
    if not names:
        raise FitError("FIT FORMULA MUST USE AT LEAST ONE METRIC NAME: " + " ".join(NAMES))
    return Fit(s, frozenset(names), fn)
