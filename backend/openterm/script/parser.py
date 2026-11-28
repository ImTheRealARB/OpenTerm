"""Recursive-descent parser: tokens -> syntax tree (`ast.py`).

Precedence, lowest first (spec 1.4):  ?:  <  or  <  and  <  not  <  == !=  <  < <= > >=  <  + -  <  * / %  <  unary -  <  postfix
(call, history `x[n]`, member `a.b`). The parser stops at the first syntax error and raises ScriptCompileError with it.
"""

# `x != x` is the standard test for NaN (na) in Python and JavaScript; ruff's PLR0124 would reject it.

from __future__ import annotations

from . import ast as A
from .errors import ScriptCompileError, err
from .lexer import Token, tokenize

ASSIGN_OPS = frozenset(["=", ":=", "+=", "-=", "*=", "/="])


class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.pos = 0

    # ------------------------------------------------------------------------------------------ token helpers

    @property
    def tok(self) -> Token:
        return self.toks[self.pos]

    def peek(self, k: int = 1) -> Token:
        i = min(self.pos + k, len(self.toks) - 1)
        return self.toks[i]

    def advance(self) -> Token:
        t = self.toks[self.pos]
        if t.kind != "eof":
            self.pos += 1
        return t

    def is_op(self, val: str, tok: Token | None = None) -> bool:
        t = tok or self.tok
        return t.kind == "op" and t.val == val

    def is_kw(self, val: str, tok: Token | None = None) -> bool:
        t = tok or self.tok
        return t.kind == "kw" and t.val == val

    def describe(self, t: Token) -> str:
        """How a token reads in an error message."""
        if t.kind == "nl":
            return "END OF LINE"
        if t.kind == "eof":
            return "END OF SCRIPT"
        if t.kind == "indent":
            return "INDENT"
        if t.kind == "dedent":
            return "END OF BLOCK"
        if t.kind == "num":
            return "NUMBER"
        if t.kind == "str":
            return "TEXT"
        if t.kind == "color":
            return "COLOUR"
        return str(t.val).upper()

    def fail(self, msg: str, t: Token | None = None):
        t = t or self.tok
        raise ScriptCompileError([err(msg, t.line, t.col)])

    def expect_op(self, val: str) -> Token:
        if not self.is_op(val):
            self.fail(f"EXPECTED {val}")
        return self.advance()

    def expect_kw(self, val: str) -> Token:
        if not self.is_kw(val):
            self.fail(f"EXPECTED {val.upper()}")
        return self.advance()

    def expect_name(self) -> Token:
        if self.tok.kind != "name":
            self.fail("EXPECTED A NAME")
        return self.advance()

    def end_of_statement(self) -> None:
        if self.tok.kind == "nl":
            self.advance()
        elif self.tok.kind != "eof":
            self.fail(f"UNEXPECTED {self.describe(self.tok)}")

    # ------------------------------------------------------------------------------------------ program and blocks

    def parse_program(self) -> list:
        stmts = []
        while self.tok.kind != "eof":
            if self.tok.kind == "indent":
                self.fail("UNEXPECTED INDENT")
            stmts.append(self.statement())
        return stmts

    def block(self) -> list:
        """The indented body after a block header (the header's own NEWLINE is consumed here)."""
        if self.tok.kind != "nl":
            self.fail("EXPECTED A NEW LINE")
        self.advance()
        if self.tok.kind != "indent":
            self.fail("EXPECTED AN INDENTED BLOCK")
        self.advance()
        stmts = []
        while self.tok.kind not in ("dedent", "eof"):
            if self.tok.kind == "indent":
                self.fail("UNEXPECTED INDENT")
            stmts.append(self.statement())
        if self.tok.kind == "dedent":
            self.advance()
        return stmts

    # ------------------------------------------------------------------------------------------ statements

    def statement(self):
        t = self.tok
        if t.kind == "kw":
            if t.val == "if":
                return self.if_stmt()
            if t.val == "for":
                return self.for_stmt()
            if t.val == "while":
                self.advance()
                cond = self.expr()
                return A.While(cond, self.block(), t.line, t.col)
            if t.val in ("break", "continue"):
                self.advance()
                self.end_of_statement()
                return A.Break(t.line, t.col) if t.val == "break" else A.Continue(t.line, t.col)
            if t.val == "var":
                self.advance()
                name = self.expect_name()
                if not self.is_op("="):
                    self.fail("EXPECTED =")
                self.advance()
                value = self.expr()
                self.end_of_statement()
                return A.Assign(name.val, "=", value, True, t.line, t.col)
            if t.val in ("else", "to", "by"):
                self.fail(f"UNEXPECTED {t.val.upper()}")
        if t.kind == "name":
            nxt = self.peek()
            if nxt.kind == "op" and nxt.val in ASSIGN_OPS:
                self.advance()
                self.advance()
                value = self.expr()
                self.end_of_statement()
                return A.Assign(t.val, nxt.val, value, False, t.line, t.col)
            if self.is_op("(", nxt) and self.looks_like_function_def():
                return self.func_def()
        if self.is_op("[") and self.looks_like_destructure():
            return self.destructure()
        e = self.expr()
        self.end_of_statement()
        return A.ExprStmt(e, t.line, t.col)

    def looks_like_function_def(self) -> bool:
        """`name ( ... ) =>` : scan to the matching ) and check for =>."""
        depth = 0
        i = self.pos + 1
        while i < len(self.toks):
            t = self.toks[i]
            if t.kind == "op" and t.val in "([":
                depth += 1
            elif t.kind == "op" and t.val in ")]":
                depth -= 1
                if depth == 0:
                    n = self.toks[i + 1] if i + 1 < len(self.toks) else None
                    return n is not None and n.kind == "op" and n.val == "=>"
            elif t.kind in ("nl", "eof"):
                return False
            i += 1
        return False

    def looks_like_destructure(self) -> bool:
        """`[a, b] = ...` : scan to the matching ] and check for a single =."""
        depth = 0
        i = self.pos
        while i < len(self.toks):
            t = self.toks[i]
            if t.kind == "op" and t.val == "[":
                depth += 1
            elif t.kind == "op" and t.val == "]":
                depth -= 1
                if depth == 0:
                    n = self.toks[i + 1] if i + 1 < len(self.toks) else None
                    return n is not None and n.kind == "op" and n.val == "="
            elif t.kind in ("nl", "eof"):
                return False
            i += 1
        return False

    def destructure(self) -> A.TupleAssign:
        t = self.expect_op("[")
        names: list[str] = []
        pos: list[tuple[int, int]] = []
        while True:
            n = self.expect_name()
            names.append(n.val)
            pos.append((n.line, n.col))
            if self.is_op(","):
                self.advance()
                continue
            break
        self.expect_op("]")
        self.expect_op("=")
        value = self.expr()
        self.end_of_statement()
        return A.TupleAssign(names, value, pos, t.line, t.col)

    def if_stmt(self) -> A.If:
        t = self.expect_kw("if")
        cond = self.expr()
        body = self.block()
        orelse = None
        if self.is_kw("else"):
            e = self.advance()
            if self.is_kw("if"):
                orelse = [self.if_stmt()]
            else:
                orelse = self.block()
            _ = e
        return A.If(cond, body, orelse, t.line, t.col)

    def for_stmt(self) -> A.For:
        t = self.expect_kw("for")
        name = self.expect_name()
        self.expect_op("=")
        start = self.expr()
        self.expect_kw("to")
        stop = self.expr()
        step = None
        if self.is_kw("by"):
            self.advance()
            step = self.expr()
        return A.For(name.val, start, stop, step, self.block(), t.line, t.col)

    def func_def(self) -> A.FuncDef:
        name = self.expect_name()
        self.expect_op("(")
        params: list[A.Param] = []
        if not self.is_op(")"):
            while True:
                p = self.expect_name()
                default = None
                if self.is_op("="):
                    self.advance()
                    default = self.expr()
                params.append(A.Param(p.val, default, p.line, p.col))
                if self.is_op(","):
                    self.advance()
                    continue
                break
        self.expect_op(")")
        self.expect_op("=>")
        if self.tok.kind == "nl":
            body = self.block()
        else:
            e = self.expr()
            self.end_of_statement()
            body = [A.ExprStmt(e, e.line, e.col)]
        return A.FuncDef(name.val, params, body, name.line, name.col)

    # ------------------------------------------------------------------------------------------ expressions

    def expr(self):
        return self.ternary()

    def ternary(self):
        cond = self.or_()
        if self.is_op("?"):
            q = self.advance()
            a = self.ternary()
            self.expect_op(":")
            b = self.ternary()
            return A.Ternary(cond, a, b, q.line, q.col)
        return cond

    def or_(self):
        left = self.and_()
        while self.is_kw("or"):
            t = self.advance()
            left = A.Binary("or", left, self.and_(), t.line, t.col)
        return left

    def and_(self):
        left = self.not_()
        while self.is_kw("and"):
            t = self.advance()
            left = A.Binary("and", left, self.not_(), t.line, t.col)
        return left

    def not_(self):
        if self.is_kw("not"):
            t = self.advance()
            return A.Unary("not", self.not_(), t.line, t.col)
        return self.equality()

    def equality(self):
        left = self.comparison()
        while self.tok.kind == "op" and self.tok.val in ("==", "!="):
            t = self.advance()
            left = A.Binary(t.val, left, self.comparison(), t.line, t.col)
        return left

    def comparison(self):
        left = self.additive()
        while self.tok.kind == "op" and self.tok.val in ("<", "<=", ">", ">="):
            t = self.advance()
            left = A.Binary(t.val, left, self.additive(), t.line, t.col)
        return left

    def additive(self):
        left = self.multiplicative()
        while self.tok.kind == "op" and self.tok.val in ("+", "-"):
            t = self.advance()
            left = A.Binary(t.val, left, self.multiplicative(), t.line, t.col)
        return left

    def multiplicative(self):
        left = self.unary()
        while self.tok.kind == "op" and self.tok.val in ("*", "/", "%"):
            t = self.advance()
            left = A.Binary(t.val, left, self.unary(), t.line, t.col)
        return left

    def unary(self):
        if self.is_op("-"):
            t = self.advance()
            return A.Unary("-", self.unary(), t.line, t.col)
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            t = self.tok
            if self.is_op("("):
                self.advance()
                e = A.Call(e, self.call_args(), t.line, t.col)
            elif self.is_op("["):
                self.advance()
                idx = self.expr()
                self.expect_op("]")
                e = A.Index(e, idx, t.line, t.col)
            elif self.is_op("."):
                self.advance()
                n = self.tok
                if n.kind != "name":
                    self.fail("EXPECTED A NAME")
                self.advance()
                e = A.Member(e, n.val, n.line, n.col)
            else:
                return e

    def call_args(self) -> list[A.Arg]:
        """Arguments after the opening ( : positional first, then `name=value`. Consumes the closing )."""
        args: list[A.Arg] = []
        seen_named = False
        if not self.is_op(")"):
            while True:
                t = self.tok
                nxt = self.peek()
                if t.kind == "name" and self.is_op("=", nxt):
                    self.advance()
                    self.advance()
                    args.append(A.Arg(self.expr(), t.val, t.line, t.col))
                    seen_named = True
                else:
                    if seen_named:
                        self.fail("A POSITIONAL ARGUMENT CANNOT FOLLOW A NAMED ONE")
                    e = self.expr()
                    args.append(A.Arg(e, None, t.line, t.col))
                if self.is_op(","):
                    self.advance()
                    continue
                break
        self.expect_op(")")
        return args

    def primary(self):
        t = self.tok
        if t.kind == "num":
            self.advance()
            return A.Num(t.val, t.line, t.col)
        if t.kind == "str":
            self.advance()
            return A.Str(t.val, t.line, t.col)
        if t.kind == "color":
            self.advance()
            return A.Color(t.val, t.line, t.col)
        if t.kind == "kw":
            if t.val in ("true", "false"):
                self.advance()
                return A.Bool(t.val == "true", t.line, t.col)
            if t.val == "na":
                self.advance()
                if self.is_op("("):  # na(x) is the "is it missing?" function
                    return A.Name("na", t.line, t.col)
                return A.NaLit(t.line, t.col)
        if t.kind == "name":
            self.advance()
            return A.Name(t.val, t.line, t.col)
        if self.is_op("("):
            self.advance()
            e = self.expr()
            self.expect_op(")")
            return e
        if self.is_op("["):
            self.advance()
            items = []
            if not self.is_op("]"):
                while True:
                    items.append(self.expr())
                    if self.is_op(","):
                        self.advance()
                        continue
                    break
            self.expect_op("]")
            return A.TupleLit(items, t.line, t.col)
        self.fail("EXPECTED AN EXPRESSION")


def parse(src: str) -> list:
    """Source text -> list of statements. Raises ScriptCompileError."""
    return Parser(tokenize(src)).parse_program()
