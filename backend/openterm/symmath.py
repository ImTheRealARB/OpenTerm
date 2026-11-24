"""Symbol math (Phase 22): `AAPL/MSFT`, `ES=F-NQ=F`, `2*GLD-SLV` as a chartable series.

Pure Python (no pandas, no numpy: the server process must never import them), no `eval`. Three parts:

1. A small hand-written PARSER for `+ - * /`, unary minus, parentheses, numbers and symbols (`parse_formula`).
2. A ROUND-TRIP printer (`render`): the normalised formula that labels the chart. Parsing the printed text gives the same tree.
3. An ALIGNER (`align`) + evaluator (`apply`): each symbol (a "leg") brings its own bars; the legs are joined on the bar's
   time (INNER join: a bar must exist in every leg), then the formula is applied column by column.

THE MINUS RULE (the one genuinely ambiguous character)
-------------------------------------------------------
A Yahoo-style symbol may contain a hyphen (`BRK-B`, `BTC-USD`, `BAJAJ-AUTO.NS`), but `-` is also minus. The text has no brackets
around a symbol, so the parser needs one clear rule. A hyphen is PART OF THE SYMBOL only when ALL of these hold:

  * it touches a letter or digit on both sides (no space either side), and
  * the word to its left is not a plain number, has no `.` yet, has no hyphen yet and does not end in `=F` / `=X`
    (a finished futures / FX symbol such as `ES=F`, `EURUSD=X` never takes a hyphen), and
  * the word to its right is a TAIL that real symbols use: a single letter (share class: `BRK-B`), a currency or stablecoin
    code (`BTC-USD`, `ETH-EUR`, `SOL-USDT`), or a name with an exchange suffix (`AUTO.NS` in `BAJAJ-AUTO.NS`).

Every other hyphen is MINUS. So `ES=F-NQ=F`, `GLD-SLV`, `2*GLD-SLV`, `^GSPC-^IXIC`, `RELIANCE.NS-TCS.NS` are subtractions, while
`BRK-B`, `BTC-USD`, `BAJAJ-AUTO.NS` stay one symbol. A hyphen with a space on EITHER side is always minus: `BTC-USD - ETH-USD`
is one symbol minus another, and `V - A` (not the symbol `V-A`) is the way to subtract a one-letter symbol. When in doubt, put
spaces around the minus; the normalised label prints them (` - `) for exactly this reason.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from .symbols import CRYPTO_QUOTES, CURRENCIES


class SymMathError(ValueError):
    """A formula the parser or the aligner refuses. The message is shown to the user as written."""


MAX_FORMULA_CHARS = 200
MAX_LEGS = 6  # each leg is a history fetch: bound them
MAX_NODES = 64

# Characters a symbol or a number is made of (after upper-casing). `-` is handled separately by the minus rule above.
_WORD = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.=^&_")
_NUM = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)$")
_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9^=.&_-]*$")
_EXCHANGE_TAIL = re.compile(r"^[A-Z0-9&_]+\.[A-Z]{1,4}$")  # AUTO.NS, MOTORS.BO
# Quote currencies and stablecoins that follow a hyphen in a real symbol (BTC-USD, ETH-EUR, SOL-USDT, ETH-BTC).
_QUOTE_TAILS = frozenset(CURRENCIES) | frozenset(CRYPTO_QUOTES) | {"USDC", "DAI", "BUSD", "TUSD", "FDUSD", "USDP", "BTC", "ETH"}
# A text with none of these characters is a plain symbol: skip the tokenizer (the hot path for every normal history request).
_HINT = re.compile(r"[+*/()\s-]")


# --- the tree -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Sym:
    name: str


@dataclass(frozen=True)
class Neg:
    x: Any


@dataclass(frozen=True)
class Bin:
    op: str  # one of + - * /
    left: Any
    right: Any


Expr = Num | Sym | Neg | Bin


# --- tokenizer ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Tok:
    kind: str  # num | sym | op | lp | rp
    text: str


def _hyphen_joins(s: str, start: int, at: int) -> bool:
    """Is the `-` at s[at] part of the symbol that began at s[start]? (the minus rule in the module docstring)"""
    n = len(s)
    left = s[start:at]
    if at + 1 >= n or s[at + 1] not in _WORD:  # a space, an operator or the end follows: minus
        return False
    if "." in left or "-" in left or _NUM.match(left) or left.endswith(("=F", "=X")):
        return False
    end = at + 1
    while end < n and s[end] in _WORD:
        end += 1
    tail = s[at + 1:end]
    return (len(tail) == 1 and tail.isalpha()) or tail in _QUOTE_TAILS or bool(_EXCHANGE_TAIL.match(tail))


def _tokenize(text: str) -> list[_Tok]:
    s = text.strip().upper()
    if not s:
        raise SymMathError("EMPTY FORMULA")
    toks: list[_Tok] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
        elif ch in "+-*/":
            toks.append(_Tok("op", ch))  # a `-` seen HERE is minus: hyphens inside a symbol were eaten by the word scan below
            i += 1
        elif ch == "(":
            toks.append(_Tok("lp", ch))
            i += 1
        elif ch == ")":
            toks.append(_Tok("rp", ch))
            i += 1
        elif ch in _WORD:
            j = i
            while j < n:
                if s[j] in _WORD or (s[j] == "-" and j > i and s[j - 1] in _WORD and _hyphen_joins(s, i, j)):
                    j += 1
                else:
                    break
            word = s[i:j]
            if _NUM.match(word):
                toks.append(_Tok("num", word))
            elif _SYMBOL.match(word):
                toks.append(_Tok("sym", word))
            else:
                raise SymMathError(f"BAD SYMBOL {word}")
            i = j
        else:
            raise SymMathError(f"UNEXPECTED CHARACTER {ch!r}")
    return toks


# --- parser (recursive descent) -----------------------------------------------------------------
#   expr  := term (("+" | "-") term)*
#   term  := unary (("*" | "/") unary)*
#   unary := "-" unary | atom
#   atom  := NUMBER | SYMBOL | "(" expr ")"
# `*` and `/` bind tighter than `+` and `-`; each level groups left to right, so `A-B-C` is `(A-B)-C` and `A/B/C` is `(A/B)/C`.
class _Parser:
    def __init__(self, toks: list[_Tok], resolve: Callable[[str], str] | None):
        self.toks, self.at, self.resolve, self.nodes = toks, 0, resolve, 0

    def _peek(self) -> _Tok | None:
        return self.toks[self.at] if self.at < len(self.toks) else None

    def _take(self) -> _Tok:
        tok = self.toks[self.at]
        self.at += 1
        return tok

    def _node(self, node: Expr) -> Expr:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise SymMathError(f"FORMULA TOO LONG (MORE THAN {MAX_NODES} PARTS)")
        return node

    def parse(self) -> Expr:
        out = self._expr()
        if (extra := self._peek()) is not None:
            raise SymMathError(f"EXPECTED + - * / BEFORE {extra.text}" if extra.kind in ("num", "sym", "lp") else f"UNEXPECTED {extra.text}")
        return out

    def _expr(self) -> Expr:
        left = self._term()
        while (t := self._peek()) is not None and t.kind == "op" and t.text in "+-":
            self._take()
            left = self._node(Bin(t.text, left, self._term()))
        return left

    def _term(self) -> Expr:
        left = self._unary()
        while (t := self._peek()) is not None and t.kind == "op" and t.text in "*/":
            self._take()
            left = self._node(Bin(t.text, left, self._unary()))
        return left

    def _unary(self) -> Expr:
        t = self._peek()
        if t is not None and t.kind == "op" and t.text == "-":
            self._take()
            return self._node(Neg(self._unary()))
        return self._atom()

    def _atom(self) -> Expr:
        t = self._peek()
        if t is None:
            raise SymMathError("FORMULA ENDS EARLY: EXPECTED A SYMBOL OR NUMBER")
        if t.kind == "num":
            self._take()
            return self._node(Num(float(t.text)))
        if t.kind == "sym":
            self._take()
            return self._node(Sym(self.resolve(t.text) if self.resolve else t.text))
        if t.kind == "lp":
            self._take()
            inner = self._expr()
            if (c := self._peek()) is None or c.kind != "rp":
                raise SymMathError("MISSING )")
            self._take()
            return inner
        raise SymMathError(f"EXPECTED A SYMBOL OR NUMBER, GOT {t.text}")


def parse_formula(text: str, resolve: Callable[[str], str] | None = None) -> Expr | None:
    """The formula tree of `text`, or None when `text` is just one plain symbol (the caller then takes the ordinary path).

    `resolve` maps each symbol (`SPX` -> `^GSPC`), so the tree and the printed label use the names the data sources know.
    Raises SymMathError for a text that has operators but is not a valid formula (`AAPL/`, `(AAPL`, `2*3` with no symbol)."""
    if len(text) > MAX_FORMULA_CHARS:
        raise SymMathError(f"FORMULA OVER {MAX_FORMULA_CHARS} CHARACTERS")
    if not _HINT.search(text):
        return None
    toks = _tokenize(text)
    if len(toks) == 1 and toks[0].kind == "sym":
        return None  # `BRK-B`, `BTC-USD`, ` AAPL `: one symbol, not math
    expr = _Parser(toks, resolve).parse()
    found = legs(expr)
    if not found:
        raise SymMathError("A FORMULA NEEDS AT LEAST ONE SYMBOL")
    if len(found) > MAX_LEGS:
        raise SymMathError(f"AT MOST {MAX_LEGS} DIFFERENT SYMBOLS PER FORMULA (GOT {len(found)})")
    return expr


def is_formula(text: str) -> bool:
    """True for text that is a formula, or an operator-bearing text that fails to parse (it is still no symbol)."""
    try:
        return parse_formula(text) is not None
    except SymMathError:
        return True


def legs(expr: Expr) -> list[str]:
    """The distinct symbols of a formula, in the order they first appear."""
    out: dict[str, None] = {}

    def walk(e: Expr) -> None:
        if isinstance(e, Sym):
            out.setdefault(e.name)
        elif isinstance(e, Neg):
            walk(e.x)
        elif isinstance(e, Bin):
            walk(e.left)
            walk(e.right)

    walk(expr)
    return list(out)


# --- printer ------------------------------------------------------------------------------------
_PREC = {"+": 1, "-": 1, "*": 2, "/": 2}


def _prec(e: Expr) -> int:
    return _PREC[e.op] if isinstance(e, Bin) else 3 if isinstance(e, Neg) else 4


def render(e: Expr) -> str:
    """The normalised formula: spaces around `+` and `-` (so a hyphen is never ambiguous when it is read back), none around `*` and `/`,
    and brackets only where the grouping needs them. `parse_formula(render(x))` has the same tree as `x`."""
    if isinstance(e, Num):
        # Plain decimal, never 1e+06: the printed label is parsed again, and `+` would read as an operator.
        return f"{e.value:.12f}".rstrip("0").rstrip(".") or "0"
    if isinstance(e, Sym):
        return e.name
    if isinstance(e, Neg):
        inner = render(e.x)
        return f"-({inner})" if _prec(e.x) < 3 else f"-{inner}"
    p = _PREC[e.op]
    left, right = render(e.left), render(e.right)
    if _prec(e.left) < p:
        left = f"({left})"
    # The right side needs brackets when it binds looser, or equally tight under `-` and `/` (they do not regroup: A-(B-C)).
    if _prec(e.right) < p or (_prec(e.right) == p and e.op in "-/"):
        right = f"({right})"
    return f"{left} {e.op} {right}" if e.op in "+-" else f"{left}{e.op}{right}"


# --- the aligner --------------------------------------------------------------------------------
@dataclass
class Frame:
    """One leg's bars in columns (what `Bars.model_dump()` holds)."""

    t: list[int]
    o: list[float | None]
    h: list[float | None]
    l: list[float | None]
    c: list[float | None]
    tz: str | None = None

    @classmethod
    def of(cls, bars: dict) -> Frame:
        return cls(bars["t"], bars["o"], bars["h"], bars["l"], bars["c"], bars.get("tz"))


@lru_cache(maxsize=32)
def _zone(name: str):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


def _day_ordinals(t: list[int], tz: str | None) -> tuple[list[int], bool]:
    """Local calendar day of each bar (as `date.toordinal()`), and whether the zone was unknown (so UTC days were used).

    Two exchanges open their daily bar at different instants (New York 14:30 UTC, Mumbai 03:45 UTC), so joining daily bars on the
    exact timestamp would match nothing across markets: they are joined on the exchange-local DATE instead."""
    if not tz or tz == "UTC":
        return [x // 86_400 + _EPOCH_ORDINAL for x in t], False
    zone = _zone(tz)
    if zone is None:  # an abbreviation such as "EST": say so (the note names it) instead of guessing a zone
        return [x // 86_400 + _EPOCH_ORDINAL for x in t], True
    return [datetime.fromtimestamp(x, zone).date().toordinal() for x in t], False


def _keys(f: Frame, interval: str) -> tuple[list[Any], bool]:
    """What a bar is matched on: the exchange-local date (1d), ISO week (1wk), month (1mo); the exact timestamp for intraday and
    every other candle length."""
    if interval not in ("1d", "1wk", "1mo"):
        return list(f.t), False
    days, fallback = _day_ordinals(f.t, f.tz)
    if interval == "1d":
        return days, fallback
    dates = [date.fromordinal(d) for d in days]
    return ([d.isocalendar()[:2] for d in dates] if interval == "1wk" else [(d.year, d.month) for d in dates]), fallback


@dataclass
class Aligned:
    t: list[int]
    cols: dict[str, dict[str, list[float]]]  # leg -> field -> values on the common bars
    bars_per_leg: dict[str, int]
    dropped_join: int  # bars present in some leg but not in all of them
    incomplete: int  # bars skipped because a leg had no value for open, high, low or close
    utc_fallback: list[str]  # legs whose time zone was unknown (joined on UTC dates)


def align(frames: dict[str, Frame], interval: str) -> Aligned:
    """INNER join of the legs on bar time. Raises SymMathError when no bar is common to all of them."""
    maps: dict[str, dict[Any, int]] = {}
    incomplete, fallback = 0, []
    for leg, f in frames.items():
        keys, unknown = _keys(f, interval)
        if unknown:
            fallback.append(leg)
        seen: dict[Any, int] = {}
        for idx, (k, o, h, lo, c) in enumerate(zip(keys, f.o, f.h, f.l, f.c, strict=True)):
            if o is None or h is None or lo is None or c is None:
                incomplete += 1
                continue
            seen[k] = idx  # two bars with one key (a partial last bar): the later one wins
        maps[leg] = seen
    common = set.intersection(*(set(m) for m in maps.values()))
    union = set.union(*(set(m) for m in maps.values()))
    if not common:
        sizes = ", ".join(f"{leg} {len(m)}" for leg, m in maps.items())
        raise SymMathError(f"NO COMMON BARS BETWEEN THE SYMBOLS ({sizes}): CHECK THE RANGE, THE CANDLE LENGTH AND THE TRADING DAYS")
    order = sorted(common)
    first = next(iter(frames))
    cols = {
        leg: {fld: [getattr(frames[leg], fld)[maps[leg][k]] for k in order] for fld in ("o", "h", "l", "c")}
        for leg in frames
    }
    return Aligned(
        t=[frames[first].t[maps[first][k]] for k in order], cols=cols,
        bars_per_leg={leg: len(m) for leg, m in maps.items()}, dropped_join=len(union) - len(common),
        incomplete=incomplete, utc_fallback=fallback,
    )


# Column-wise evaluation: every node turns whole columns into a column, so the Python loops stay tight (a 10-year daily pair is
# ~2,500 bars x 4 fields). A zero divisor gives NaN; a bar with a non-finite field is dropped and counted.
def _column(e: Expr, cols: dict[str, list[float]], n: int) -> list[float]:
    if isinstance(e, Num):
        return [e.value] * n
    if isinstance(e, Sym):
        return cols[e.name]
    if isinstance(e, Neg):
        return [-x for x in _column(e.x, cols, n)]
    a, b = _column(e.left, cols, n), _column(e.right, cols, n)
    if e.op == "+":
        return [x + y for x, y in zip(a, b, strict=True)]
    if e.op == "-":
        return [x - y for x, y in zip(a, b, strict=True)]
    if e.op == "*":
        return [x * y for x, y in zip(a, b, strict=True)]
    return [x / y if y != 0.0 else math.nan for x, y in zip(a, b, strict=True)]


@dataclass
class Applied:
    t: list[int]
    o: list[float]
    h: list[float]
    l: list[float]
    c: list[float]
    dropped_zero: int  # bars removed because the formula divided by zero (or overflowed)


def apply(expr: Expr, a: Aligned) -> Applied:
    """The formula on every field of every common bar. OHLC is computed PER FIELD (open from the legs' opens, close from their
    closes ...), which is an approximation for anything but a plain scale: the real high of a ratio is not the ratio of the highs.
    So high / low are reset to the max / min of the four computed values, which keeps every bar valid (low <= open, close <= high)."""
    n = len(a.t)
    out = {fld: _column(expr, {leg: a.cols[leg][fld] for leg in a.cols}, n) for fld in ("o", "h", "l", "c")}
    keep = [i for i in range(n) if all(math.isfinite(out[f][i]) for f in "ohlc")]
    t = [a.t[i] for i in keep]
    o, c = [out["o"][i] for i in keep], [out["c"][i] for i in keep]
    h = [max(out["o"][i], out["h"][i], out["l"][i], out["c"][i]) for i in keep]
    lo = [min(out["o"][i], out["h"][i], out["l"][i], out["c"][i]) for i in keep]
    return Applied(t, o, h, lo, c, n - len(keep))
