"""Indicator columns for WL and Q (Phase 27 item 4): `COLS=RSI14,ATR14,PCT_SMA200,REL_VOL<0.5`. Pure (no pandas).

A column is any BT rule term (`RSI14`, `SMA50`, `ATR14`, `RET20`, `HIGH20`, `CLOSE`...), or one of two derived values:
  PCT_SMA<n> / PCT_EMA<n>  how far the close is above (+) or below (-) that average, in percent;
  REL_VOL[<n>]             the newest bar's volume over the average of the n bars before it (default 20).
An optional comparison (`RSI14<30`) colours the cell when it holds. The maths of every rule term stays in `bt/rules.py`
(one home); the worker part is `scanner/job.py` `cols_run`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..bt import rules

MAX_COLS = 6
MAX_SYMBOLS = 200
DERIVED = {"PCT_SMA", "PCT_EMA", "REL_VOL"}
COL_RE = re.compile(r"^(PCT_SMA|PCT_EMA|REL_VOL|[A-Z]+)(\d*)(?:(<=|>=|<|>)(-?\d+(?:\.\d+)?))?$")


@dataclass(frozen=True)
class Col:
    label: str  # what the column header shows, e.g. "PCT_SMA200"
    kind: str  # a rules.Term kind (SMA, RSI, FIELD...) or PCT_SMA / PCT_EMA / REL_VOL
    n: int
    name: str = ""  # FIELD name (CLOSE, VOLUME...)
    op: str | None = None  # the colouring comparison, if any
    num: float | None = None

    def public(self) -> dict:
        return {"label": self.label, "op": self.op, "num": self.num}


def parse(text: str) -> list[Col]:
    """`"RSI14,ATR14<5"` -> columns. Raises rules.RuleError (the same error type a bad SCAN rule raises)."""
    parts = [p.strip().upper() for p in (text or "").split(",") if p.strip()]
    if not parts:
        raise rules.RuleError("COLS= NEEDS AT LEAST ONE COLUMN, E.G. COLS=RSI14,PCT_SMA200")
    if len(parts) > MAX_COLS:
        raise rules.RuleError(f"AT MOST {MAX_COLS} COLUMNS")
    out: list[Col] = []
    for p in parts:
        m = COL_RE.match(p)
        if not m:
            raise rules.RuleError(f"BAD COLUMN {p}: E.G. RSI14, ATR14, PCT_SMA200, REL_VOL, RSI14<30")
        base, digits, op, num = m.groups()
        cmp = {"op": op, "num": float(num)} if op else {}
        if base in DERIVED:
            n = int(digits) if digits else (20 if base == "REL_VOL" else 0)
            if not 1 <= n <= rules.MAX_PERIOD:
                raise rules.RuleError(f"{base} NEEDS A PERIOD 1-{rules.MAX_PERIOD}, E.G. {base}200")
            out.append(Col(f"{base}{n}", base, n, **cmp))
            continue
        # Anything else must be a rule term: let the rule parser say what is wrong with it.
        term = rules.parse(f"{base}{digits} > 0").left
        out.append(Col(term.label, term.kind, int(term.n), term.name, **cmp))
    labels = [c.label for c in out]
    if len(set(labels)) != len(labels):
        raise rules.RuleError("A COLUMN IS LISTED TWICE")
    return out


def max_period(cols: list[Col]) -> int:
    """Bars each column needs (REL_VOL looks one bar further back than its window)."""
    return max((c.n + (1 if c.kind == "REL_VOL" else 0)) for c in cols)
