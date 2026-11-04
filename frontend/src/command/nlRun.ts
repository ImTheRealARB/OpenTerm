/**
 * Glue between the command line and the plain-English parser (command/natural.ts). This file is tiny and sits in the startup
 * bundle; natural.ts and the company list (a 1 MB screener payload) are fetched with `import()` the first time something
 * that is not a valid command is typed. See natural.ts for the rules on when natural language is consulted.
 */
import { isFunction } from "../functions/registry";
import { parseCommand } from "./parser";
import type { NlResult } from "./natural";

export type NlOutcome = NlResult | { kind: "asis" };

/** Tickers of the company list once it has been loaded (set by nlResolve.ts); null before that. */
export const known: { symbols: Set<string> | null } = { symbols: null };

export const PANEL_PREFIX = /^\s*([1-9])\s*:\s*/;

/** True when the typed text should be tried as plain English before (or instead of) running it as a command. */
export function needsNatural(input: string): boolean {
  const body = input.replace(PANEL_PREFIX, "").trim();
  if (body.length < 3 || !/[a-zA-Z]/.test(body)) return false;
  const p = parseCommand(input, isFunction);
  if (!p.ok) return true; // BAD SYMBOL / UNKNOWN FUNCTION: the error is shown only if natural language finds nothing
  // Valid grammar always wins, except a lone lower-case word ("apple"): syntactically a ticker, but really a company name.
  if (p.fn || /\s/.test(body) || !/^[A-Za-z]{3,}$/.test(body) || body === body.toUpperCase()) return false;
  return !known.symbols?.has(body.toUpperCase());
}

/** Interprets typed text (see nlResolve.ts). `asis`: run it exactly as typed. */
export const resolveNatural = (input: string): Promise<NlOutcome> => import("./nlResolve").then((m) => m.resolveNatural(input));
