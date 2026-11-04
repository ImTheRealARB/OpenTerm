/**
 * Formula language for custom indicators. Hand-written recursive-descent parser and a vectorised evaluator over Float64Array.
 * No eval, no Function, no user JavaScript: the only things a formula can do are the operators and functions listed here.
 * Pure (no DOM), so it runs inside the indicator Web Worker and in unit tests.
 *
 * Grammar (lowest to highest precedence):
 *   or      := and ( OR and )*
 *   and     := not ( AND not )*
 *   not     := NOT not | cmp
 *   cmp     := add ( (< <= > >= == != =) add )?
 *   add     := mul ( (+ -) mul )*
 *   mul     := unary ( (* /) unary )*
 *   unary   := - unary | pow
 *   pow     := primary ( ^ unary )?              right associative, so -2^2 = -4 and 2^-1 works
 *   primary := number | name | name ( args ) [ . output ] | ( or )
 *
 * Names: open high low close volume (o h l c v), hl2 hlc3 ohlc4, TRUE FALSE, PI.
 * Functions: ABS LOG LN SQRT EXP SIGN FLOOR CEIL ROUND POW MAX MIN IF CROSSOVER CROSSUNDER REF,
 * series functions f(series, n): SMA EMA WMA RMA HMA DEMA TEMA TRIMA ZLEMA KAMA RSI STDEV VAR SUM HIGHEST LOWEST MEDIAN ROC MOM ZSCORE LINREG SLOPE,
 * and any library indicator by id with numeric params, e.g. MACD(12,26,9).signal or ATR(14).
 * Comparisons and AND / OR / NOT give 1 or 0 (NaN while data is missing).
 */
import { findIndicator, resolveParams } from "./library/catalog";
import { type A, diff, emaN, firstFinite, hi, lag, linreg, lo, map, nanArr, rmaN, smaN, stdN, sumN, wmaN, zip } from "./library/math";
import { hma, kama, trima, zlema, medianN } from "./library/trend";
import { rsi } from "./indicators";
import type { Cols } from "./library/types";

export const MAX_FORMULA_LENGTH = 500;
export const MAX_DEPTH = 40;
const MAX_NODES = 300;

export type FormulaResult = { ok: true; out: A } | { ok: false; error: string; pos: number };

class FormulaError extends Error {
  constructor(msg: string, public pos: number) {
    super(msg);
  }
}

// ---------------------------------------------------------------- lexer

type Tok = { k: "num" | "id" | "op" | "end"; s: string; v?: number; pos: number };

const OPS3 = ["<=", ">=", "==", "!=", "<>"];

function lex(src: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") {
      i++;
      continue;
    }
    if ((ch >= "0" && ch <= "9") || (ch === "." && src[i + 1] >= "0" && src[i + 1] <= "9")) {
      let j = i;
      while (j < src.length && ((src[j] >= "0" && src[j] <= "9") || src[j] === ".")) j++;
      if ((src[j] === "e" || src[j] === "E") && /[0-9+-]/.test(src[j + 1] ?? "")) {
        j++;
        if (src[j] === "+" || src[j] === "-") j++;
        while (j < src.length && src[j] >= "0" && src[j] <= "9") j++;
      }
      const text = src.slice(i, j);
      const v = Number(text);
      if (!Number.isFinite(v)) throw new FormulaError(`BAD NUMBER ${text} AT ${i + 1}`, i);
      out.push({ k: "num", s: text, v, pos: i });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(ch)) {
      let j = i + 1;
      while (j < src.length && /[A-Za-z0-9_]/.test(src[j])) j++;
      out.push({ k: "id", s: src.slice(i, j).toUpperCase(), pos: i });
      i = j;
      continue;
    }
    const two = src.slice(i, i + 2);
    if (OPS3.includes(two)) {
      out.push({ k: "op", s: two === "<>" ? "!=" : two, pos: i });
      i += 2;
      continue;
    }
    if ("+-*/^(),.<>=".includes(ch)) {
      out.push({ k: "op", s: ch === "=" ? "==" : ch, pos: i });
      i++;
      continue;
    }
    throw new FormulaError(`UNEXPECTED CHARACTER ${ch} AT ${i + 1}`, i);
  }
  out.push({ k: "end", s: "", pos: src.length });
  return out;
}

// ---------------------------------------------------------------- parser

type Node =
  | { t: "num"; v: number; pos: number }
  | { t: "name"; name: string; pos: number }
  | { t: "un"; op: "-" | "NOT"; a: Node; pos: number }
  | { t: "bin"; op: string; a: Node; b: Node; pos: number }
  | { t: "call"; name: string; args: Node[]; out?: string; pos: number };

class Parser {
  private i = 0;
  private depth = 0;
  private nodes = 0;
  constructor(private toks: Tok[]) {}

  private peek = () => this.toks[this.i];
  private next = () => this.toks[this.i++];
  private isOp(s: string) {
    const t = this.peek();
    return t.k === "op" && t.s === s;
  }
  private isKw(s: string) {
    const t = this.peek();
    return t.k === "id" && t.s === s;
  }
  private enter(pos: number) {
    if (++this.depth > MAX_DEPTH) throw new FormulaError(`TOO DEEP AT ${pos + 1}`, pos);
    if (++this.nodes > MAX_NODES) throw new FormulaError(`FORMULA TOO LARGE AT ${pos + 1}`, pos);
  }
  private leave() {
    this.depth--;
  }

  parse(): Node {
    const n = this.or();
    const t = this.peek();
    if (t.k !== "end") throw new FormulaError(t.s === ")" ? `UNEXPECTED ) AT ${t.pos + 1}` : `UNEXPECTED ${t.s} AT ${t.pos + 1}`, t.pos);
    return n;
  }

  private or(): Node {
    this.enter(this.peek().pos);
    let a = this.and();
    while (this.isKw("OR")) {
      const p = this.next().pos;
      a = { t: "bin", op: "OR", a, b: this.and(), pos: p };
    }
    this.leave();
    return a;
  }
  private and(): Node {
    let a = this.not();
    while (this.isKw("AND")) {
      const p = this.next().pos;
      a = { t: "bin", op: "AND", a, b: this.not(), pos: p };
    }
    return a;
  }
  private not(): Node {
    if (this.isKw("NOT")) {
      const p = this.next().pos;
      this.enter(p);
      const a = this.not();
      this.leave();
      return { t: "un", op: "NOT", a, pos: p };
    }
    return this.cmp();
  }
  private cmp(): Node {
    const a = this.add();
    const t = this.peek();
    if (t.k === "op" && ["<", "<=", ">", ">=", "==", "!="].includes(t.s)) {
      this.next();
      return { t: "bin", op: t.s, a, b: this.add(), pos: t.pos };
    }
    return a;
  }
  private add(): Node {
    let a = this.mul();
    while (this.isOp("+") || this.isOp("-")) {
      const t = this.next();
      a = { t: "bin", op: t.s, a, b: this.mul(), pos: t.pos };
    }
    return a;
  }
  private mul(): Node {
    let a = this.unary();
    while (this.isOp("*") || this.isOp("/")) {
      const t = this.next();
      a = { t: "bin", op: t.s, a, b: this.unary(), pos: t.pos };
    }
    return a;
  }
  private unary(): Node {
    if (this.isOp("-") || this.isOp("+")) {
      const t = this.next();
      this.enter(t.pos);
      const a = this.unary();
      this.leave();
      return t.s === "-" ? { t: "un", op: "-", a, pos: t.pos } : a;
    }
    return this.pow();
  }
  private pow(): Node {
    const a = this.primary();
    if (this.isOp("^")) {
      const t = this.next();
      this.enter(t.pos);
      const b = this.unary();
      this.leave();
      return { t: "bin", op: "^", a, b, pos: t.pos };
    }
    return a;
  }
  private primary(): Node {
    const t = this.next();
    if (t.k === "num") return { t: "num", v: t.v!, pos: t.pos };
    if (t.k === "id") {
      if (this.isOp("(")) {
        this.next();
        this.enter(t.pos);
        const args: Node[] = [];
        if (!this.isOp(")")) {
          for (;;) {
            args.push(this.or());
            if (this.isOp(",")) {
              this.next();
              continue;
            }
            break;
          }
        }
        if (!this.isOp(")")) {
          const e = this.peek();
          throw new FormulaError(`EXPECTED ) AT ${e.pos + 1}`, e.pos);
        }
        this.next();
        this.leave();
        let out: string | undefined;
        if (this.isOp(".")) {
          this.next();
          const o = this.peek();
          if (o.k !== "id") throw new FormulaError(`EXPECTED OUTPUT NAME AT ${o.pos + 1}`, o.pos);
          out = this.next().s;
        }
        return { t: "call", name: t.s, args, out, pos: t.pos };
      }
      return { t: "name", name: t.s, pos: t.pos };
    }
    if (t.k === "op" && t.s === "(") {
      this.enter(t.pos);
      const n = this.or();
      this.leave();
      if (!this.isOp(")")) {
        const e = this.peek();
        throw new FormulaError(`EXPECTED ) AT ${e.pos + 1}`, e.pos);
      }
      this.next();
      return n;
    }
    throw new FormulaError(t.k === "end" ? `EXPECTED EXPRESSION AT ${t.pos + 1}` : `UNEXPECTED ${t.s} AT ${t.pos + 1}`, t.pos);
  }
}

// ---------------------------------------------------------------- evaluator

type V = number | A;
const isArr = (v: V): v is A => typeof v !== "number";

function toArr(v: V, n: number): A {
  return isArr(v) ? v : new Float64Array(n).fill(v);
}

function bin(a: V, b: V, n: number, f: (x: number, y: number) => number): V {
  if (!isArr(a) && !isArr(b)) return f(a, b);
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = f(isArr(a) ? a[i] : a, isArr(b) ? b[i] : b);
  return out;
}

const bool = (x: boolean) => (x ? 1 : 0);
const nanOr = (x: number, y: number, r: number) => (Number.isNaN(x) || Number.isNaN(y) ? NaN : r);

const BIN: Record<string, (x: number, y: number) => number> = {
  "+": (x, y) => x + y,
  "-": (x, y) => x - y,
  "*": (x, y) => x * y,
  "/": (x, y) => (y === 0 ? NaN : x / y),
  "^": (x, y) => {
    const r = x ** y;
    return Number.isFinite(r) ? r : NaN;
  },
  "<": (x, y) => nanOr(x, y, bool(x < y)),
  "<=": (x, y) => nanOr(x, y, bool(x <= y)),
  ">": (x, y) => nanOr(x, y, bool(x > y)),
  ">=": (x, y) => nanOr(x, y, bool(x >= y)),
  "==": (x, y) => nanOr(x, y, bool(x === y)),
  "!=": (x, y) => nanOr(x, y, bool(x !== y)),
  AND: (x, y) => nanOr(x, y, bool(x !== 0 && y !== 0)),
  OR: (x, y) => nanOr(x, y, bool(x !== 0 || y !== 0)),
};

/** Runs fn on the part of the series after its leading NaNs, so a computed series can feed a smoother. */
function onValid(src: A, fn: (a: A) => A): A {
  const f = firstFinite(src);
  if (f === 0) return fn(src);
  const out = nanArr(src.length);
  if (f < src.length) out.set(fn(src.subarray(f)), f);
  return out;
}

const MATH1: Record<string, (x: number) => number> = {
  ABS: Math.abs,
  LOG: (x) => (x > 0 ? Math.log10(x) : NaN),
  LN: (x) => (x > 0 ? Math.log(x) : NaN),
  SQRT: (x) => (x >= 0 ? Math.sqrt(x) : NaN),
  EXP: (x) => {
    const r = Math.exp(x);
    return Number.isFinite(r) ? r : NaN;
  },
  SIGN: Math.sign,
  FLOOR: Math.floor,
  CEIL: Math.ceil,
  ROUND: Math.round,
};

/** f(series, n). */
const SERIES: Record<string, (a: A, n: number) => A> = {
  SMA: smaN,
  EMA: emaN,
  WMA: wmaN,
  RMA: rmaN,
  HMA: (a, n) => onValid(a, (s) => hma(s, n)),
  DEMA: (a, n) => {
    const e1 = emaN(a, n);
    return zip(e1, emaN(e1, n), (x, y) => 2 * x - y);
  },
  TEMA: (a, n) => {
    const e1 = emaN(a, n);
    const e2 = emaN(e1, n);
    const e3 = emaN(e2, n);
    return map(a, (_, i) => 3 * e1[i] - 3 * e2[i] + e3[i]);
  },
  TRIMA: (a, n) => onValid(a, (s) => trima(s, n)),
  ZLEMA: (a, n) => onValid(a, (s) => zlema(s, n)),
  KAMA: (a, n) => onValid(a, (s) => kama(s, n)),
  RSI: (a, n) => onValid(a, (s) => rsi(s, n)),
  STDEV: stdN,
  VAR: (a, n) => map(stdN(a, n), (x) => x * x),
  SUM: sumN,
  HIGHEST: hi,
  LOWEST: lo,
  MEDIAN: (a, n) => onValid(a, (s) => medianN(s, n)),
  ROC: (a, n) => zip(a, lag(a, n), (x, y) => (y === 0 ? NaN : (x / y - 1) * 100)),
  MOM: (a, n) => diff(a, n),
  ZSCORE: (a, n) => {
    const m = smaN(a, n);
    const s = stdN(a, n);
    return map(a, (x, i) => (s[i] === 0 ? 0 : (x - m[i]) / s[i]));
  },
  LINREG: (a, n) => onValid(a, (s) => linreg(s, n).value),
  SLOPE: (a, n) => onValid(a, (s) => linreg(s, n).slope),
};

class Evaluator {
  constructor(private cols: Cols, private n = cols.c.length) {}

  private column(name: string): V | undefined {
    const { o, h, l, c, v } = this.cols;
    switch (name) {
      case "OPEN": case "O": return o;
      case "HIGH": case "H": return h;
      case "LOW": case "L": return l;
      case "CLOSE": case "C": return c;
      case "VOLUME": case "V": return v;
      case "HL2": return zip(h, l, (a, b) => (a + b) / 2);
      case "HLC3": return map(c, (x, i) => (h[i] + l[i] + x) / 3);
      case "OHLC4": return map(c, (x, i) => (o[i] + h[i] + l[i] + x) / 4);
      case "TRUE": return 1;
      case "FALSE": return 0;
      case "PI": return Math.PI;
      default: return undefined;
    }
  }

  eval(node: Node): V {
    const n = this.n;
    switch (node.t) {
      case "num":
        return node.v;
      case "name": {
        const v = this.column(node.name);
        if (v === undefined) throw new FormulaError(`UNKNOWN NAME ${node.name} AT ${node.pos + 1}`, node.pos);
        return v;
      }
      case "un": {
        const a = this.eval(node.a);
        return bin(a, 0, n, node.op === "-" ? (x) => -x : (x) => (Number.isNaN(x) ? NaN : bool(x === 0)));
      }
      case "bin":
        return bin(this.eval(node.a), this.eval(node.b), n, BIN[node.op]);
      case "call":
        return this.call(node);
    }
  }

  private scalar(node: Node, what: string): number {
    const v = this.eval(node);
    if (isArr(v)) throw new FormulaError(`${what} MUST BE A NUMBER AT ${node.pos + 1}`, node.pos);
    return v;
  }

  private count(node: Node, name: string, max = 5000): number {
    const v = this.scalar(node, "LENGTH");
    if (!Number.isInteger(v) || v < 1 || v > Math.max(max, 1)) throw new FormulaError(`${name} LENGTH MUST BE A WHOLE NUMBER FROM 1 TO ${Math.max(max, 1)} AT ${node.pos + 1}`, node.pos);
    return v;
  }

  private arity(node: Extract<Node, { t: "call" }>, k: number) {
    if (node.args.length !== k) throw new FormulaError(`${node.name} TAKES ${k} ARGUMENT${k === 1 ? "" : "S"} AT ${node.pos + 1}`, node.pos);
  }

  private call(node: Extract<Node, { t: "call" }>): V {
    const { name, args } = node;
    const n = this.n;
    if (MATH1[name]) {
      this.arity(node, 1);
      return bin(this.eval(args[0]), 0, n, (x) => MATH1[name](x));
    }
    switch (name) {
      case "POW":
        this.arity(node, 2);
        return bin(this.eval(args[0]), this.eval(args[1]), n, BIN["^"]);
      case "MAX":
      case "MIN": {
        this.arity(node, 2);
        const f = name === "MAX" ? Math.max : Math.min;
        return bin(this.eval(args[0]), this.eval(args[1]), n, (x, y) => (Number.isNaN(x) || Number.isNaN(y) ? NaN : f(x, y)));
      }
      case "IF": {
        this.arity(node, 3);
        const c = toArr(this.eval(args[0]), n);
        const a = this.eval(args[1]);
        const b = this.eval(args[2]);
        const out = new Float64Array(n);
        for (let i = 0; i < n; i++) out[i] = Number.isNaN(c[i]) ? NaN : c[i] !== 0 ? (isArr(a) ? a[i] : a) : isArr(b) ? b[i] : b;
        return out;
      }
      case "CROSSOVER":
      case "CROSSUNDER": {
        this.arity(node, 2);
        const a = toArr(this.eval(args[0]), n);
        const b = toArr(this.eval(args[1]), n);
        const out = nanArr(n);
        const up = name === "CROSSOVER";
        for (let i = 1; i < n; i++) {
          const now = a[i] - b[i];
          const was = a[i - 1] - b[i - 1];
          if (Number.isNaN(now) || Number.isNaN(was)) continue;
          out[i] = bool(up ? now > 0 && was <= 0 : now < 0 && was >= 0);
        }
        return out;
      }
      case "REF": {
        this.arity(node, 2);
        const k = this.scalar(args[1], "SHIFT");
        if (!Number.isInteger(k) || k < 0 || k > n) throw new FormulaError(`REF SHIFT MUST BE A WHOLE NUMBER FROM 0 TO ${n} AT ${args[1].pos + 1}`, args[1].pos);
        const a = this.eval(args[0]);
        return isArr(a) ? lag(a, k) : a;
      }
    }
    if (SERIES[name] && args.length === 2) {
      const src = toArr(this.eval(args[0]), n);
      return SERIES[name](src, this.count(args[1], name));
    }
    const def = findIndicator(name);
    if (def) {
      if (args.length > def.params.length) throw new FormulaError(`${name} TAKES AT MOST ${def.params.length} PARAMETER${def.params.length === 1 ? "" : "S"} AT ${node.pos + 1}`, node.pos);
      let given: number[];
      try {
        given = args.map((a) => this.scalar(a, "PARAMETER"));
      } catch (e) {
        if (SERIES[name]) throw new FormulaError(`${name} TAKES (SERIES, LENGTH) AT ${node.pos + 1}`, node.pos);
        throw e;
      }
      let oi = 0;
      if (node.out !== undefined) {
        oi = def.outputs.findIndex((o) => o.toUpperCase() === node.out);
        if (oi < 0) throw new FormulaError(`${name} HAS NO OUTPUT ${node.out}; USE ${def.outputs.join(", ").toUpperCase()} AT ${node.pos + 1}`, node.pos);
      }
      return def.fn(this.cols, resolveParams(def, given))[oi];
    }
    if (SERIES[name]) throw new FormulaError(`${name} TAKES (SERIES, LENGTH) AT ${node.pos + 1}`, node.pos);
    throw new FormulaError(`UNKNOWN FUNCTION ${name} AT ${node.pos + 1}`, node.pos);
  }
}

/** Parses only (cheap): used for live validation while typing. */
export function parseFormula(src: string): { ok: true } | { ok: false; error: string; pos: number } {
  try {
    if (src.length > MAX_FORMULA_LENGTH) throw new FormulaError(`FORMULA LONGER THAN ${MAX_FORMULA_LENGTH} CHARACTERS AT ${MAX_FORMULA_LENGTH + 1}`, MAX_FORMULA_LENGTH);
    if (!src.trim()) throw new FormulaError("EMPTY FORMULA AT 1", 0);
    new Parser(lex(src)).parse();
    return { ok: true };
  } catch (e) {
    if (e instanceof FormulaError) return { ok: false, error: e.message, pos: e.pos };
    throw e;
  }
}

/**
 * Checks names and function arities without data: runs the evaluator on a tiny synthetic series so unknown functions and
 * wrong argument counts show up in the library panel while typing.
 */
export function validateFormula(src: string): { ok: true } | { ok: false; error: string; pos: number } {
  const p = parseFormula(src);
  if (!p.ok) return p;
  const n = 64;
  const ramp = Float64Array.from({ length: n }, (_, i) => 100 + i);
  const r = evaluateFormula(src, { o: ramp, h: ramp.map((x) => x + 1), l: ramp.map((x) => x - 1), c: ramp, v: new Float64Array(n).fill(1000) });
  return r.ok ? { ok: true } : r;
}

export function evaluateFormula(src: string, cols: Cols): FormulaResult {
  try {
    const p = parseFormulaTree(src);
    const v = new Evaluator(cols).eval(p);
    const out = toArr(v, cols.c.length);
    // never hand infinities to the chart
    const res = out === cols.c || out === cols.o || out === cols.h || out === cols.l || out === cols.v ? out.slice() : out;
    for (let i = 0; i < res.length; i++) if (!Number.isFinite(res[i])) res[i] = NaN;
    return { ok: true, out: res };
  } catch (e) {
    if (e instanceof FormulaError) return { ok: false, error: e.message, pos: e.pos };
    throw e;
  }
}

function parseFormulaTree(src: string): Node {
  if (src.length > MAX_FORMULA_LENGTH) throw new FormulaError(`FORMULA LONGER THAN ${MAX_FORMULA_LENGTH} CHARACTERS AT ${MAX_FORMULA_LENGTH + 1}`, MAX_FORMULA_LENGTH);
  if (!src.trim()) throw new FormulaError("EMPTY FORMULA AT 1", 0);
  return new Parser(lex(src)).parse();
}
