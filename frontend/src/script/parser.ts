/**
 * OpenTerm Script parser: tokens -> syntax tree (ast.ts). Hand-written recursive descent, like chart/formula.ts.
 *
 * "Recursive descent" means one small function per grammar rule; each calls the rule for the next-tighter precedence.
 * Precedence, loosest first (spec 1.4):
 *   ?:   or   and   not   == !=   < <= > >=   + -   * / %   unary -   postfix (call, [n], .name)
 * The first syntax error stops parsing (a ScriptCompileError with one entry).
 */
import {
  type Arg,
  type AssignOp,
  type Ast,
  type BinOp,
  type Expr,
  type Param,
  type Pos,
  type Stmt,
  ScriptCompileError,
} from "./ast";
import { lex, type Tok } from "./lexer";

const ASSIGN_OPS = new Set([":=", "+=", "-=", "*=", "/="]);

export function parse(src: string): Ast {
  return new Parser(lex(src)).program();
}

class Parser {
  private i = 0;
  constructor(private toks: Tok[]) {}

  // ---------------------------------------------------------------- token helpers
  private peek(o = 0): Tok {
    return this.toks[Math.min(this.i + o, this.toks.length - 1)];
  }
  private next(): Tok {
    const t = this.toks[this.i];
    if (this.i < this.toks.length - 1) this.i++;
    return t;
  }
  private pos(t: Tok): Pos {
    return { line: t.line, col: t.col };
  }
  private isOp(s: string, o = 0): boolean {
    const t = this.peek(o);
    return t.k === "op" && t.s === s;
  }
  private isKw(s: string, o = 0): boolean {
    const t = this.peek(o);
    return t.k === "kw" && t.s === s;
  }
  private err(msg: string, t: Tok = this.peek()): never {
    throw new ScriptCompileError([{ msg, line: t.line, col: t.col }]);
  }
  private expectOp(s: string): Tok {
    if (!this.isOp(s)) this.err(`EXPECTED ${s}`);
    return this.next();
  }
  private describe(t: Tok): string {
    if (t.k === "eof") return "END OF SCRIPT";
    if (t.k === "nl") return "END OF LINE";
    if (t.k === "indent") return "INDENT";
    if (t.k === "dedent") return "DEDENT";
    return t.s.toUpperCase();
  }

  // ---------------------------------------------------------------- statements
  program(): Ast {
    const body: Stmt[] = [];
    while (this.peek().k !== "eof") {
      if (this.peek().k === "nl") {
        this.next();
        continue;
      }
      if (this.peek().k === "indent") this.err("UNEXPECTED INDENT");
      if (this.peek().k === "dedent") this.err("BAD INDENT");
      body.push(this.statement());
    }
    return { body };
  }

  /** `nl` after a simple statement (the dedent / eof after the last line of a block counts too). */
  private endOfStatement(): void {
    const t = this.peek();
    if (t.k === "nl") {
      this.next();
      return;
    }
    if (t.k === "eof" || t.k === "dedent") return;
    this.err(`UNEXPECTED ${this.describe(t)}`);
  }

  /** NL INDENT stmt+ DEDENT */
  private block(): Stmt[] {
    if (this.peek().k !== "nl") this.err("EXPECTED END OF LINE");
    this.next();
    if (this.peek().k !== "indent") this.err("EXPECTED AN INDENTED BLOCK");
    this.next();
    const body: Stmt[] = [];
    while (this.peek().k !== "dedent" && this.peek().k !== "eof") {
      if (this.peek().k === "nl") {
        this.next();
        continue;
      }
      if (this.peek().k === "indent") this.err("UNEXPECTED INDENT");
      body.push(this.statement());
    }
    if (this.peek().k === "dedent") this.next();
    return body;
  }

  private statement(): Stmt {
    const t = this.peek();
    const pos = this.pos(t);
    if (t.k === "kw") {
      if (t.s === "if") return this.ifStmt();
      if (t.s === "for") return this.forStmt();
      if (t.s === "while") {
        this.next();
        const cond = this.expr();
        return { t: "while", cond, body: this.block(), pos };
      }
      if (t.s === "break" || t.s === "continue") {
        this.next();
        this.endOfStatement();
        return t.s === "break" ? { t: "break", pos } : { t: "continue", pos };
      }
      if (t.s === "var") {
        this.next();
        const nameTok = this.next();
        if (nameTok.k !== "id") this.err("EXPECTED A NAME AFTER VAR", nameTok);
        this.expectOp("=");
        const value = this.expr();
        this.endOfStatement();
        return { t: "decl", name: nameTok.s, value, isVar: true, pos };
      }
    }
    // `[a, b] = expr`: a tuple pattern. (A tuple EXPRESSION `[a, b]` as a function's last line has no `=` after the `]`.)
    if (this.isOp("[")) {
      const close = this.matchingBracket();
      if (close >= 0 && this.toks[close + 1]?.k === "op" && this.toks[close + 1].s === "=") {
        this.next();
        const names: string[] = [];
        while (!this.isOp("]")) {
          const n = this.next();
          if (n.k !== "id") this.err("EXPECTED A NAME", n);
          names.push(n.s);
          if (this.isOp(",")) this.next();
          else if (!this.isOp("]")) this.err("EXPECTED ]");
        }
        this.next();
        this.expectOp("=");
        const value = this.expr();
        this.endOfStatement();
        return { t: "tdecl", names, value, pos };
      }
    }
    if (t.k === "id") {
      // function definition: name ( params ) =>
      if (this.isOp("(", 1)) {
        const close = this.matchingParen(this.i + 1);
        if (close >= 0 && this.toks[close + 1]?.k === "op" && this.toks[close + 1].s === "=>") return this.funcDef();
      }
      // name = expr   /   name := expr   /   name += expr ...
      const n1 = this.peek(1);
      if (n1.k === "op" && n1.s === "=") {
        this.next();
        this.next();
        const value = this.expr();
        this.endOfStatement();
        return { t: "decl", name: t.s, value, isVar: false, pos };
      }
      if (n1.k === "op" && ASSIGN_OPS.has(n1.s)) {
        this.next();
        this.next();
        const value = this.expr();
        this.endOfStatement();
        return { t: "assign", name: t.s, op: n1.s as AssignOp, value, pos };
      }
    }
    const e = this.expr();
    this.endOfStatement();
    return { t: "expr", e, pos };
  }

  private ifStmt(): Stmt {
    const t = this.next(); // if
    const pos = this.pos(t);
    const cond = this.expr();
    const then = this.block();
    let else_: Stmt[] | null = null;
    if (this.isKw("else")) {
      this.next();
      if (this.isKw("if")) else_ = [this.ifStmt()];
      else else_ = this.block();
    }
    return { t: "if", cond, then, else_, pos };
  }

  private forStmt(): Stmt {
    const t = this.next(); // for
    const pos = this.pos(t);
    const v = this.next();
    if (v.k !== "id") this.err("EXPECTED A LOOP VARIABLE", v);
    this.expectOp("=");
    const from = this.expr();
    if (!this.isKw("to")) this.err("EXPECTED TO");
    this.next();
    const to = this.expr();
    let by: Expr | null = null;
    if (this.isKw("by")) {
      this.next();
      by = this.expr();
    }
    return { t: "for", v: v.s, from, to, by, body: this.block(), pos };
  }

  private funcDef(): Stmt {
    const nameTok = this.next();
    const pos = this.pos(nameTok);
    this.expectOp("(");
    const params: Param[] = [];
    while (!this.isOp(")")) {
      const p = this.next();
      if (p.k !== "id") this.err("EXPECTED A PARAMETER NAME", p);
      let def: Expr | undefined;
      if (this.isOp("=")) {
        this.next();
        def = this.expr();
      }
      params.push({ name: p.s, def, pos: this.pos(p) });
      if (this.isOp(",")) this.next();
      else if (!this.isOp(")")) this.err("EXPECTED )");
    }
    this.next(); // )
    this.expectOp("=>");
    let body: Stmt[];
    if (this.peek().k === "nl") {
      body = this.block();
    } else {
      const e = this.expr();
      this.endOfStatement();
      body = [{ t: "expr", e, pos: e.pos }];
    }
    return { t: "func", name: nameTok.s, params, body, pos };
  }

  /** Index of the `)` matching the `(` at index `open` (or -1). */
  private matchingParen(open: number): number {
    let d = 0;
    for (let j = open; j < this.toks.length; j++) {
      const k = this.toks[j];
      if (k.k === "op" && k.s === "(") d++;
      else if (k.k === "op" && k.s === ")") {
        d--;
        if (d === 0) return j;
      } else if (k.k === "eof") break;
    }
    return -1;
  }
  private matchingBracket(): number {
    let d = 0;
    for (let j = this.i; j < this.toks.length; j++) {
      const k = this.toks[j];
      if (k.k === "op" && k.s === "[") d++;
      else if (k.k === "op" && k.s === "]") {
        d--;
        if (d === 0) return j;
      } else if (k.k === "eof") break;
    }
    return -1;
  }

  // ---------------------------------------------------------------- expressions
  expr(): Expr {
    return this.ternary();
  }

  private ternary(): Expr {
    const c = this.or();
    if (this.isOp("?")) {
      const q = this.next();
      const a = this.ternary();
      if (!this.isOp(":")) this.err("EXPECTED :");
      this.next();
      const b = this.ternary();
      return { t: "cond", c, a, b, pos: this.pos(q) };
    }
    return c;
  }

  private or(): Expr {
    let l = this.and();
    while (this.isKw("or")) {
      const o = this.next();
      l = { t: "bin", op: "or", l, r: this.and(), pos: this.pos(o) };
    }
    return l;
  }
  private and(): Expr {
    let l = this.not();
    while (this.isKw("and")) {
      const o = this.next();
      l = { t: "bin", op: "and", l, r: this.not(), pos: this.pos(o) };
    }
    return l;
  }
  private not(): Expr {
    if (this.isKw("not")) {
      const o = this.next();
      return { t: "un", op: "not", e: this.not(), pos: this.pos(o) };
    }
    return this.equality();
  }
  private equality(): Expr {
    let l = this.comparison();
    while (this.isOp("==") || this.isOp("!=")) {
      const o = this.next();
      l = { t: "bin", op: o.s as BinOp, l, r: this.comparison(), pos: this.pos(o) };
    }
    return l;
  }
  private comparison(): Expr {
    let l = this.additive();
    while (this.isOp("<") || this.isOp("<=") || this.isOp(">") || this.isOp(">=")) {
      const o = this.next();
      l = { t: "bin", op: o.s as BinOp, l, r: this.additive(), pos: this.pos(o) };
    }
    return l;
  }
  private additive(): Expr {
    let l = this.multiplicative();
    while (this.isOp("+") || this.isOp("-")) {
      const o = this.next();
      l = { t: "bin", op: o.s as BinOp, l, r: this.multiplicative(), pos: this.pos(o) };
    }
    return l;
  }
  private multiplicative(): Expr {
    let l = this.unary();
    while (this.isOp("*") || this.isOp("/") || this.isOp("%")) {
      const o = this.next();
      l = { t: "bin", op: o.s as BinOp, l, r: this.unary(), pos: this.pos(o) };
    }
    return l;
  }
  private unary(): Expr {
    if (this.isOp("-")) {
      const o = this.next();
      return { t: "un", op: "-", e: this.unary(), pos: this.pos(o) };
    }
    return this.postfix();
  }

  private postfix(): Expr {
    let e = this.primary();
    for (;;) {
      if (this.isOp("(")) {
        if (e.t !== "id" && e.t !== "member") this.err("EXPECTED A FUNCTION NAME BEFORE (");
        e = this.callRest(e);
      } else if (this.isOp("[")) {
        const b = this.next();
        const idx = this.expr();
        this.expectOp("]");
        e = { t: "hist", obj: e, idx, pos: this.pos(b) };
      } else if (this.isOp(".")) {
        const d = this.next();
        const n = this.next();
        if (n.k !== "id" && n.k !== "kw") this.err("EXPECTED A NAME AFTER .", n);
        e = { t: "member", obj: e, name: n.s, pos: this.pos(d) };
      } else return e;
    }
  }

  private callRest(callee: Expr): Expr {
    const open = this.next(); // (
    const args: Arg[] = [];
    let named = false;
    while (!this.isOp(")")) {
      const t = this.peek();
      // `name = value` is a named argument (a single `=`; `==` is a different token)
      if (t.k === "id" && this.isOp("=", 1)) {
        this.next();
        this.next();
        args.push({ name: t.s, value: this.expr(), pos: this.pos(t) });
        named = true;
      } else {
        if (named) this.err("POSITIONAL ARGUMENT AFTER A NAMED ONE");
        args.push({ value: this.expr(), pos: this.pos(t) });
      }
      if (this.isOp(",")) this.next();
      else if (!this.isOp(")")) this.err("EXPECTED )");
    }
    this.next(); // )
    return { t: "call", callee, args, pos: this.pos(open) };
  }

  private primary(): Expr {
    const t = this.next();
    const pos = this.pos(t);
    switch (t.k) {
      case "num":
        return { t: "num", v: t.v as number, pos };
      case "str":
        return { t: "str", v: t.s, pos };
      case "color":
        return { t: "color", v: t.s, pos };
      case "id":
        return { t: "id", name: t.s, pos };
      case "kw":
        if (t.s === "true") return { t: "bool", v: true, pos };
        if (t.s === "false") return { t: "bool", v: false, pos };
        if (t.s === "na") {
          // `na(x)` is the function; a bare `na` is the missing value
          if (this.isOp("(")) return this.callRest({ t: "id", name: "na", pos });
          return { t: "na", pos };
        }
        break;
      case "op":
        if (t.s === "(") {
          const e = this.expr();
          this.expectOp(")");
          return e;
        }
        if (t.s === "[") {
          const items: Expr[] = [];
          while (!this.isOp("]")) {
            items.push(this.expr());
            if (this.isOp(",")) this.next();
            else if (!this.isOp("]")) this.err("EXPECTED ]");
          }
          this.next();
          return { t: "tuple", items, pos };
        }
        break;
      default:
        break;
    }
    this.err(t.k === "nl" || t.k === "eof" ? "EXPECTED EXPRESSION" : `UNEXPECTED ${this.describe(t)}`, t);
  }
}
