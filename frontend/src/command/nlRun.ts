/**
 * Glue between the command line and the plain-English parser (command/natural.ts). This file is tiny and sits in the startup
 * bundle; natural.ts and the company list (a 1 MB screener payload) are fetched with `import()` the first time something
 * that is not a valid command is typed. See natural.ts for the rules on when natural language is consulted.
 */
import { isFunction } from "../functions/registry";
import type { UniverseEntry } from "../gui/companySearch";
import { parseCommand } from "./parser";
import type { NlResult } from "./natural";

export type NlOutcome = NlResult | { kind: "asis" };

let universe: UniverseEntry[] | null = null;
let symbols: Set<string> | null = null;

const PANEL_PREFIX = /^([1-9])\s*:\s*/;

function split(input: string): { prefix: string; body: string } {
  const t = input.trim();
  const m = PANEL_PREFIX.exec(t);
  return { prefix: m ? `${m[1]}: ` : "", body: m ? t.slice(m[0].length) : t };
}

/** True when the typed text should be tried as plain English before (or instead of) running it as a command. */
export function needsNatural(input: string): boolean {
  const { body } = split(input);
  if (body.length < 3 || !/[a-zA-Z]/.test(body)) return false;
  const p = parseCommand(input, isFunction);
  if (!p.ok) return true; // BAD SYMBOL / UNKNOWN FUNCTION: the error is shown only if natural language finds nothing
  // Valid grammar always wins, except a lone lower-case word ("apple"): syntactically a ticker, but really a company name.
  if (p.fn || /\s/.test(body) || !/^[A-Za-z]{3,}$/.test(body) || body === body.toUpperCase()) return false;
  return !symbols?.has(body.toUpperCase());
}

async function load(): Promise<UniverseEntry[]> {
  if (universe) return universe;
  const m = await import("../gui/suggestData");
  universe = await m.loadUniverse();
  if (!universe.length) {
    // A failed load is not remembered (suggestData retries next time), and neither is it here.
    const empty = universe;
    universe = null;
    return empty;
  }
  symbols = new Set(universe.map((e) => e.symbol));
  return universe;
}

/** Interprets typed text. `asis`: run it exactly as typed (a real ticker, or nothing understood for a single word). */
export async function resolveNatural(input: string): Promise<NlOutcome> {
  const { prefix, body } = split(input);
  const [uni, nat] = await Promise.all([load(), import("./natural")]);
  const single = !/\s/.test(body);
  if (single && symbols?.has(body.toUpperCase())) return { kind: "asis" };
  const r = nat.interpretNatural(body, { isFunction, companies: uni.length ? uni : null });
  if (r.kind === "command") return { ...r, command: prefix + r.command };
  if (r.kind === "choices") return { kind: "choices", choices: r.choices.map((c) => ({ ...c, command: prefix + c.command })) };
  return single ? { kind: "asis" } : r;
}
