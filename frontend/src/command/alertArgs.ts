/** `ALRT` argument parsing and alert condition evaluation. Pure, unit-tested directly. */
import { isSymbolToken, type SecurityRef } from "./markets";

export interface AlertRule {
  op: ">" | "<";
  /** price = absolute level; pct = percent change vs previous close. */
  unit: "price" | "pct";
  value: number;
}

export type AlrtAction =
  | { kind: "list" }
  | { kind: "create"; symbol: string; rule: AlertRule }
  | { kind: "delete"; id: number }
  | { kind: "rearm"; id: number }
  | { kind: "clear" }
  | { kind: "error"; message: string };

const USAGE = "USAGE: ALRT | ALRT SYM > 200 | ALRT SYM < 180 | ALRT SYM +5% | ALRT SYM -3% | ALRT DEL ID | ALRT CLEAR";
const COND = /^(>=?|<=?)?([+-])?(\d+(?:\.\d+)?|\.\d+)(%)?$/;

function idAction(kind: "delete" | "rearm", raw: string | undefined): AlrtAction {
  const id = Number(raw);
  return raw && /^\d+$/.test(raw) && id > 0 ? { kind, id } : { kind: "error", message: `ALRT ${kind === "delete" ? "DEL" : "REARM"} NEEDS AN ALERT ID, E.G. ALRT ${kind === "delete" ? "DEL" : "REARM"} 3` };
}

/** Parses the condition part: "> 200", ">=200", "+5%", "-3%", "> 5%", "< -2%". */
export function parseRule(text: string): AlertRule | string {
  const m = COND.exec(text.replace(/\s+/g, ""));
  if (!m) return USAGE;
  const [, opRaw, sign, num, pct] = m;
  const n = Number(num);
  if (!pct) {
    if (!opRaw) return "PRICE ALERTS NEED > OR <, E.G. ALRT AAPL > 200";
    if (sign === "-" || n <= 0) return "PRICE LEVEL MUST BE ABOVE 0";
    return { op: opRaw[0] as ">" | "<", unit: "price", value: n };
  }
  const value = sign === "-" ? -n : n;
  if (value === 0) return "PERCENT MUST NOT BE 0";
  if (Math.abs(value) > 1000) return "PERCENT MUST BE AT MOST 1000";
  if (opRaw) return { op: opRaw[0] as ">" | "<", unit: "pct", value };
  if (!sign) return `SAY +${n}% (UP) OR -${n}% (DOWN)`;
  return { op: sign === "+" ? ">" : "<", unit: "pct", value };
}

/**
 * `ALRT` (list), `ALRT SYM > 200`, `ALRT SYM < 180`, `ALRT SYM +5%` / `-3%` (vs previous close), `ALRT DEL id`,
 * `ALRT REARM id`, `ALRT CLEAR` (removes triggered alerts). `AAPL ALRT > 200` uses the typed security.
 */
export function parseAlrt(args: string[], explicit?: SecurityRef): AlrtAction {
  if (!args.length) return explicit ? { kind: "error", message: `ALRT NEEDS A CONDITION, E.G. ${explicit.symbol} ALRT > 200` } : { kind: "list" };
  const first = args[0].toUpperCase();
  if (first === "DEL" || first === "DELETE" || first === "RM") return args.length === 2 ? idAction("delete", args[1]) : idAction("delete", undefined);
  if (first === "REARM") return args.length === 2 ? idAction("rearm", args[1]) : idAction("rearm", undefined);
  if (first === "CLEAR") return args.length === 1 ? { kind: "clear" } : { kind: "error", message: USAGE };

  // Split operators off the tokens so "AAPL>200" and "AAPL > 200" read the same.
  const toks = args.join(" ").replace(/(>=?|<=?)/g, " $1 ").trim().split(/\s+/);
  const condStart = (t: string) => /^[<>+-]/.test(t) || /^[\d.]+%?$/.test(t);
  let symbol: string;
  let cond: string[];
  if (explicit && condStart(toks[0])) {
    symbol = explicit.symbol;
    cond = toks;
  } else {
    symbol = toks[0].toUpperCase();
    cond = toks.slice(1);
  }
  if (!isSymbolToken(symbol)) return { kind: "error", message: `BAD SYMBOL: ${symbol}` };
  if (!cond.length) return { kind: "error", message: `ALRT ${symbol} NEEDS A CONDITION, E.G. ALRT ${symbol} > 200 OR ALRT ${symbol} +5%` };
  const rule = parseRule(cond.join(""));
  return typeof rule === "string" ? { kind: "error", message: rule } : { kind: "create", symbol, rule };
}

/** Percent change vs previous close from a tick: its own pct, else derived from the absolute change. */
export function tickPct(price: number, pct: number | null, change: number | null): number | null {
  if (pct != null && Number.isFinite(pct)) return pct;
  if (change == null || !Number.isFinite(change)) return null;
  const prev = price - change;
  return prev > 0 ? (change / prev) * 100 : null;
}

/** True when the condition holds (levels are inclusive: "> 200" fires at 200.00). */
export function alertMet(rule: AlertRule, price: number, pct: number | null, change: number | null): boolean {
  if (!Number.isFinite(price)) return false;
  const x = rule.unit === "price" ? price : tickPct(price, pct, change);
  if (x == null) return false;
  return rule.op === ">" ? x >= rule.value : x <= rule.value;
}

export function describeRule(r: AlertRule): string {
  if (r.unit === "price") return `${r.op} ${r.value}`;
  const s = `${r.value > 0 ? "+" : ""}${r.value}%`;
  const natural = (r.op === ">" && r.value > 0) || (r.op === "<" && r.value < 0);
  return natural ? s : `${r.op} ${s}`;
}
