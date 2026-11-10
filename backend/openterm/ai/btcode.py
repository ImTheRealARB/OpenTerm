"""AI BT CODE: the model drafts a SignalEngine Python strategy. The draft is checked with the same static sandbox check BT EDIT
uses on save (`sandbox.check`: parses and walks the code, never executes it), at most one repair round feeds the error back, and
nothing is ever saved or run by the AI. Pure helpers here; the route lives in routes.py.
"""

from __future__ import annotations

import re

from ..bt import sandbox
from ..bt.templates import RSI_MEAN_REVERSION
from ..redact import redact

NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}$")  # the BT EDIT name rule
FENCE_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
NAME_LINE_RE = re.compile(r"^BT_CODE_NAME[ \t]+(\S+)[ \t]*$", re.MULTILINE)
LINE_RE = re.compile(r"^LINE (\d+):")
BT_CODE_TOOLS = ["history", "skill"]
NOTE = "DRAFT FROM A MODEL, NOT RUN AND NOT SAVED: READ THE CODE, OPEN IT IN BT EDIT AND SAVE IT YOURSELF (CTRL+S). A BACKTEST IS A HISTORICAL SIMULATION, NOT A FORECAST"

BT_CODE_SYSTEM = """You write one Python trading strategy for OpenTerm's BT engine. Today is {today}.
Contract: the code defines `class SignalEngine` (no base class, no decorators) with `def generate(self, data_map)`.
data_map maps each symbol to a pandas DataFrame indexed by date with open, high, low, close, volume columns.
generate returns a dict: symbol -> pandas Series (same index as that DataFrame) of target weights between -1 and 1: 1.0 is fully long, 0.0 is flat, -1.0 is fully short.
Orders fill at the NEXT bar's open, so a signal never trades on the bar that produced it. Never look ahead (no shift(-n)). Bars before an indicator has enough history must be 0.0 (flat), not NaN.
The sandbox allows only these imports: {modules}. No file, network, exec or eval access; no names starting with underscores; no decorators; no `global`; no `await`.
Do not call to_csv, read_* and similar I/O methods. Keep it short, plain and commented.
Example (RSI mean reversion):
```python
{example}```
Method: optionally look at the symbol with the history tool if the idea depends on price behaviour. Then answer with ONE fenced ```python block holding the whole strategy, one sentence of rationale, and on its own last line exactly:
BT_CODE_NAME rsi_dip_buyer
The name is lowercase letters, digits, _ or -, 1 to 40 characters. You cannot run or save the strategy: the user reads it and saves it. A backtest is a historical simulation, not a forecast."""

REPAIR = ("The strategy failed the sandbox check: {error}\nFix exactly that problem and answer again in the same format: one fenced ```python block with the whole "
          "corrected strategy, then the BT_CODE_NAME line. Use only the allowed imports.")


def system_prompt(today: str) -> str:
    return BT_CODE_SYSTEM.format(today=today, modules=", ".join(sorted(sandbox.ALLOWED_MODULES)), example=RSI_MEAN_REVERSION)


def extract_code(answer: str) -> str | None:
    """The last fenced block of the answer (a model may show a wrong attempt first), else the whole text if it looks like a strategy."""
    blocks = [b.strip("\n") + "\n" for b in FENCE_RE.findall(answer or "") if b.strip()]
    if blocks:
        return blocks[-1]
    return answer.strip() + "\n" if "class SignalEngine" in (answer or "") else None


def suggest_name(answer: str) -> str:
    m = NAME_LINE_RE.findall(answer or "")
    name = m[-1].lower() if m else ""
    return name if NAME_RE.match(name) else "ai_draft"


def validate(code: str | None) -> dict:
    """The BT EDIT save check, without running anything: {ok, error, line}. Errors are redacted like the editor's."""
    if code is None:
        return {"ok": False, "error": "THE MODEL DID NOT RETURN A PYTHON CODE BLOCK", "line": None}
    try:
        sandbox.check(code)
    except sandbox.SandboxError as e:
        msg = redact(str(e))
        m = LINE_RE.match(msg)
        return {"ok": False, "error": msg, "line": int(m.group(1)) if m else None}
    return {"ok": True, "error": None, "line": None}


def rationale(answer: str) -> str:
    """The model's prose without the code block and the name line (the code is shown by itself, with its validation)."""
    return NAME_LINE_RE.sub("", FENCE_RE.sub("", answer or "")).strip()[:600]
