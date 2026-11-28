/**
 * OpenTerm Script: the syntax tree (what the parser builds and the checker / compiler read).
 *
 * A tree is just plain objects. Every node has a `pos` (line and column, both 1-based) so error messages can point
 * at the exact spot. Expressions and statements are "tagged unions": the `t` field says which kind a node is.
 */

export interface Pos {
  line: number;
  col: number;
}

/** A compile or run error as the host shows it. `bar` is only set for run errors. */
export interface ScriptError {
  msg: string;
  line: number;
  col: number;
  bar?: number;
}

export type BinOp = "+" | "-" | "*" | "/" | "%" | "==" | "!=" | "<" | "<=" | ">" | ">=" | "and" | "or";
export type AssignOp = ":=" | "+=" | "-=" | "*=" | "/=";

/** One argument of a call: positional (no name) or named (`color=color.red`). */
export interface Arg {
  name?: string;
  value: Expr;
  pos: Pos;
}

export type Expr =
  | { t: "num"; v: number; pos: Pos }
  | { t: "str"; v: string; pos: Pos }
  | { t: "color"; v: string; pos: Pos }
  | { t: "bool"; v: boolean; pos: Pos }
  /** The bare `na` value (not the `na(x)` function: that is a call whose callee is `id` named `na`). */
  | { t: "na"; pos: Pos }
  | { t: "id"; name: string; pos: Pos }
  /** `a.b`: a namespace name (`ta.sma`, `color.red`) or a method name (`arr.push`). */
  | { t: "member"; obj: Expr; name: string; pos: Pos }
  /** `callee(args)`: callee is an `id` or a `member`. */
  | { t: "call"; callee: Expr; args: Arg[]; pos: Pos }
  /** `x[n]`: the value of a variable n bars ago. */
  | { t: "hist"; obj: Expr; idx: Expr; pos: Pos }
  | { t: "un"; op: "-" | "not"; e: Expr; pos: Pos }
  | { t: "bin"; op: BinOp; l: Expr; r: Expr; pos: Pos }
  | { t: "cond"; c: Expr; a: Expr; b: Expr; pos: Pos }
  /** `[a, b]`: only valid as the result of a user function. */
  | { t: "tuple"; items: Expr[]; pos: Pos };

export interface Param {
  name: string;
  /** Literal default value (or undefined = required). */
  def?: Expr;
  pos: Pos;
}

export type Stmt =
  | { t: "decl"; name: string; value: Expr; isVar: boolean; pos: Pos }
  | { t: "tdecl"; names: string[]; value: Expr; pos: Pos }
  | { t: "assign"; name: string; op: AssignOp; value: Expr; pos: Pos }
  | { t: "expr"; e: Expr; pos: Pos }
  | { t: "if"; cond: Expr; then: Stmt[]; else_: Stmt[] | null; pos: Pos }
  | { t: "for"; v: string; from: Expr; to: Expr; by: Expr | null; body: Stmt[]; pos: Pos }
  | { t: "while"; cond: Expr; body: Stmt[]; pos: Pos }
  | { t: "break"; pos: Pos }
  | { t: "continue"; pos: Pos }
  /** A user function. `body`'s last statement (an `expr`) is the result. */
  | { t: "func"; name: string; params: Param[]; body: Stmt[]; pos: Pos };

export interface Ast {
  body: Stmt[];
}

/** Thrown by the lexer and parser (the first syntax error stops compilation) and by the checker for the full list. */
export class ScriptCompileError extends Error {
  constructor(public errors: ScriptError[]) {
    super(errors[0]?.msg ?? "COMPILE ERROR");
  }
}
