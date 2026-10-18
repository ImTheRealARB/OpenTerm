/**
 * Phase 14: command arguments of the options, rates and futures functions -> API query parameters. Pure (no window), unit-tested.
 * `KEY=VALUE` tokens go through unchanged (the backend names them); positional tokens are recognised by shape, never guessed.
 */
import { keyValueArgs } from "../research/tablePayload";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const MONEYNESS = new Set(["ITM", "OTM", "ALL"]);

export interface Parsed {
  params: Record<string, string>;
  /** Tokens that were neither KEY=VALUE nor a recognised positional; the panel shows usage instead of loading. */
  bad: string[];
}

/** OMON: `[YYYY-MM-DD] [ITM|OTM|ALL] [Q=pct]` after the security. */
export function omonArgs(args: string[]): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const a = raw.toUpperCase();
    if (DATE.test(a)) params.date = a;
    else if (MONEYNESS.has(a)) params.moneyness = a;
    else if (a.startsWith("Q=") && a.length > 2) params.q = a.slice(2);
    else bad.push(raw);
  }
  return { params, bad };
}

/** Calculators: every token is `KEY=VALUE`. Keys are lower-cased; values keep their case (TYPE=C, BARR=UO, LEGS=+1C270@5). */
export function kvParams(args: string[]): Parsed {
  const { params, bad } = keyValueArgs(args);
  return { params, bad };
}

/** One positional word (a futures root, a CFTC market name, a currency pair) then optional KEY=VALUE tokens. */
export function wordThenKv(args: string[], key: string): Parsed {
  const words = args.filter((a) => !a.includes("="));
  const { params, bad } = keyValueArgs(args.filter((a) => a.includes("=")));
  if (words.length) params[key] = words.join(" ");
  return { params, bad };
}
