/**
 * Phase 15: command arguments of RISK, PORT OPT and PORT ATTR -> the string params of a quant job, and `quantBody`, which types them
 * for `POST /api/quant/{fn}`. Pure (no window), unit-tested. Anything not recognised is reported in `bad`, never guessed.
 */
import type { Parsed } from "./derivArgs";

export type { Parsed };

const NAME = /^[A-Za-z0-9_.-]{1,40}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const NUM = /^-?\d+(\.\d+)?$/;
const SYMBOL = /^[A-Za-z0-9^._-]{1,20}$/;

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

/** FACT: `<SYMBOL|PORTFOLIO> [RANGE=3y]`. One word only; anything else is reported. */
export function factArgs(args: string[]): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const i = raw.indexOf("=");
    if (i < 0) {
      if (SYMBOL.test(raw) && !params.symbol) params.symbol = raw.toUpperCase();
      else bad.push(raw);
    } else if (raw.slice(0, i).toLowerCase() === "range" && raw.slice(i + 1)) params.range = raw.slice(i + 1).toLowerCase();
    else bad.push(raw);
  }
  return { params, bad };
}

const UNIVERSE_WORD = /^(TOP100|SYN|WL:[A-Za-z0-9_.-]{1,40}|LIST:[A-Za-z0-9^._,-]{1,400})$/i;
const NUMLIST = /^-?\d+(\.\d+)?(,-?\d+(\.\d+)?)*$/;

/** ALPHA: `[UNIVERSE=TOP100|SYN|WL:<NAME>|LIST:A,B,C] [RANGE=2y] [FAMILY=..] [H=1,5,10,20]`; a bare universe word is also accepted. */
export function alphaArgs(args: string[]): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const i = raw.indexOf("=");
    const k = i < 0 ? "universe" : raw.slice(0, i).toLowerCase();
    const v = i < 0 ? raw : raw.slice(i + 1);
    if (!v) bad.push(raw);
    else if (k === "universe" && UNIVERSE_WORD.test(v) && !params.universe) params.universe = v.toUpperCase();
    else if (k === "range" && i >= 0) params.range = v.toLowerCase();
    else if (k === "family" && i >= 0 && NAME.test(v)) params.family = v;
    else if (k === "h" && i >= 0 && NUMLIST.test(v)) params.h = v;
    else bad.push(raw);
  }
  return { params, bad };
}

/** CORR REGIME: `[WL:<NAME>|LIST:A,B,C] [WIN=60] [EDGE=0.5]`. */
export function regimeArgs(args: string[]): Parsed {
  const params: Record<string, string> = {};
  const bad: string[] = [];
  for (const raw of args) {
    const i = raw.indexOf("=");
    const k = i < 0 ? "list" : raw.slice(0, i).toLowerCase();
    const v = i < 0 ? raw : raw.slice(i + 1);
    if (!v) bad.push(raw);
    else if (k === "list" && /^(WL|LIST):/i.test(v) && UNIVERSE_WORD.test(v) && !params.list) params.list = v.toUpperCase();
    else if ((k === "win" || k === "edge") && i >= 0 && NUM.test(v)) params[k] = v;
    else bad.push(raw);
  }
  return { params, bad };
}

export const QL_CALCS = ["GARCH", "OU", "COINT", "HEDGE", "COPULA", "ROLL", "AMIHUD", "KYLE", "VPIN", "EVENT", "DSR", "ADF", "HVAR"];

export interface QlParsed {
  params: Record<string, string | string[]>;
  bad: string[];
}

/** QL: `<CALCULATOR> [SYMBOL ...] [KEY=VALUE ...]`. Symbols (upper-cased) become a list; keys are lower-cased, values kept as typed. */
export function qlArgs(args: string[]): QlParsed {
  const params: Record<string, string | string[]> = {};
  const bad: string[] = [];
  if (!args.length) return { params, bad: ["CALCULATOR"] };
  const calc = args[0].toUpperCase();
  if (!QL_CALCS.includes(calc)) return { params, bad: [calc] };
  params.calc = calc;
  const symbols: string[] = [];
  for (const raw of args.slice(1)) {
    const i = raw.indexOf("=");
    if (i < 0) {
      if (SYMBOL.test(raw)) symbols.push(raw.toUpperCase());
      else bad.push(raw);
      continue;
    }
    const k = raw.slice(0, i).toLowerCase();
    const v = raw.slice(i + 1);
    if (!v || !/^[a-z_]{1,20}$/.test(k) || k === "calc" || k === "symbols") bad.push(raw);
    else params[k] = v;
  }
  if (symbols.length) params.symbols = symbols;
  return { params, bad };
}

/** Params that are numbers in the job body; `h` is a list of numbers. Other values (symbols, calc, universe) stay strings. */
const NUMERIC = new Set(["conf", "hor", "cap", "lookback", "rf", "tc", "sr", "n", "t", "win", "edge", "skew", "kurt", "trial_sr_std", "est", "buckets"]);
/** QL keeps `win` (EVENT: "-5,5") and `h` (one number) as the user typed them / plain numbers. */
const QL_STRING = new Set(["win"]);
const LISTS = new Set(["h"]);

/** The JSON body of `POST /api/quant/{fn}`: numeric params as numbers, horizon lists as arrays, symbols as given. */
export function quantBody(fn: string, params: Record<string, string | string[]>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) body[k] = v;
    else if (fn === "ql" && QL_STRING.has(k)) body[k] = v;
    else if (LISTS.has(k) && fn !== "ql") body[k] = v.split(",").map((x) => (NUM.test(x.trim()) ? Number(x) : x.trim()));
    else if ((NUMERIC.has(k) || (fn === "ql" && k === "h")) && NUM.test(v)) body[k] = Number(v);
    else body[k] = v;
  }
  return body;
}
