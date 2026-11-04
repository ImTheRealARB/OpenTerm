/**
 * Plain-English view of a BT rule (GUI rule builder). Pure: no DOM, no network.
 *
 * The BT grammar (bt/ruleParse.ts, backend bt/rules.py) is ONE boolean expression: `or := and (OR and)*`,
 * `and := cmp (AND cmp)*`, `cmp := term op term`. The strategy is long while the rule is true and flat (or short with
 * SHORT) otherwise, so there is no separate "sell" rule: selling is "the buy rule stopped being true". For a cross
 * (`A CROSS> B`) the rule stays true from the cross until the opposite cross, so the sentence says "sell when it crosses
 * back below". This module only offers what the grammar supports and never changes its meaning.
 *
 *   ruleToForm(rule)        rule text -> Form, or null (invalid, a saved @strategy, or a number it cannot print)
 *   formToRule(form)        Form -> the exact rule text the grammar accepts (upper case, ` AND ` / ` OR `)
 *   formToSentence(form)    "Buy when the 20-day average crosses above the 50-day average; sell when it crosses back below."
 *   ruleToSentence(rule)    the two above in one step; null when unsupported (the caller shows the raw rule)
 */
import { MAX_PERIOD, parseRule } from "../bt/ruleParse";

export type Op = "crosses above" | "crosses below" | "is above" | "is below" | "is at least" | "is at most";
export type OperandKind = "price" | "open" | "high" | "low" | "volume" | "sma" | "ema" | "rsi" | "highn" | "lown" | "ret" | "number";
/** `n` is the period (average, RSI, high/low/return) or the value (number); ignored for price/open/high/low/volume. */
export interface Operand {
  kind: OperandKind;
  n: number;
}
export interface Clause {
  left: Operand;
  op: Op;
  right: Operand;
}
/** `buy` = OR of AND-groups: `[[a, b], [c]]` is `a AND b OR c`. */
export interface Form {
  buy: Clause[][];
}

export const OPS: { op: Op; sym: string }[] = [
  { op: "crosses above", sym: "CROSS>" },
  { op: "crosses below", sym: "CROSS<" },
  { op: "is above", sym: ">" },
  { op: "is below", sym: "<" },
  { op: "is at least", sym: ">=" },
  { op: "is at most", sym: "<=" },
];
const SYM_OF = new Map(OPS.map((o) => [o.op, o.sym]));
const OP_OF = new Map(OPS.map((o) => [o.sym, o.op]));

/** Operand kinds in the order a form offers them; `period` kinds take an N, `number` takes a value. */
export const OPERANDS: { kind: OperandKind; label: string; word: string; period: boolean; def: number }[] = [
  { kind: "price", label: "price", word: "CLOSE", period: false, def: 0 },
  { kind: "open", label: "opening price", word: "OPEN", period: false, def: 0 },
  { kind: "high", label: "day's high", word: "HIGH", period: false, def: 0 },
  { kind: "low", label: "day's low", word: "LOW", period: false, def: 0 },
  { kind: "volume", label: "volume", word: "VOLUME", period: false, def: 0 },
  { kind: "sma", label: "-day average", word: "SMA", period: true, def: 20 },
  { kind: "ema", label: "-day exponential average", word: "EMA", period: true, def: 20 },
  { kind: "rsi", label: "-day RSI", word: "RSI", period: true, def: 14 },
  { kind: "highn", label: "-day high", word: "HIGH", period: true, def: 20 },
  { kind: "lown", label: "-day low", word: "LOW", period: true, def: 20 },
  { kind: "ret", label: "-day return", word: "RET", period: true, def: 20 },
  { kind: "number", label: "a number", word: "", period: false, def: 0 },
];
const META = new Map(OPERANDS.map((o) => [o.kind, o]));

export const isPeriodKind = (k: OperandKind) => META.get(k)!.period;
export const defaultOperand = (kind: OperandKind): Operand => ({ kind, n: META.get(kind)!.def });
export const emptyClause = (): Clause => ({ left: defaultOperand("sma"), op: "crosses above", right: { kind: "sma", n: 50 } });

/** A finite number the grammar's number token can carry (plain digits, no exponent). */
const printable = (n: number) => Number.isFinite(n) && n >= 0 && n < 1e15 && /^\d+(\.\d+)?$/.test(String(n));

function operandRule(o: Operand): string {
  const m = META.get(o.kind)!;
  if (o.kind === "number") return String(o.n);
  return m.period ? `${m.word}${Math.trunc(o.n)}` : m.word;
}

export function formToRule(form: Form): string {
  return form.buy
    .filter((g) => g.length)
    .map((g) => g.map((c) => `${operandRule(c.left)} ${SYM_OF.get(c.op)} ${operandRule(c.right)}`).join(" AND "))
    .join(" OR ");
}

/** Whether `formToRule(form)` is accepted by the grammar (periods in range, RSI >= 2, numbers printable). */
export function formError(form: Form): string | null {
  const text = formToRule(form);
  if (!text) return "Add a condition.";
  for (const g of form.buy)
    for (const c of g)
      for (const o of [c.left, c.right]) {
        const m = META.get(o.kind)!;
        if (o.kind === "number" && !printable(o.n)) return "Use a plain number such as 30 or 0.05.";
        if (m.period && !(Number.isInteger(o.n) && o.n >= 1 && o.n <= MAX_PERIOD)) return `Periods are whole numbers from 1 to ${MAX_PERIOD}.`;
        if (o.kind === "rsi" && o.n < 2) return "RSI needs a period of 2 or more.";
      }
  const r = parseRule(text);
  return r.ok ? null : r.error;
}

// ---- rule text -> form ---------------------------------------------------------------------------------------------

const TOKEN = /\s*(?:(CROSS[<>])|(>=|<=|>|<)|(\d+(?:\.\d+)?|\.\d+)|([A-Za-z]+\d*)|(\S))/iy;

function lex(text: string): string[] | null {
  const out: string[] = [];
  let pos = 0;
  while (pos < text.length) {
    TOKEN.lastIndex = pos;
    const m = TOKEN.exec(text);
    if (!m || TOKEN.lastIndex === pos) break;
    out.push((m[1] ?? m[2] ?? m[3] ?? m[4] ?? m[5] ?? "").toUpperCase());
    pos = TOKEN.lastIndex;
  }
  return out;
}

function operand(tok: string): Operand | null {
  if (/^(\d+(\.\d+)?|\.\d+)$/.test(tok)) {
    const n = Number(tok);
    return printable(n) ? { kind: "number", n } : null;
  }
  const m = /^([A-Z]+)(\d*)$/.exec(tok);
  if (!m) return null;
  const [, name, digits] = m;
  if (!digits) {
    const hit = OPERANDS.find((o) => !o.period && o.word === name && o.kind !== "number");
    return hit ? { kind: hit.kind, n: 0 } : null;
  }
  const hit = OPERANDS.find((o) => o.period && o.word === name);
  return hit ? { kind: hit.kind, n: parseInt(digits, 10) } : null;
}

export function ruleToForm(rule: string): Form | null {
  if (!parseRule(rule).ok) return null; // also rejects "@strategy", empty and over-long rules
  const toks = lex(rule);
  if (!toks) return null;
  const buy: Clause[][] = [[]];
  let i = 0;
  while (i < toks.length) {
    const l = operand(toks[i]);
    const op = OP_OF.get(toks[i + 1]);
    const r = operand(toks[i + 2]);
    if (!l || !op || !r) return null;
    buy[buy.length - 1].push({ left: l, op, right: r });
    i += 3;
    if (i >= toks.length) break;
    if (toks[i] === "AND") i++;
    else if (toks[i] === "OR") {
      buy.push([]);
      i++;
    } else return null;
  }
  return { buy };
}

// ---- form -> sentence ----------------------------------------------------------------------------------------------

export function operandText(o: Operand): string {
  switch (o.kind) {
    case "price": return "the price";
    case "open": return "the opening price";
    case "high": return "the day's high";
    case "low": return "the day's low";
    case "volume": return "the volume";
    case "sma": return `the ${o.n}-day average`;
    case "ema": return `the ${o.n}-day exponential average`;
    case "rsi": return `the ${o.n}-day RSI`;
    case "highn": return `the ${o.n}-day high`;
    case "lown": return `the ${o.n}-day low`;
    case "ret": return `the ${o.n}-day return`;
    case "number": return String(o.n);
  }
}

export const clauseText = (c: Clause) => `${operandText(c.left)} ${c.op} ${operandText(c.right)}`;

export function formToSentence(form: Form): string {
  const groups = form.buy.filter((g) => g.length);
  if (!groups.length) return "";
  const buy = groups.map((g) => g.map(clauseText).join(" and ")).join(", or when ");
  const only = groups.length === 1 && groups[0].length === 1 ? groups[0][0] : null;
  let sell = "sell when that stops being true";
  if (only?.op === "crosses above") sell = "sell when it crosses back below";
  else if (only?.op === "crosses below") sell = "sell when it crosses back above";
  return `Buy when ${buy}; ${sell}.`;
}

export function ruleToSentence(rule: string): string | null {
  const f = ruleToForm(rule);
  return f ? formToSentence(f) : null;
}

/** Name used in the step-5 spec. */
export const sentenceFormToRule = formToRule;
