/**
 * Phase 15: command arguments of RISK, PORT OPT and PORT ATTR -> the string params of a quant job, and `quantBody`, which types them
 * for `POST /api/quant/{fn}`. Pure (no window), unit-tested. Anything not recognised is reported in `bad`, never guessed.
 */
import type { Parsed } from "./derivArgs";

export type { Parsed };

const NAME = /^[A-Za-z0-9_.-]{1,40}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const NUM = /^-?\d+(\.\d+)?$/;

type Norm = (v: string) => string;
const upper: Norm = (v) => v.toUpperCase();
const lower: Norm = (v) => v.toLowerCase();
const same: Norm = (v) => v;

/** One portfolio word, then KEY=VALUE pairs of the allowed keys (key -> how its value is normalised). */
function portfolioKv(args: string[], keys: Record<string, Norm>): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const i = raw.indexOf("=");
    if (i < 0) {
      if (NAME.test(raw) && !params.portfolio) params.portfolio = raw.toUpperCase();
      else bad.push(raw);
      continue;
    }
    const k = raw.slice(0, i).toLowerCase();
    const v = raw.slice(i + 1);
    if (!v || !(k in keys)) bad.push(raw);
    else params[k] = keys[k](v);
  }
  return { params, bad };
}

/** RISK: `[PORTFOLIO] [RANGE=3y] [BENCH=SPY] [CONF=95] [HOR=1]`. */
export function riskArgs(args: string[]): Parsed {
  return portfolioKv(args, { range: lower, bench: upper, conf: same, hor: same });
}

/** PORT OPT: `[PORTFOLIO] [METHOD=..] [CAP=] [LOOKBACK=] [RF=] [TC=]`. */
export function optArgs(args: string[]): Parsed {
  return portfolioKv(args, { method: upper, cap: same, lookback: same, rf: same, tc: same });
}

export type AttrAction = { kind: "add"; date: string; value: string; flow?: string } | { kind: "del"; date: string };

export interface AttrParsed extends Parsed {
  action?: AttrAction;
}

/** PORT ATTR: `[PORTFOLIO] [BENCH=SPY] [RANGE=1y]`, or `[PORTFOLIO] ADD <date> VALUE= [FLOW=]` / `[PORTFOLIO] DEL <date>`. */
export function attrArgs(args: string[]): AttrParsed {
  const i = args.findIndex((a) => a.toUpperCase() === "ADD" || a.toUpperCase() === "DEL");
  if (i < 0) return portfolioKv(args, { bench: upper, range: lower });
  const kind = args[i].toUpperCase() === "ADD" ? "add" : "del";
  const head = portfolioKv(args.slice(0, i), {});
  const params: Record<string, string> = { ...head.params };
  const bad = [...head.bad];
  if (!params.portfolio) bad.push("PORTFOLIO");
  let date = "";
  let value: string | undefined;
  let flow: string | undefined;
  for (const raw of args.slice(i + 1)) {
    const j = raw.indexOf("=");
    const k = j > 0 ? raw.slice(0, j).toLowerCase() : "";
    const v = j > 0 ? raw.slice(j + 1) : "";
    if (DATE.test(raw) && !date) date = raw;
    else if (kind === "add" && k === "value" && NUM.test(v)) value = v;
    else if (kind === "add" && k === "flow" && NUM.test(v)) flow = v;
    else bad.push(raw);
  }
  if (!date && !bad.some((b) => !b.includes("=") && b !== "PORTFOLIO")) bad.push("DATE");
  if (kind === "add" && value === undefined && !bad.some((b) => b.toUpperCase().startsWith("VALUE="))) bad.push("VALUE=");
  if (kind === "del") return { params, action: { kind, date }, bad };
  return { params, action: { kind, date, value: value ?? "", ...(flow !== undefined ? { flow } : {}) }, bad };
}

/** Params that are numbers in the job body; `h` is a list of numbers. Other values (symbols, calc, universe) stay strings. */
const NUMERIC = new Set(["conf", "hor", "cap", "lookback", "rf", "tc", "sr", "n", "t", "win", "edge"]);
const LISTS = new Set(["h"]);

/** The JSON body of `POST /api/quant/{fn}`: numeric params as numbers, horizon lists as arrays, symbols as given. */
export function quantBody(_fn: string, params: Record<string, string | string[]>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) body[k] = v;
    else if (LISTS.has(k)) body[k] = v.split(",").map((x) => (NUM.test(x.trim()) ? Number(x) : x.trim()));
    else if (NUMERIC.has(k) && NUM.test(v)) body[k] = Number(v);
    else body[k] = v;
  }
  return body;
}
