"""Lexer: turns script text into tokens, including INDENT / DEDENT tokens for the indented blocks.

Rules (spec 1.1):
  * `//` starts a comment. Blank and comment-only lines are ignored.
  * Blocks are made by indentation like Python. A tab counts as 4 spaces.
  * Inside ( ) and [ ] newlines and indentation are ignored, so a call can span lines.
  * A line that ends with a binary operator or a comma continues on the next line.
"""

# `x != x` is the standard test for NaN (na) in Python and JavaScript; ruff's PLR0124 would reject it.

from __future__ import annotations

import re

from .errors import ScriptCompileError, err

KEYWORDS = frozenset(
    ["if", "else", "for", "to", "by", "while", "break", "continue", "var", "and", "or", "not", "true", "false", "na"]
)

# If a line ends with one of these the statement goes on the next line.
CONTINUATION_OPS = frozenset(
    ["+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", "?", ":", ",", "=", ":=", "+=", "-=", "*=", "/="]
)
CONTINUATION_WORDS = frozenset(["and", "or", "not"])

# One regular expression with a named group per token kind. The order matters: longer operators first, colours before
# the generic "unknown character" case, numbers before the `.` operator so `.5` is a number.
_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t]+)
  | (?P<comment>//[^\n]*)
  | (?P<num>(?:\d+\.\d+|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<color>\#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})(?![0-9A-Za-z_]))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<op>:=|\+=|-=|\*=|/=|==|!=|<=|>=|=>|[-+*/%<>=?:,.()\[\]])
    """,
    re.VERBOSE,
)

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}


class Token:
    """One token. `kind` is num, str, color, name, kw, op, nl, indent, dedent or eof."""

    __slots__ = ("col", "kind", "line", "val")

    def __init__(self, kind: str, val, line: int, col: int):
        self.kind = kind
        self.val = val
        self.line = line
        self.col = col

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.kind}, {self.val!r}, {self.line}:{self.col})"


def _unescape(body: str) -> str:
    """Turn the backslash escapes of a text literal into the characters they stand for."""
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def tokenize(src: str) -> list[Token]:
    """Split `src` into tokens. Raises ScriptCompileError (one error) on the first lexical problem."""
    tokens: list[Token] = []
    indents = [0]  # the stack of open indentation widths
    depth = 0  # how many ( or [ are open
    continuing = False  # the previous logical line ended with an operator
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    last_line = 1

    for line_no, raw in enumerate(lines, 1):
        last_line = line_no
        # --- indentation
        width = 0
        i = 0
        while i < len(raw) and raw[i] in " \t":
            width += 4 if raw[i] == "\t" else 1
            i += 1
        rest = raw[i:]
        if rest == "" or rest.startswith("//"):
            continue  # blank or comment-only: invisible to the parser
        if depth == 0 and not continuing:
            if width > indents[-1]:
                indents.append(width)
                tokens.append(Token("indent", None, line_no, 1))
            else:
                while width < indents[-1]:
                    indents.pop()
                    tokens.append(Token("dedent", None, line_no, 1))
                if width != indents[-1]:
                    raise ScriptCompileError([err("INCONSISTENT INDENTATION", line_no, 1)])

        # --- tokens of this line
        first_of_line = len(tokens)
        pos = i
        while pos < len(raw):
            m = _TOKEN_RE.match(raw, pos)
            if m is None:
                bad = raw[pos]
                if bad in "\"'":
                    raise ScriptCompileError([err("UNTERMINATED TEXT", line_no, pos + 1)])
                raise ScriptCompileError([err(f"UNEXPECTED CHARACTER {bad}", line_no, pos + 1)])
            kind = m.lastgroup
            text = m.group()
            col = pos + 1
            pos = m.end()
            if kind == "ws" or kind == "comment":
                continue
            if kind == "num":
                tokens.append(Token("num", float(text), line_no, col))
            elif kind == "str":
                tokens.append(Token("str", _unescape(text[1:-1]), line_no, col))
            elif kind == "color":
                tokens.append(Token("color", text.lower(), line_no, col))
            elif kind == "name":
                tokens.append(Token("kw" if text in KEYWORDS else "name", text, line_no, col))
            else:  # op
                if text in "([":
                    depth += 1
                elif text in ")]":
                    depth -= 1
                    if depth < 0:
                        raise ScriptCompileError([err(f"UNEXPECTED {text}", line_no, col)])
                tokens.append(Token("op", text, line_no, col))

        # --- end of the line: a NEWLINE unless we are inside brackets or the line ends with an operator
        if depth == 0:
            last = tokens[-1] if len(tokens) > first_of_line else None
            ends_open = last is not None and (
                (last.kind == "op" and last.val in CONTINUATION_OPS) or (last.kind == "kw" and last.val in CONTINUATION_WORDS)
            )
            if ends_open:
                continuing = True
            else:
                tokens.append(Token("nl", None, line_no, len(raw) + 1))
                continuing = False

    if depth > 0:
        raise ScriptCompileError([err("EXPECTED )", last_line, 1)])
    if tokens and tokens[-1].kind != "nl":
        tokens.append(Token("nl", None, last_line, 1))
    while len(indents) > 1:
        indents.pop()
        tokens.append(Token("dedent", None, last_line, 1))
    tokens.append(Token("eof", None, last_line, 1))
    return tokens
