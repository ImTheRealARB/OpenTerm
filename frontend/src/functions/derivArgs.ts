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

const ROOT = /^[A-Z0-9]{1,4}$/;
const PAIR = /^[A-Z]{3}[/-]?[A-Z]{3}$/;
const TENORS = /^(\d+[WMY])(,\d+[WMY])*$/;

/** CT: one futures root (`CL`, `ES`, `6E`). Anything else is reported, never guessed. */
export function ctArgs(args: string[]): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const a = raw.toUpperCase();
    if (ROOT.test(a) && !params.root) params.root = a;
    else bad.push(raw);
  }
  return { params, bad };
}

/** FXFA: `<PAIR> [1W,1M,3M] [R1=pct] [R2=pct]`; the pair and the tenor list are recognised by shape. */
export function fxfaArgs(args: string[]): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const a = raw.toUpperCase();
    const i = a.indexOf("=");
    if (i > 0 && i < a.length - 1) {
      const k = a.slice(0, i).toLowerCase();
      if (k === "r1" || k === "r2" || k === "tenors") params[k] = a.slice(i + 1);
      else bad.push(raw);
    } else if (TENORS.test(a)) params.tenors = a;
    else if (PAIR.test(a) && !params.pair) params.pair = a.replace(/[/-]/g, "");
    else bad.push(raw);
  }
  return { params, bad };
}
