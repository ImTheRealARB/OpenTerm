/**
 * OpenTerm Script in the indicator Web Worker (Phase 25 wave 2). Pure like `chart/libraryWorker.ts`: no DOM, no worker globals,
 * so vitest runs `handleScript` directly. The wiring is a few lines in `chart/indicators.worker.ts` (`routeScript`).
 *
 * Messages (main thread -> worker -> main thread):
 *   "script"       compile + run one script over the chart's bars. Reply `status`:
 *                    "ok"     result (plots, drawings, alerts, conditions, error?) + the script's title / overlay / inputs
 *                    "needs"  the script uses `request(SYMBOL, TF, ...)` of ANOTHER symbol: fetch these, send the same message
 *                             again with `requests`. (The chart's own symbol and longer timeframes of it are built here.)
 *                    "error"  compile error (with line:col), or a bad input value
 *   "script-tick"  a live tick: the newest bar changed (`isNew` = a new bar opened). Replies with the newest bar's values only.
 *   "script-drop"  forget every run whose key starts with `prefix` (a chart went away).
 * The worker keeps one RunState per `key` (chart id + script name), so a tick re-runs only the newest bar.
 */
import { compile } from "./index";
import type { Bar, BarCols, InputDef, ScriptError, ScriptResult, ScriptTick } from "./index";
import type { RunState } from "./runtime";
import { inputsFromRaw } from "./inputArgs";
import { normTimeframe, resample, tfSeconds, type TCols } from "./resample";

export interface ScriptReq {
  type: "script";
  id: number;
  /** Caller's key for this run (the chart + script name): ticks find the run by it. */
  key: string;
  name: string;
  source: string;
  /** Raw positional input values (`SCRIPT=NAME(14,70)`), "" = default. */
  rawInputs: string[];
  /** The chart's symbol (upper case): a `request` for it is answered from the chart's own bars. */
  symbol: string;
  /** The chart's timeframe in script spelling ("5m", "1D"); omitted when the script language has no word for it. */
  chartTf?: string;
  bars: TCols;
  /** Bars for `request(...)`, keyed "SYMBOL|TIMEFRAME" (the `needs` answer). */
  requests?: Record<string, BarCols>;
}

export interface ScriptInfo {
  title: string;
  overlay: boolean;
  inputs: InputDef[];
}

export type ScriptRes =
  | { type: "script"; id: number; key: string; status: "ok"; info: ScriptInfo; result: ScriptResult; ms: number }
  | { type: "script"; id: number; key: string; status: "needs"; info: ScriptInfo; needs: { symbol: string; timeframe: string }[] }
  | { type: "script"; id: number; key: string; status: "error"; stage: "compile" | "inputs"; errors: ScriptError[] };

export interface ScriptTickReq {
  type: "script-tick";
  id: number;
  key: string;
  bar: Bar;
  isNew: boolean;
}

export interface ScriptTickRes {
  type: "script-tick";
  id: number;
  key: string;
  /** null when this worker holds no run for the key (dropped, or the first run has not finished). */
  tick: ScriptTick | null;
}

export interface ScriptDropReq {
  type: "script-drop";
  prefix: string;
}

export type ScriptMsg = ScriptReq | ScriptTickReq | ScriptDropReq;
type Out = { msg: ScriptRes | ScriptTickRes; transfer: ArrayBuffer[] };

/** One RunState per key. Bounded: a chart holds at most a handful, and charts drop theirs when they close. */
const runs = new Map<string, RunState>();
const MAX_RUNS = 64;

export function isScriptMsg(m: unknown): m is ScriptMsg {
  const t = typeof m === "object" && m !== null ? (m as { type?: unknown }).type : undefined;
  return t === "script" || t === "script-tick" || t === "script-drop";
}

/** Entry for `indicators.worker.ts`: answers one message, or returns null when there is nothing to send back. */
export function routeScript(m: ScriptMsg): Out | null {
  if (m.type === "script") return handleScript(m);
  if (m.type === "script-tick") return handleScriptTick(m);
  dropScripts(m.prefix);
  return null;
}

export function dropScripts(prefix: string): void {
  for (const k of [...runs.keys()]) if (k.startsWith(prefix)) runs.delete(k);
}

/** Number of runs held (tests, and the leak check in the worker). */
export function runCount(): number {
  return runs.size;
}

function resultTransfer(r: ScriptResult): ArrayBuffer[] {
  const out: ArrayBuffer[] = [];
  for (const p of r.plots) if (p.values) out.push(p.values.buffer as ArrayBuffer);
  for (const c of r.conditions) out.push(c.values.buffer as ArrayBuffer);
  return out;
}

export function handleScript(req: ScriptReq): Out {
  const base = { type: "script" as const, id: req.id, key: req.key };
  const compiled = compile(req.source);
  if (!compiled.ok) return { msg: { ...base, status: "error", stage: "compile", errors: compiled.errors }, transfer: [] };
  const program = compiled.program;
  const info: ScriptInfo = { title: program.meta.title, overlay: program.meta.overlay, inputs: program.meta.inputs };

  const typed = inputsFromRaw(program.meta.inputs, req.rawInputs);
  if (typed.errors.length) {
    return { msg: { ...base, status: "error", stage: "inputs", errors: typed.errors.map((msg) => ({ msg, line: 0, col: 0 })) }, transfer: [] };
  }

  // Which other series does the script need? The chart's own symbol is answered here; other symbols come from the host.
  const chartTf = req.chartTf ?? "";
  const own = (tf: string): TCols => {
    const n = normTimeframe(tf) ?? tf;
    return n === "" || chartTf === "" || !(tfSeconds(n) > tfSeconds(chartTf)) ? req.bars : resample(req.bars, n);
  };
  const supplied: Record<string, BarCols> = { ...(req.requests ?? {}) };
  const needs: { symbol: string; timeframe: string }[] = [];
  for (const r of program.resolveRequests(typed.values)) {
    if (r.symbol === "") continue; // the chart's own series: the engine resamples it itself
    const k = `${r.symbol}|${r.timeframe}`;
    if (supplied[k]) continue;
    if (r.symbol.toUpperCase() === req.symbol.toUpperCase()) supplied[k] = own(r.timeframe);
    else needs.push(r);
  }
  if (needs.length) return { msg: { ...base, status: "needs", info, needs }, transfer: [] };

  const t0 = Date.now();
  const rs = program.run(req.bars, { inputs: typed.values, requests: supplied, chartTimeframe: req.chartTf });
  if (!runs.has(req.key) && runs.size >= MAX_RUNS) runs.delete(runs.keys().next().value as string);
  runs.set(req.key, rs);
  const result = rs.result();
  return { msg: { ...base, status: "ok", info, result, ms: Date.now() - t0 }, transfer: resultTransfer(result) };
}

export function handleScriptTick(req: ScriptTickReq): Out {
  const base = { type: "script-tick" as const, id: req.id, key: req.key };
  const rs = runs.get(req.key);
  if (!rs) return { msg: { ...base, tick: null }, transfer: [] };
  if (req.isNew) rs.append(req.bar);
  else rs.updateLast(req.bar);
  return { msg: { ...base, tick: rs.tick() }, transfer: [] };
}
