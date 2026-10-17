/** `PORT` argument parsing. Pure (no store, no network) so it is unit-tested directly. */
import { LAYOUT_NAME_RE } from "../state/layoutState";
import { isSymbolToken, type SecurityRef } from "./markets";

export type PortAction =
  | { kind: "view"; name?: string }
  | { kind: "add"; name: string; symbol: string; qty: number; cost: number | null; currency?: string }
  | { kind: "remove"; name: string; symbols: string[] }
  | { kind: "delete"; name: string }
  | { kind: "export"; name: string }
  | { kind: "import"; name: string }
  | { kind: "base"; name: string; base: string }
  | { kind: "error"; message: string };

const NAME_ERR = "PORTFOLIO NAME: 1-32 OF A-Z 0-9 _ . -";
const USAGE = "USAGE: PORT [NAME] | PORT NAME ADD SYM QTY [COST] | PORT NAME RM SYM | PORT NAME EXPORT|IMPORT | PORT DEL NAME";
const ADD = new Set(["ADD", "+", "BUY"]);
const REMOVE = new Set(["RM", "REMOVE", "-"]);

/** "1,000", "-5", "2.5e3", "@150", "$150.25" -> number; anything else -> null. */
export function parseNumber(raw: string): number | null {
  let t = raw.trim().replace(/^[@$€£₹]/, "");
  if (/^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(t)) t = t.replace(/,/g, "");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/**
 * `PORT` (index), `PORT NAME`, `PORT NAME ADD SYM QTY [COST] [CCY]` (a lot: average cost), `PORT NAME RM SYM...`,
 * `PORT DEL NAME`, `PORT NAME EXPORT`, `PORT NAME IMPORT`, `PORT NAME BASE CCY`.
 * `AAPL PORT CORE ADD 10 150` adds the typed security; the panel's sticky security is never added silently.
 */
export function parsePort(args: string[], explicit?: SecurityRef): PortAction {
  if (!args.length) return { kind: "view" };
  const first = args[0].toUpperCase();
  if (first === "DEL" || first === "DELETE") {
    if (!args[1]) return { kind: "error", message: "PORT DEL NEEDS A NAME" };
    const name = args[1].toUpperCase();
    return LAYOUT_NAME_RE.test(name) ? { kind: "delete", name } : { kind: "error", message: NAME_ERR };
  }
  if (!LAYOUT_NAME_RE.test(first)) return { kind: "error", message: NAME_ERR };
  const name = first;
  if (args.length === 1) return { kind: "view", name };
  const verb = args[1].toUpperCase();
  const rest = args.slice(2);
  if (verb === "EXPORT" || verb === "IMPORT") {
    return rest.length ? { kind: "error", message: USAGE } : { kind: verb === "EXPORT" ? "export" : "import", name };
  }
  if (verb === "BASE") {
    const base = rest[0]?.toUpperCase();
    return base && /^[A-Z]{3}$/.test(base) && rest.length === 1
      ? { kind: "base", name, base }
      : { kind: "error", message: `PORT ${name} BASE NEEDS A CURRENCY, E.G. PORT ${name} BASE EUR` };
  }
  if (REMOVE.has(verb)) {
    const syms = [...new Set(rest.map((a) => a.toUpperCase()))];
    if (!syms.length) return { kind: "error", message: `PORT ${name} RM NEEDS A SYMBOL` };
    const bad = syms.find((s) => !isSymbolToken(s));
    return bad ? { kind: "error", message: `BAD SYMBOL: ${bad}` } : { kind: "remove", name, symbols: syms };
  }
  if (!ADD.has(verb)) return { kind: "error", message: USAGE };

  // ADD: [SYM] QTY [COST] [CCY]. The symbol may come from the typed security.
  let toks = rest;
  let symbol: string | undefined;
  if (explicit && (toks.length === 0 || parseNumber(toks[0]) !== null)) symbol = explicit.symbol;
  else {
    symbol = toks[0]?.toUpperCase();
    toks = toks.slice(1);
  }
  const example = `E.G. PORT ${name} ADD AAPL 10 150`;
  if (!symbol) return { kind: "error", message: `PORT ${name} ADD NEEDS SYM QTY [COST], ${example}` };
  if (!isSymbolToken(symbol)) return { kind: "error", message: `BAD SYMBOL: ${symbol}` };
  if (!toks.length) return { kind: "error", message: `PORT ${name} ADD ${symbol} NEEDS A QUANTITY, ${example}` };
  if (toks.length > 3) return { kind: "error", message: USAGE };
  const qty = parseNumber(toks[0]);
  if (qty === null || qty === 0) return { kind: "error", message: `BAD QUANTITY: ${toks[0]}` };
  let cost: number | null = null;
  let currency: string | undefined;
  for (const t of toks.slice(1)) {
    if (/^[A-Za-z]{3}$/.test(t) && currency === undefined) currency = t === "GBp" || t === "ZAc" ? t : t.toUpperCase();
    else if (cost === null && parseNumber(t) !== null) {
      cost = parseNumber(t);
      if (cost! < 0) return { kind: "error", message: `BAD COST: ${t}` };
    } else return { kind: "error", message: `BAD COST: ${t}` };
  }
  return { kind: "add", name, symbol, qty, cost, ...(currency ? { currency } : {}) };
}
