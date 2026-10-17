/**
 * BT rule syntax and command arguments (spec docs/specs/PHASE_12.md decision F). A line-for-line mirror of the
 * backend's `bt/rules.py` parser: same grammar, same messages, same 0-based error columns, so the panel can reject a
 * bad rule before anything is sent. The backend validates again; it is the authority.
 *
 *   rule := and_expr ("OR" and_expr)* ; and_expr := cmp ("AND" cmp)* ; cmp := term op term
 *   term := CLOSE | OPEN | HIGH | LOW | VOLUME | SMA<n> | EMA<n> | RSI<n> | HIGH<n> | LOW<n> | RET<n> | number
 */

export const MAX_PERIOD = 1000;
const FIELDS = new Set(["CLOSE", "OPEN", "HIGH", "LOW", "VOLUME"]);
const INDICATORS = new Set(["SMA", "EMA", "RSI", "HIGH", "LOW", "RET"]);
export const INTERVALS = ["1D", "1W"];
const RANGE_RE = /^(\d{1,2}Y|\d{1,2}M|MAX|YTD)$/;
const TOKEN_RE = /\s*(?:(CROSS[<>])|(>=|<=|>|<)|(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+\d*)|(\S))/iy;
/** `BT <SUB> ...` forms; anything else is `BT <SYMBOLS> <RULE> ...`. */
export const SUBCOMMANDS = new Set(["RUNS", "EXPORT", "SAVE", "LOAD", "DEL"]);
/** `BT MC|WF <SYMBOLS> <RULE> ...` runs the backtest, then validates it. */
const VALIDATIONS = new Set(["MC", "WF"]);

export type RuleCheck = { ok: true; error?: undefined; col?: undefined } | { ok: false; error: string; col: number };

interface Tok {
  kind: "op" | "num" | "word" | "junk" | "end";
  text: string;
  col: number;
}

class RuleError extends Error {
  constructor(message: string, public col = -1) {
    super(message);
  }
}

/** Python repr of a short token, as the backend's messages quote it. */
const repr = (s: string) => (s.includes("'") && !s.includes('"') ? `"${s}"` : `'${s.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`);

function tokens(text: string): Tok[] {
  const out: Tok[] = [];
  let pos = 0;
  while (pos < text.length) {
    TOKEN_RE.lastIndex = pos;
    const m = TOKEN_RE.exec(text);
    if (!m || TOKEN_RE.lastIndex === pos) break;
    const [, cross, op, num, word, junk] = m;
    const g = cross ?? op ?? num ?? word ?? junk ?? "";
    const col = m.index + m[0].length - g.length;
    if (cross) out.push({ kind: "op", text: cross.toUpperCase(), col });
    else if (op) out.push({ kind: "op", text: op, col });
    else if (num) out.push({ kind: "num", text: num, col });
    else if (word) out.push({ kind: "word", text: word.toUpperCase(), col });
    else if (junk) out.push({ kind: "junk", text: junk, col });
    pos = TOKEN_RE.lastIndex;
  }
  out.push({ kind: "end", text: "", col: text.trim() ? text.trimEnd().length : text.length });
  return out;
}

function parse(text: string): void {
  if (!text.trim()) throw new RuleError("EMPTY RULE", 0);
  if (text.length > 500) throw new RuleError("RULE IS TOO LONG (500 CHARACTERS MAX)", 500);
  const toks = tokens(text);
  let i = 0;
  const peek = () => toks[i];
  const take = () => toks[i++];

  const term = () => {
    const t = take();
    if (t.kind === "num") return;
    if (t.kind === "end") throw new RuleError("RULE ENDS TOO EARLY: EXPECTED A TERM", t.col);
    if (t.kind !== "word") throw new RuleError(`EXPECTED A TERM, GOT ${repr(t.text)}`, t.col);
    const m = /^([A-Z]+)(\d*)$/.exec(t.text)!;
    const [, name, digits] = m;
    if (!digits) {
      if (FIELDS.has(name)) return;
      throw new RuleError(`UNKNOWN TERM ${t.text}` + (INDICATORS.has(name) ? `: ${name} NEEDS A PERIOD, E.G. ${name}20` : ""), t.col);
    }
    if (!INDICATORS.has(name)) throw new RuleError(`UNKNOWN TERM ${t.text}`, t.col);
    const n = parseInt(digits, 10);
    if (!(n >= 1 && n <= MAX_PERIOD)) throw new RuleError(`${name} PERIOD MUST BE 1-${MAX_PERIOD}`, t.col);
    if (name === "RSI" && n < 2) throw new RuleError("RSI PERIOD MUST BE 2 OR MORE", t.col);
  };
  const cmp = () => {
    term();
    const t = take();
    if (t.kind !== "op") {
      throw new RuleError(t.kind === "end" ? "EXPECTED A COMPARISON (> < >= <= CROSS> CROSS<)" : `EXPECTED A COMPARISON, GOT ${repr(t.text)}`, t.col);
    }
    term();
  };
  const andExpr = () => {
    cmp();
    while (peek().kind === "word" && peek().text === "AND") {
      take();
      cmp();
    }
  };
  andExpr();
  while (peek().kind === "word" && peek().text === "OR") {
    take();
    andExpr();
  }
  const t = peek();
  if (t.kind !== "end") throw new RuleError(`UNEXPECTED ${repr(t.text)}`, t.col);
}

/** Checks a rule. Errors carry the backend's message and 0-based column. */
export function parseRule(text: string): RuleCheck {
  try {
    parse(text);
    return { ok: true };
  } catch (e) {
    if (e instanceof RuleError) return { ok: false, error: e.message, col: e.col };
    throw e;
  }
}

export interface BtRun {
  ok: true;
  sub?: undefined;
  symbols: string[];
  rule: string;
  interval: string;
  range: string;
  short: boolean;
  fees?: number;
  slip?: number;
  cash: number;
  bench?: string;
  mkt?: string;
  /** Validate the finished run: Monte Carlo (MC) or walk-forward (WF). */
  val?: "MC" | "WF";
}
export interface BtSub {
  ok: true;
  sub: string;
  args: string[];
}
/** `col` (0-based, into `rule`) is set only for rule syntax errors. */
export interface BtArgsError {
  ok: false;
  error: string;
  col?: number;
  rule?: string;
}
export type BtArgs = BtRun | BtSub | BtArgsError;
export const isBtRun = (a: BtArgs): a is BtRun => a.ok && a.sub === undefined;

export const BT_USAGE = "USAGE: BT <SYMBOLS> <RULE> [1D|1W] [RANGE] [SHORT] [FEES=bps] [SLIP=bps] [CASH=n] [BENCH=sym]";

function isOption(a: string): boolean {
  const u = a.toUpperCase();
  return INTERVALS.includes(u) || RANGE_RE.test(u) || u === "SHORT" || (u.includes("=") && ["FEES", "SLIP", "CASH", "BENCH", "MKT"].includes(u.split("=")[0]));
}

const DECIMAL = /^[+-]?(\d+(\.\d*)?|\.\d+)(e[+-]?\d+)?$/i;
const SPECIAL = /^[+-]?(inf(inity)?|nan)$/i; // Python float() accepts these; the range check then rejects them
/** Python's `{x:g}` for the bounds used here. */
const g = (x: number) => (Math.abs(x) >= 1e6 ? x.toExponential() : String(x));

function num(key: string, raw: string, lo: number, hi: number): number {
  const s = raw.trim();
  if (!DECIMAL.test(s) && !SPECIAL.test(s)) throw new RuleError(`${key}= NEEDS A NUMBER`);
  const v = DECIMAL.test(s) ? Number(s) : NaN;
  if (!(v >= lo && v <= hi)) throw new RuleError(`${key} MUST BE ${g(lo)}-${g(hi)}`);
  return v;
}

/** `BT` command arguments (as split by the command line) -> a run request, a subcommand, or an error. */
export function parseBtArgs(args: string[]): BtArgs {
  if (args.length && VALIDATIONS.has(args[0].toUpperCase())) {
    const val = args[0].toUpperCase() as "MC" | "WF";
    const inner = parseBtArgs(args.slice(1));
    if (inner.ok && inner.sub === undefined) return { ...inner, val };
    return inner.ok ? { ok: false, error: `BT ${val} <SYMBOLS> <RULE> [OPTIONS]: IT RUNS THE BACKTEST, THEN VALIDATES IT` } : inner;
  }
  if (args.length && SUBCOMMANDS.has(args[0].toUpperCase())) return { ok: true, sub: args[0].toUpperCase(), args: args.slice(1) };
  try {
    if (args.length < 2) throw new RuleError(BT_USAGE);
    const symbols = args[0].split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (!symbols.length || symbols.length > 100) throw new RuleError("BT NEEDS 1-100 SYMBOLS");
    const rest = args.slice(1);
    const ruleParts: string[] = [];
    while (rest.length && !isOption(rest[0])) ruleParts.push(rest.shift()!);
    const out: BtRun = { ok: true, symbols, rule: ruleParts.join(" "), interval: "1D", range: "5Y", short: false, cash: 100_000 };
    for (const a of rest) {
      const u = a.toUpperCase();
      if (INTERVALS.includes(u)) out.interval = u;
      else if (RANGE_RE.test(u)) out.range = u;
      else if (u === "SHORT") out.short = true;
      else if (u.startsWith("FEES=")) out.fees = num("FEES", u.slice(5), 0, 1000);
      else if (u.startsWith("SLIP=")) out.slip = num("SLIP", u.slice(5), 0, 1000);
      else if (u.startsWith("CASH=")) out.cash = num("CASH", u.slice(5), 1, 1e12);
      else if (u.startsWith("BENCH=")) out.bench = u.slice(6) || undefined;
      else if (u.startsWith("MKT=")) out.mkt = u.slice(4).toLowerCase() || undefined;
      else throw new RuleError(`UNKNOWN BT OPTION ${a}`);
    }
    const r = parseRule(out.rule);
    if (!r.ok) return { ok: false, error: r.error, col: r.col, rule: out.rule };
    return out;
  } catch (e) {
    if (e instanceof RuleError) return { ok: false, error: e.message };
    throw e;
  }
}
