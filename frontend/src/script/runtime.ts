/**
 * OpenTerm Script runtime: the bar loop, the result, and live updates (spec section 2).
 *
 *   Program    a compiled script (the checked syntax tree + meta). It can be run many times.
 *   RunState   ONE run over a set of bars. It owns the Ctx, holds the results and can be updated bar by bar:
 *                updateLast(bar)  the newest bar's prices changed (a live tick): re-run only that bar
 *                append(bar)      a new bar opened: run it
 *
 * How a live tick works: before the newest bar runs, we SNAPSHOT everything a script can change (variables, history,
 * arrays, maps, drawings, the memory of every `ta.*` call site). `updateLast` restores that snapshot and re-runs just the
 * newest bar with its new prices. `append` first takes a fresh snapshot (the state after the old newest bar = the state
 * at the start of the new bar).
 *
 * Scripts that use `request(...)` or `lib.*` re-do part of their work on a tick (the other series / whole-series
 * indicator are recomputed): see the notes in docs/review/phase25_A.md.
 */
import type { Ast, ScriptError } from "./ast";
import type { Checked, ProgramMeta } from "./checker";
import { Builder, resolveInputs } from "./compile";
import { Ctx, type OutRec } from "./ctx";
import { LIMITS } from "./names";
import { bucketEnd, normTimeframe, resample, tfSeconds, type TCols } from "./resample";
import { restoreState, snapState } from "./ta";
import { ScriptRuntimeError, cloneValue, type BoxH, type LabelH, type LineH, type TableH } from "./values";
import { findIndicator, resolveParams } from "../chart/library/catalog";
import type { Cols } from "../chart/library/types";

// ---------------------------------------------------------------- public types

/** Bars as columns. `t` = bar open time, epoch SECONDS. (Plain arrays are accepted too: they are copied.) */
export interface BarCols {
  o: ArrayLike<number>;
  h: ArrayLike<number>;
  l: ArrayLike<number>;
  c: ArrayLike<number>;
  v: ArrayLike<number>;
  t?: ArrayLike<number>;
}

export interface Bar {
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  /** Bar open time (epoch seconds). Needed by `append`; `updateLast` keeps the old time when it is missing. */
  t?: number;
}

export interface RunOpts {
  /** Setting values by input title (see ProgramMeta.inputs). */
  inputs?: Record<string, unknown>;
  /** Other series for `request(...)`, keyed "SYMBOL|TIMEFRAME" (symbol "" = the chart's own; timeframe in normal spelling, e.g. "1D"). */
  requests?: Record<string, BarCols>;
  /** The chart's timeframe ("5m", "1D" ...), used to check that a request is not shorter than the chart. */
  chartTimeframe?: string;
}

export interface PlotOut {
  kind: "plot" | "hline" | "fill" | "shape" | "bgcolor";
  title: string;
  /** plot style / shape style / hline line style */
  style: string;
  /** One number per bar (na = NaN): plot value; shape: 1 (or the price for `location="absolute"`); bgcolor: 1. */
  values?: Float64Array;
  /** The colour (when it never changes, or the colour of the first call). */
  color?: string;
  /** One colour per bar, ONLY when the colour changed during the run (null = the default colour). */
  colors?: (string | null)[];
  price?: number;
  /** fill: the two plots (indexes into `plots`). */
  a?: number;
  b?: number;
  location?: string;
  text?: string;
  /** plot only: line width in pixels */
  linewidth?: number;
}

export interface LabelOut {
  x: number;
  y: number;
  text: string;
  color: string | null;
  style: string;
  textcolor: string | null;
}
export interface LineOut {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string | null;
  width: number;
}
export interface BoxOut {
  left: number;
  top: number;
  right: number;
  bottom: number;
  color: string | null;
  bgcolor: string | null;
}
export interface TableOut {
  position: string;
  columns: number;
  rows: number;
  cells: { column: number; row: number; text: string; color: string | null; bgcolor: string | null }[];
}
export interface DrawingsOut {
  labels: LabelOut[];
  lines: LineOut[];
  boxes: BoxOut[];
  tables: TableOut[];
}

export interface ScriptResult {
  plots: PlotOut[];
  drawings: DrawingsOut;
  /** Newest 500 alerts: `alert(...)` calls with the bar they fired on. */
  alerts: { bar: number; message: string }[];
  conditions: { title: string; message: string; values: Uint8Array }[];
  error?: ScriptError;
  stats: { steps: number; ms: number };
}

/** What a live tick changes: the newest bar's values only (spec section 2; the worker sends this on `script-tick`). */
export interface ScriptTick {
  /** Index of the newest bar and the number of bars. */
  bar: number;
  n: number;
  /** Per plot (same order as `ScriptResult.plots`): the value on the newest bar and its colour (undefined = unchanged default). */
  plots: { v: number; color?: string | null }[];
  drawings: DrawingsOut;
  /** Alerts that fired on the newest bar. */
  alerts: { bar: number; message: string }[];
  /** Per condition: 1 if it was true on the newest bar. */
  conditions: number[];
  error?: ScriptError;
}

// ---------------------------------------------------------------- program

export class Program {
  constructor(
    public meta: ProgramMeta,
    readonly ast: Ast,
    readonly checked: Checked,
  ) {}

  /** Compile-and-run over `bars`. */
  run(bars: BarCols, opts: RunOpts = {}): RunState {
    const rs = new RunState(this, bars, opts);
    rs.exec();
    return rs;
  }

  /**
   * The `request` series this script needs, with symbol / timeframe settled by the given inputs (an input may choose the
   * symbol). The host fetches these before `run`. Falls back to the defaults in `meta.requests` if the inputs are bad.
   */
  resolveRequests(inputs?: Record<string, unknown>): { symbol: string; timeframe: string }[] {
    const empty: BarCols = { o: [], h: [], l: [], c: [], v: [], t: [] };
    const rs = new RunState(this, empty, { inputs });
    if (rs.error) return this.meta.requests;
    const seen = new Set<string>();
    const out: { symbol: string; timeframe: string }[] = [];
    for (const r of rs.ctx.requests) {
      if (!seen.has(r.key)) {
        seen.add(r.key);
        out.push({ symbol: r.symbol, timeframe: r.timeframe });
      }
    }
    return out;
  }
}

// ---------------------------------------------------------------- helpers

function medianDt(t: Float64Array, n: number, fallback: number): number {
  if (n < 2) return fallback;
  const d: number[] = [];
  for (let i = 1; i < n; i++) {
    const x = t[i] - t[i - 1];
    if (x === x && x > 0) d.push(x);
  }
  if (d.length === 0) return fallback;
  d.sort((a, b) => a - b);
  return d[Math.floor(d.length / 2)];
}

/** Compute every `lib.*` call site once over all bars of `ctx`. */
function hoistLibs(ctx: Ctx): void {
  if (ctx.libs.length === 0) return;
  const n = ctx.n;
  const cols: Cols = { o: ctx.o.subarray(0, n), h: ctx.h.subarray(0, n), l: ctx.l.subarray(0, n), c: ctx.c.subarray(0, n), v: ctx.v.subarray(0, n), t: ctx.t.subarray(0, n) };
  const cache = new Map<string, Float64Array[]>();
  for (const site of ctx.libs) {
    const key = `${site.id}:${site.params.join(",")}`;
    let outs = cache.get(key);
    if (!outs) {
      const def = findIndicator(site.id);
      if (!def) throw new ScriptRuntimeError(`UNKNOWN INDICATOR LIB.${site.id}`);
      outs = n === 0 ? def.outputs.map(() => new Float64Array(0)) : def.fn(cols, resolveParams(def, site.params));
      cache.set(key, outs);
    }
    site.outs = outs;
  }
}

function toError(e: unknown, bar: number): ScriptError {
  if (e instanceof ScriptRuntimeError) return { msg: e.message, line: e.pos?.line ?? 0, col: e.pos?.col ?? 0, bar };
  if (e instanceof RangeError) return { msg: "SCRIPT TOO DEEPLY NESTED", line: 0, col: 0, bar };
  return { msg: `INTERNAL ERROR: ${e instanceof Error ? e.message : String(e)}`, line: 0, col: 0, bar };
}

interface Snap {
  slots: unknown[];
  hist: (unknown[] | null)[];
  labels: unknown[];
  lines: unknown[];
  boxes: unknown[];
  tables: unknown[];
  states: unknown[];
  memArr: number;
  memMap: number;
  steps: number;
}

const now = (): number => (typeof performance !== "undefined" ? performance.now() : Date.now());

// ---------------------------------------------------------------- one run

export class RunState {
  ctx: Ctx;
  error: ScriptError | null = null;
  private main: (() => number) | null = null;
  private snap: Snap | null = null;
  private ms = 0;
  private bars!: BarCols;

  constructor(
    private program: Program,
    bars: BarCols,
    private opts: RunOpts,
  ) {
    this.ctx = new Ctx(1);
    this.init(bars);
  }

  /** (Re)build everything for a set of bars: copy the bars, compile the closures, prepare libs and requests. */
  private init(bars: BarCols): void {
    this.bars = bars;
    const n = bars.c.length;
    const ctx = new Ctx(n + Math.max(64, n >> 3));
    this.ctx = ctx;
    ctx.o.set(bars.o);
    ctx.h.set(bars.h);
    ctx.l.set(bars.l);
    ctx.c.set(bars.c);
    ctx.v.set(bars.v);
    if (bars.t) ctx.t.set(bars.t);
    ctx.n = n;
    this.error = null;
    this.snap = null;
    this.ms = 0;
    try {
      const inputs = resolveInputs(this.program.meta.inputs, this.opts.inputs);
      this.main = new Builder(ctx, this.program.checked, inputs).program(this.program.ast);
      ctx.initHist();
      hoistLibs(ctx);
      this.setupRequests();
    } catch (e) {
      this.main = null;
      this.error = toError(e, 0);
    }
  }

  // ---------------------------------------------------------------- requests

  private setupRequests(): void {
    const ctx = this.ctx;
    const chartTf = this.opts.chartTimeframe ? (normTimeframe(this.opts.chartTimeframe) ?? "") : "";
    for (const site of ctx.requests) {
      const fail = (msg: string) => {
        site.err = msg;
      };
      // 1. the other series
      let other: TCols | null = null;
      const given = this.opts.requests?.[site.key];
      const chartHasT = this.bars.t !== undefined;
      if (site.timeframe !== "" && chartTf !== "" && tfSeconds(site.timeframe) < tfSeconds(chartTf)) {
        fail(`REQUEST TIMEFRAME ${site.timeframe.toUpperCase()} IS SHORTER THAN THE CHART`);
        continue;
      }
      if (given) {
        if (!given.t) {
          fail(`REQUEST DATA FOR ${site.key.toUpperCase()} HAS NO BAR TIMES`);
          continue;
        }
        other = { o: Float64Array.from(given.o), h: Float64Array.from(given.h), l: Float64Array.from(given.l), c: Float64Array.from(given.c), v: Float64Array.from(given.v), t: Float64Array.from(given.t) };
      } else if (site.symbol === "") {
        if (!chartHasT) {
          fail("REQUEST NEEDS BAR TIMES");
          continue;
        }
        const n = ctx.n;
        const own: TCols = { o: ctx.o.subarray(0, n), h: ctx.h.subarray(0, n), l: ctx.l.subarray(0, n), c: ctx.c.subarray(0, n), v: ctx.v.subarray(0, n), t: ctx.t.subarray(0, n) };
        other = site.timeframe === "" || site.timeframe === chartTf ? own : resample(own, site.timeframe);
      } else {
        fail(`NO DATA FOR REQUEST ${site.key.toUpperCase()}`);
        continue;
      }
      // 2. run the expression over the other series
      const sub = site.sub;
      const m = other.t.length;
      sub.o = other.o;
      sub.h = other.h;
      sub.l = other.l;
      sub.c = other.c;
      sub.v = other.v;
      sub.t = other.t;
      sub.n = m;
      sub.cap = m;
      try {
        hoistLibs(sub);
        site.vals = new Float64Array(m).fill(NaN);
        for (let b = 0; b < m; b++) {
          sub.bar = b;
          const v = site.ev();
          if (typeof v !== "number") throw new ScriptRuntimeError("REQUEST MUST GIVE A NUMBER");
          site.vals[b] = v;
        }
      } catch (e) {
        fail(e instanceof ScriptRuntimeError ? e.message : String(e));
        continue;
      }
      // 3. for each chart bar, the newest other bar that had CLOSED by the close of the chart bar (spec 1.5: no look-ahead)
      const n = ctx.n;
      const t = ctx.t;
      const fallback = tfSeconds(chartTf || site.timeframe) || 86400;
      const dtLast = medianDt(t, n, fallback);
      const otherDt = medianDt(other.t, m, fallback);
      const endOf = (k: number): number => (k + 1 < m ? other.t[k + 1] : site.timeframe === "" ? other.t[k] + otherDt : bucketEnd(other.t[k], site.timeframe));
      site.map = new Int32Array(n).fill(-1);
      let k = -1;
      for (let i = 0; i < n; i++) {
        const limit = t[i] + (i + 1 < n ? t[i + 1] - t[i] : dtLast);
        while (k + 1 < m && endOf(k + 1) <= limit) k++;
        site.map[i] = k;
      }
    }
  }

  // ---------------------------------------------------------------- running bars

  /** Run every bar. Takes the snapshot before the newest bar. */
  exec(): void {
    const t0 = now();
    const n = this.ctx.n;
    if (this.main) {
      for (let i = 0; i < n; i++) {
        if (i === n - 1) this.snap = this.takeSnap();
        if (!this.runBar(i)) break;
      }
      if (n === 0) this.snap = this.takeSnap();
    }
    this.ms += now() - t0;
  }

  private runBar(bar: number): boolean {
    const ctx = this.ctx;
    const main = this.main as () => number;
    ctx.bar = bar;
    ctx.sb = 0;
    ctx.barCap = Math.min(LIMITS.stepsPerBar, LIMITS.stepsPerRun - ctx.steps);
    const S = ctx.slots;
    const resets = ctx.resets;
    for (let i = 0; i < resets.length; i++) S[resets[i]] = NaN;
    try {
      main();
    } catch (e) {
      this.error = toError(e, bar);
      this.clearBar(bar);
      return false;
    }
    ctx.steps += ctx.sb;
    // keep this bar's value of every variable that is read as `x[n]`
    const hist = ctx.hist;
    for (let s = 0; s < hist.length; s++) {
      const H = hist[s];
      if (H) H[bar % H.length] = S[s];
    }
    return true;
  }

  /** Forget what the given bar drew (used when a bar is re-run or failed half way). */
  private clearBar(bar: number): void {
    const ctx = this.ctx;
    for (const o of ctx.outputs) {
      if (o.values) o.values[bar] = NaN;
      if (o.colors) o.colors[bar] = undefined;
    }
    for (const c of ctx.conditions) c.values[bar] = 0;
    while (ctx.alerts.length > 0 && ctx.alerts[ctx.alerts.length - 1].bar >= bar) ctx.alerts.pop();
  }

  // ---------------------------------------------------------------- snapshot

  private takeSnap(): Snap {
    const ctx = this.ctx;
    const seen = new Map<object, object>();
    const cl = (v: unknown) => cloneValue(v, seen);
    return {
      slots: ctx.slots.map(cl),
      hist: ctx.hist.map((h) => (h ? h.map(cl) : null)),
      labels: ctx.labels.map(cl),
      lines: ctx.lines.map(cl),
      boxes: ctx.boxes.map(cl),
      tables: ctx.tables.map(cl),
      states: ctx.states.map((s) => snapState(s)),
      memArr: ctx.memArr,
      memMap: ctx.memMap,
      steps: ctx.steps,
    };
  }

  private restoreSnap(snap: Snap): void {
    const ctx = this.ctx;
    const seen = new Map<object, object>();
    const cl = (v: unknown) => cloneValue(v, seen);
    for (let i = 0; i < snap.slots.length; i++) ctx.slots[i] = cl(snap.slots[i]);
    for (let i = 0; i < snap.hist.length; i++) {
      const H = ctx.hist[i];
      const sh = snap.hist[i];
      if (H && sh) for (let j = 0; j < sh.length; j++) H[j] = cl(sh[j]);
    }
    ctx.labels = snap.labels.map(cl) as LabelH[];
    ctx.lines = snap.lines.map(cl) as LineH[];
    ctx.boxes = snap.boxes.map(cl) as BoxH[];
    ctx.tables = snap.tables.map(cl) as TableH[];
    for (let i = 0; i < ctx.states.length; i++) restoreState(ctx.states[i], snap.states[i]);
    ctx.memArr = snap.memArr;
    ctx.memMap = snap.memMap;
    ctx.steps = snap.steps;
  }

  // ---------------------------------------------------------------- live updates

  /** The newest bar's prices changed: put the state back to the start of that bar and run it again. */
  updateLast(bar: Bar): void {
    const ctx = this.ctx;
    const n = ctx.n;
    if (n === 0) return;
    const last = n - 1;
    this.writeBar(last, bar, false);
    if (ctx.requests.length > 0) return this.rebuild();
    if (!this.snap || !this.main || (this.error && (this.error.bar ?? 0) < last)) return;
    const t0 = now();
    this.error = null;
    this.restoreSnap(this.snap);
    this.clearBar(last);
    try {
      hoistLibs(ctx);
    } catch (e) {
      this.error = toError(e, last);
      return;
    }
    this.runBar(last);
    this.ms += now() - t0;
  }

  /** A new bar opened: the old newest bar is final; run the new one. */
  append(bar: Bar): void {
    const ctx = this.ctx;
    const n = ctx.n;
    if (n === ctx.cap) ctx.grow(Math.max(n + 64, n + (n >> 1)));
    this.writeBar(n, bar, true);
    ctx.n = n + 1;
    // the request series / run state of scripts with requests are rebuilt from the bars we hold
    if (ctx.requests.length > 0) return this.rebuild();
    if (!this.main || (this.error && (this.error.bar ?? 0) < n)) return;
    const t0 = now();
    this.snap = this.takeSnap();
    this.error = null;
    try {
      hoistLibs(ctx);
    } catch (e) {
      this.error = toError(e, n);
      return;
    }
    this.runBar(n);
    this.ms += now() - t0;
  }

  private writeBar(i: number, bar: Bar, isNew: boolean): void {
    const ctx = this.ctx;
    ctx.o[i] = bar.o;
    ctx.h[i] = bar.h;
    ctx.l[i] = bar.l;
    ctx.c[i] = bar.c;
    ctx.v[i] = bar.v;
    if (bar.t !== undefined) ctx.t[i] = bar.t;
    else if (isNew) ctx.t[i] = NaN;
  }

  /** Re-run the whole script from the bars the context now holds (scripts with `request`). */
  private rebuild(): void {
    const ctx = this.ctx;
    const n = ctx.n;
    const bars: BarCols = { o: ctx.o.slice(0, n), h: ctx.h.slice(0, n), l: ctx.l.slice(0, n), c: ctx.c.slice(0, n), v: ctx.v.slice(0, n), t: ctx.t.slice(0, n) };
    this.init(bars);
    this.exec();
  }

  // ---------------------------------------------------------------- results

  /** The finished outputs as plain data (typed arrays are copies: safe to transfer). */
  result(): ScriptResult {
    const ctx = this.ctx;
    const n = ctx.n;
    const plots = ctx.outputs.map((o) => this.plotOut(o, n));
    const res: ScriptResult = {
      plots,
      drawings: this.drawings(),
      alerts: ctx.alerts.slice(-LIMITS.alerts),
      conditions: ctx.conditions.map((c) => ({ title: c.title, message: c.message, values: c.values.slice(0, n) })),
      stats: { steps: ctx.steps, ms: this.ms },
    };
    if (this.error) res.error = this.error;
    return res;
  }

  private plotOut(o: OutRec, n: number): PlotOut {
    const p: PlotOut = { kind: o.kind, title: o.title, style: o.style };
    if (o.values) p.values = o.values.slice(0, n);
    if (o.linewidth !== undefined) p.linewidth = o.linewidth;
    if (o.color !== null) p.color = o.color;
    if (o.colors) {
      const arr: (string | null)[] = new Array(n);
      for (let i = 0; i < n; i++) {
        const c = o.colors[i];
        arr[i] = c === undefined ? o.color : c;
      }
      p.colors = arr;
    }
    if (o.kind === "hline") p.price = o.price;
    if (o.kind === "fill") {
      p.a = o.a;
      p.b = o.b;
    }
    if (o.kind === "shape") {
      p.location = o.location;
      p.text = o.text;
    }
    return p;
  }

  private drawings(): DrawingsOut {
    const ctx = this.ctx;
    return {
      labels: ctx.labels.map((l) => ({ x: l.x, y: l.y, text: l.text, color: l.color, style: l.style, textcolor: l.textcolor })),
      lines: ctx.lines.map((l) => ({ x1: l.x1, y1: l.y1, x2: l.x2, y2: l.y2, color: l.color, width: l.width })),
      boxes: ctx.boxes.map((b) => ({ left: b.left, top: b.top, right: b.right, bottom: b.bottom, color: b.color, bgcolor: b.bgcolor })),
      tables: ctx.tables.map((t) => ({ position: t.position, columns: t.columns, rows: t.rows, cells: [...t.cells.values()].map((c) => ({ ...c })) })),
    };
  }

  /** Only the newest bar's values (cheap: the worker sends this on every live tick). */
  tick(): ScriptTick {
    const ctx = this.ctx;
    const n = ctx.n;
    const last = n - 1;
    const tick: ScriptTick = {
      bar: last,
      n,
      plots: ctx.outputs.map((o) => {
        const v = o.values && last >= 0 ? o.values[last] : NaN;
        if (o.colors && last >= 0) {
          const c = o.colors[last];
          return { v, color: c === undefined ? o.color : c };
        }
        return { v };
      }),
      drawings: this.drawings(),
      alerts: ctx.alerts.filter((a) => a.bar === last),
      conditions: ctx.conditions.map((c) => (last >= 0 ? c.values[last] : 0)),
    };
    if (this.error) tick.error = this.error;
    return tick;
  }
}
