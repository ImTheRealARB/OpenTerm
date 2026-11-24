/**
 * `BT OPT` arguments (Phase 26) -> the POST /api/bt/opt body. Pure, so vitest can cover it.
 *
 *   BT OPT AAPL SMA{10..50:5}>SMA{50..200:25} 1D 10Y [METHOD=GRID|RANDOM|GA] [N=200] [POP=40] [GEN=25] [SEED=1]
 *          [FIT=SHARPE|SORTINO|CALMAR|PF|NET|RETURN] [WF=5] [ANCHORED] [STOP=5] [TARGET=10] [FILL=INTRABAR] ...
 *   BT OPT AAPL @mystrategy FAST={10..50:5} SLOW={50..200:25} ...     (a saved Python strategy: its constants get the ranges)
 *
 * The rule itself is checked here by putting each range's first value in place (`SMA{10..50:5}` -> `SMA10`) and running
 * the normal rule parser; the backend checks every combination's shape again before it starts.
 */
import { applyRunOption, checkExits, isOption, parseRule, RuleError, type BtRun } from "./ruleParse";
import type { BtRunRequest } from "../net/types";

export interface BtOptRequest {
  symbols: string[];
  interval: string;
  range: string;
  options: BtRunRequest["options"];
  rule?: string;
  strategy?: string;
  /** Python strategy constants -> "{lo..hi:step}". */
  ranges?: Record<string, string>;
  method: "GRID" | "RANDOM" | "GA";
  fit: string;
  n?: number;
  pop?: number;
  gen?: number;
  seed?: number;
  wf?: number;
  anchored?: boolean;
}

export type OptArgs = { ok: true; req: BtOptRequest } | { ok: false; error: string };

export const OPT_USAGE =
  "USAGE: BT OPT <SYMBOLS> <RULE WITH {LO..HI:STEP} RANGES> [1D|1W] [RANGE] [METHOD=GRID|RANDOM|GA] [N=] [POP=] [GEN=] [SEED=] [FIT=SHARPE|SORTINO|CALMAR|PF|NET|RETURN] [WF=5] [ANCHORED] [STOP=%] [TARGET=%] [FILL=INTRABAR]";
export const OPT_EXAMPLE = "BT OPT AAPL SMA{10..50:5}>SMA{50..200:25} 1D 10Y · PYTHON: BT OPT AAPL @NAME FAST={10..50:5}";

const RANGE_RE = /\{\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)\s*(?::\s*(\d+(?:\.\d+)?))?\s*\}/g;
const METHODS = ["GRID", "RANDOM", "GA"] as const;
export const FITS = ["SHARPE", "SORTINO", "CALMAR", "PF", "NET", "RETURN"];
const STRATEGY_RE = /^@([A-Za-z0-9_-]{1,40})$/;
const NAMED_RANGE = /^([A-Z_][A-Z0-9_]{0,39})=(\{.*\})$/;

function int(key: string, raw: string, lo: number, hi: number): number {
  const v = Number(raw);
  if (!/^\d+$/.test(raw) || v < lo || v > hi) throw new RuleError(`${key} MUST BE A WHOLE NUMBER ${lo}-${hi}`);
  return v;
}

/** The OPT-only words (not BT run options). */
function isOptWord(a: string): boolean {
  const u = a.toUpperCase();
  return u === "ANCHORED" || NAMED_RANGE.test(u) || (u.includes("=") && ["METHOD", "N", "POP", "GEN", "SEED", "FIT", "WF"].includes(u.split("=")[0]));
}

/** The rule with every range replaced by its first value (what the normal rule parser can check). */
export function firstValues(template: string): string {
  return template.replace(RANGE_RE, (_m, lo: string) => lo);
}

export function parseOptArgs(args: string[]): OptArgs {
  try {
    if (args.length < 2) throw new RuleError(OPT_USAGE);
    const symbols = args[0].split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (!symbols.length || symbols.length > 100) throw new RuleError("BT OPT NEEDS 1-100 SYMBOLS");
    const rest = args.slice(1);
    const ruleParts: string[] = [];
    while (rest.length && !isOption(rest[0]) && !isOptWord(rest[0])) ruleParts.push(rest.shift()!);
    const run: BtRun = { ok: true, symbols, rule: ruleParts.join(" "), interval: "1D", range: "5Y", short: false, cash: 100_000 };
    const req: BtOptRequest = { symbols, interval: "1D", range: "5Y", options: {}, method: "GRID", fit: "SHARPE" };
    const ranges: Record<string, string> = {};
    for (const a of rest) {
      if (applyRunOption(run, a)) continue;
      const u = a.toUpperCase();
      const named = NAMED_RANGE.exec(u);
      if (named) ranges[named[1]] = named[2];
      else if (u === "ANCHORED") req.anchored = true;
      else if (u.startsWith("METHOD=")) {
        const m = u.slice(7) as BtOptRequest["method"];
        if (!METHODS.includes(m)) throw new RuleError(`METHOD= MUST BE ${METHODS.join(" OR ")}`);
        req.method = m;
      } else if (u.startsWith("FIT=")) {
        if (!FITS.includes(u.slice(4))) throw new RuleError(`FIT= MUST BE ${FITS.join(" OR ")}`);
        req.fit = u.slice(4);
      } else if (u.startsWith("N=")) req.n = int("N", u.slice(2), 2, 2000);
      else if (u.startsWith("POP=")) req.pop = int("POP", u.slice(4), 4, 200);
      else if (u.startsWith("GEN=")) req.gen = int("GEN", u.slice(4), 1, 100);
      else if (u.startsWith("SEED=")) req.seed = int("SEED", u.slice(5), 0, 2 ** 31 - 1);
      else if (u.startsWith("WF=")) req.wf = int("WF", u.slice(3), 2, 12);
      else throw new RuleError(`UNKNOWN BT OPT OPTION ${a}`);
    }
    checkExits(run);
    if (run.mkt) throw new RuleError("BT OPT TAKES A RULE OR A PYTHON STRATEGY (NO MKT=)");
    if (req.anchored && !req.wf) throw new RuleError("ANCHORED NEEDS WF=<WINDOWS>, E.G. WF=5 ANCHORED");
    req.interval = run.interval;
    req.range = run.range;
    req.options = {
      ...(run.short ? { short: true } : {}), ...(run.fees !== undefined ? { fees_bps: run.fees } : {}),
      ...(run.slip !== undefined ? { slip_bps: run.slip } : {}), ...(run.cash !== 100_000 ? { cash: run.cash } : {}),
      ...(run.stop !== undefined ? { stop_pct: run.stop } : {}), ...(run.target !== undefined ? { target_pct: run.target } : {}),
      ...(run.fill ? { fill: run.fill } : {}),
    };
    const named = STRATEGY_RE.exec(run.rule);
    if (named) {
      if (!Object.keys(ranges).length) throw new RuleError(`GIVE THE RANGES OF @${named[1].toUpperCase()}'S CONSTANTS, E.G. FAST={10..50:5}`);
      return { ok: true, req: { ...req, strategy: named[1].toLowerCase(), ranges } };
    }
    if (Object.keys(ranges).length) throw new RuleError("NAME={..} RANGES ARE FOR A SAVED PYTHON STRATEGY (@NAME); IN A RULE WRITE THE RANGE IN PLACE");
    if (!run.rule) throw new RuleError(OPT_USAGE);
    if (!new RegExp(RANGE_RE.source).test(run.rule)) throw new RuleError("PUT AT LEAST ONE RANGE IN THE RULE, E.G. SMA{10..50:5}>SMA{50..200:25}");
    const check = parseRule(firstValues(run.rule));
    if (!check.ok) throw new RuleError(`${check.error} (CHECKED WITH EACH RANGE'S FIRST VALUE: ${firstValues(run.rule)})`);
    return { ok: true, req: { ...req, rule: run.rule } };
  } catch (e) {
    if (e instanceof RuleError) return { ok: false, error: e.message };
    throw e;
  }
}

/** Index of each parameter's value in a run -> the concrete rule (Enter on a row runs it as a normal BT). */
export function renderRule(template: string, values: string[]): string {
  let k = 0;
  return template.replace(RANGE_RE, () => values[k++] ?? "");
}
