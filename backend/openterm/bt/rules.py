"""BT rule syntax (spec decision F). Parsing is pure Python (the server validates rules without pandas); `signals()`
evaluates a parsed rule on bar frames and imports pandas lazily (worker side).

    rule    := or_expr
    or_expr := and_expr ("OR" and_expr)*
    and_expr:= cmp ("AND" cmp)*
    cmp     := term op term          op: > < >= <= CROSS> CROSS<
    term    := CLOSE | OPEN | HIGH | LOW | VOLUME | SMA<n> | EMA<n> | RSI<n> | HIGH<n> | LOW<n> | RET<n> | number

Case-insensitive. Error columns are 0-based character offsets into the rule text.
Indicators: SMA = rolling mean, EMA = ewm(span=n, adjust=False), RSI = Wilder (ewm alpha 1/n), HIGH<n>/LOW<n> = rolling
max of highs / min of lows including the current bar, RET<n> = n-bar return; all need n bars (NaN before).
A comparison is 0 while any input is NaN. `A CROSS> B` is 1 from the bar A crosses above B until it crosses back
below (0 before the first cross); `CROSS<` mirrors it. With `short=True` a false (valid) rule gives -1 instead of 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_PERIOD = 1000
FIELDS = {"CLOSE", "OPEN", "HIGH", "LOW", "VOLUME"}
INDICATORS = {"SMA", "EMA", "RSI", "HIGH", "LOW", "RET"}
OPS = {">", "<", ">=", "<=", "CROSS>", "CROSS<"}
INTERVALS = {"1D": "1d", "1W": "1wk"}
RANGE_RE = re.compile(r"^(\d{1,2}Y|\d{1,2}M|MAX|YTD)$")
TOKEN_RE = re.compile(r"\s*(?:(CROSS[<>])|(>=|<=|>|<)|(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+\d*)|(\S))", re.I)


class RuleError(ValueError):
    def __init__(self, message: str, col: int = -1):
        super().__init__(message)
        self.col = col


@dataclass(frozen=True)
class Term:
    kind: str  # FIELD, SMA, EMA, ..., NUM
    n: float = 0
    col: int = 0

    @property
    def label(self) -> str:
        if self.kind == "NUM":
            return f"{self.n:g}"
        return self.name if self.kind == "FIELD" else f"{self.kind}{int(self.n)}"

    name: str = ""


@dataclass(frozen=True)
class Cmp:
    left: Term
    op: str
    right: Term


@dataclass(frozen=True)
class BoolOp:
    op: str  # AND | OR
    items: tuple


@dataclass
class _Tok:
    kind: str  # op, num, word, junk, end
    text: str
    col: int


def _tokens(text: str) -> list[_Tok]:
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            break
        cross, op, num, word, junk = m.groups()
        col = m.start(m.lastindex)
        if cross:
            out.append(_Tok("op", cross.upper(), col))
        elif op:
            out.append(_Tok("op", op, col))
        elif num:
            out.append(_Tok("num", num, col))
        elif word:
            out.append(_Tok("word", word.upper(), col))
        elif junk:
            out.append(_Tok("junk", junk, col))
        pos = m.end()
    out.append(_Tok("end", "", len(text.rstrip()) if text.strip() else len(text)))
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = _tokens(text)
        self.i = 0

    def peek(self) -> _Tok:
        return self.toks[self.i]

    def take(self) -> _Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def or_expr(self):
        items = [self.and_expr()]
        while self.peek().kind == "word" and self.peek().text == "OR":
            self.take()
            items.append(self.and_expr())
        return items[0] if len(items) == 1 else BoolOp("OR", tuple(items))

    def and_expr(self):
        items = [self.cmp()]
        while self.peek().kind == "word" and self.peek().text == "AND":
            self.take()
            items.append(self.cmp())
        return items[0] if len(items) == 1 else BoolOp("AND", tuple(items))

    def cmp(self) -> Cmp:
        left = self.term()
        t = self.take()
        if t.kind != "op":
            raise RuleError("EXPECTED A COMPARISON (> < >= <= CROSS> CROSS<)" if t.kind == "end"
                            else f"EXPECTED A COMPARISON, GOT {t.text!r}", t.col)
        return Cmp(left, t.text, self.term())

    def term(self) -> Term:
        t = self.take()
        if t.kind == "num":
            return Term("NUM", float(t.text), t.col)
        if t.kind == "end":
            raise RuleError("RULE ENDS TOO EARLY: EXPECTED A TERM", t.col)
        if t.kind != "word":
            raise RuleError(f"EXPECTED A TERM, GOT {t.text!r}", t.col)
        m = re.fullmatch(r"([A-Z]+)(\d*)", t.text)
        name, digits = m.group(1), m.group(2)
        if not digits:
            if name in FIELDS:
                return Term("FIELD", 0, t.col, name)
            raise RuleError(f"UNKNOWN TERM {t.text}" + (f": {name} NEEDS A PERIOD, E.G. {name}20"
                                                      if name in INDICATORS else ""), t.col)
        if name not in INDICATORS:
            raise RuleError(f"UNKNOWN TERM {t.text}", t.col)
        n = int(digits)
        if not 1 <= n <= MAX_PERIOD:
            raise RuleError(f"{name} PERIOD MUST BE 1-{MAX_PERIOD}", t.col)
        if name == "RSI" and n < 2:
            raise RuleError("RSI PERIOD MUST BE 2 OR MORE", t.col)
        return Term(name, n, t.col)


def parse(text: str):
    if not isinstance(text, str) or not text.strip():
        raise RuleError("EMPTY RULE", 0)
    if len(text) > 500:
        raise RuleError("RULE IS TOO LONG (500 CHARACTERS MAX)", 500)
    p = _Parser(text)
    node = p.or_expr()
    t = p.peek()
    if t.kind != "end":
        raise RuleError(f"UNEXPECTED {t.text!r}", t.col)
    return node


def max_period(node) -> int:
    """Longest lookback in the rule (bars before the first possible signal)."""
    if isinstance(node, BoolOp):
        return max(max_period(x) for x in node.items)
    return int(max(node.left.n if node.left.kind != "NUM" else 0, node.right.n if node.right.kind != "NUM" else 0))


def terms(node) -> list[Term]:
    if isinstance(node, BoolOp):
        return [t for x in node.items for t in terms(x)]
    return [node.left, node.right]


# --- command line: BT <SYMS> <RULE> [INTERVAL] [RANGE] [OPTS] ----------------------------------------------------

@dataclass
class BtCommand:
    symbols: list[str]
    rule: str
    interval: str = "1D"
    range: str = "5Y"
    short: bool = False
    fees_bps: float | None = None
    slip_bps: float | None = None
    cash: float = 100_000.0
    bench: str | None = None
    mkt: str | None = None
    extra: dict = field(default_factory=dict)


def _num(key: str, raw: str, lo: float, hi: float) -> float:
    try:
        v = float(raw)
    except ValueError:
        raise RuleError(f"{key}= NEEDS A NUMBER") from None
    if not lo <= v <= hi:
        raise RuleError(f"{key} MUST BE {lo:g}-{hi:g}")
    return int(v) if v == int(v) else v


def parse_command(args: list[str]) -> BtCommand:
    if len(args) < 2:
        raise RuleError("USAGE: BT <SYMBOLS> <RULE> [1D|1W] [RANGE] [SHORT] [FEES=bps] [SLIP=bps] [CASH=n] [BENCH=sym]")
    symbols = [s.strip().upper() for s in args[0].split(",") if s.strip()]
    if not symbols or len(symbols) > 100:
        raise RuleError("BT NEEDS 1-100 SYMBOLS")
    rule_parts, rest = [], list(args[1:])
    while rest and not _is_option(rest[0]):
        rule_parts.append(rest.pop(0))
    cmd = BtCommand(symbols=symbols, rule=" ".join(rule_parts))
    for a in rest:
        u = a.upper()
        if u in INTERVALS:
            cmd.interval = u
        elif RANGE_RE.match(u):
            cmd.range = u
        elif u == "SHORT":
            cmd.short = True
        elif u.startswith("FEES="):
            cmd.fees_bps = _num("FEES", u[5:], 0, 1000)
        elif u.startswith("SLIP="):
            cmd.slip_bps = _num("SLIP", u[5:], 0, 1000)
        elif u.startswith("CASH="):
            cmd.cash = _num("CASH", u[5:], 1, 1e12)
        elif u.startswith("BENCH="):
            cmd.bench = u[6:] or None
        elif u.startswith("MKT="):
            cmd.mkt = u[4:].lower() or None
        else:
            raise RuleError(f"UNKNOWN BT OPTION {a}")
    parse(cmd.rule)
    return cmd


def _is_option(a: str) -> bool:
    u = a.upper()
    return u in INTERVALS or bool(RANGE_RE.match(u)) or u == "SHORT" or "=" in u and u.split("=")[0] in {
        "FEES", "SLIP", "CASH", "BENCH", "MKT"}


# --- evaluation (worker side) ------------------------------------------------------------------------------------

def _series(term: Term, df, cache: dict):
    import pandas as pd

    key = (term.kind, term.n, term.name)
    if key in cache:
        return cache[key]
    close = df["close"]
    n = int(term.n)
    if term.kind == "NUM":
        s = pd.Series(term.n, index=df.index, dtype=float)
    elif term.kind == "FIELD":
        s = df[term.name.lower()].astype(float)
    elif term.kind == "SMA":
        s = close.rolling(n, min_periods=n).mean()
    elif term.kind == "EMA":
        s = close.ewm(span=n, adjust=False, min_periods=n).mean()
    elif term.kind == "RSI":
        d = close.diff()
        gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        s = 100 - 100 / (1 + gain / loss)
    elif term.kind == "HIGH":
        s = df["high"].rolling(n, min_periods=n).max()
    elif term.kind == "LOW":
        s = df["low"].rolling(n, min_periods=n).min()
    else:  # RET
        s = close.pct_change(n, fill_method=None)
    cache[key] = s
    return s


def _eval(node, df, cache: dict):
    """-> (condition, valid) boolean Series."""
    if isinstance(node, BoolOp):
        parts = [_eval(x, df, cache) for x in node.items]
        cond = parts[0][0]
        valid = parts[0][1]
        for c, v in parts[1:]:
            cond = (cond & c) if node.op == "AND" else (cond | c)
            valid = valid & v
        return cond, valid
    a, b = _series(node.left, df, cache), _series(node.right, df, cache)
    valid = a.notna() & b.notna()
    if node.op in (">", "<", ">=", "<="):
        cond = {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[node.op]
        return cond & valid, valid
    above = (a > b) if node.op == "CROSS>" else (a < b)
    prev = above.shift(1, fill_value=False) & valid.shift(1, fill_value=False)
    was_valid_prev = valid.shift(1, fill_value=False)
    on = above & valid & was_valid_prev & ~prev
    off = ~above & valid & was_valid_prev & prev
    state = on.astype(float).where(on | off)
    state = state.where(~off, 0.0).ffill()
    return (state == 1.0) & valid, valid & state.notna()


def signals(node, data_map: dict, short: bool = False) -> dict:
    """symbol -> weight Series in {-1, 0, 1} on that symbol's own index."""
    import numpy as np
    import pandas as pd

    out = {}
    for sym, df in data_map.items():
        cond, valid = _eval(node, df, {})
        vals = np.where(~valid.to_numpy(), 0.0, np.where(cond.to_numpy(), 1.0, -1.0 if short else 0.0))
        out[sym] = pd.Series(vals, index=df.index, dtype=float)
    return out


# --- Pine Script (BT EXPORT, step 7) uses the parsed rule; kept here so both stay in one grammar. -----------------
