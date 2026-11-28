/**
 * The "run context": everything one script run keeps in memory. compile.ts builds closures that read and write a Ctx;
 * runtime.ts owns the bar loop around it.
 *
 * Why one object: the compiled closures capture the Ctx once, so a variable read is `ctx.slots[3]` and a bar read is
 * `ctx.c[ctx.bar]`. Nothing is looked up by name while the script runs.
 */
import type { BuiltinCtx } from "./builtins";
import type { TaEnv } from "./ta";
import { LIMITS } from "./names";
import type { BoxH, LabelH, LineH, TableH } from "./values";

export interface Alert {
  bar: number;
  message: string;
}

/** One plot / hline / fill / shape / bgcolor of the script, collected bar by bar. */
export interface OutRec {
  kind: "plot" | "hline" | "fill" | "shape" | "bgcolor";
  title: string;
  /** plot style, shape style, or the hline's line style */
  style: string;
  location?: string;
  text?: string;
  /** plot only: line width in pixels (a constant, default 1) */
  linewidth?: number;
  /** One number per bar (plot value, shape: 1 or the price, bgcolor: 1) or null for kinds with no per-bar number. NaN = nothing. */
  values: Float64Array | null;
  price?: number;
  /** fill: the two plots (indexes into the outputs). */
  a: number;
  b: number;
  /** The colour of the first draw call; `colors` only exists when a later call used a different one. */
  color: string | null;
  colorSet: boolean;
  colors: (string | null | undefined)[] | null;
}

export interface CondRec {
  title: string;
  message: string;
  values: Uint8Array;
}

/** A `request(...)` call site (see compile.ts). */
export interface ReqSite {
  key: string;
  symbol: string;
  timeframe: string;
  /** The context the request expression runs in (its bars are the OTHER series). */
  sub: Ctx;
  ev: () => unknown;
  /** The expression's value on each bar of the other series. */
  vals: Float64Array;
  /** For each chart bar: the index of the newest CLOSED other bar, or -1. */
  map: Int32Array;
  /** Set at run start when the data is missing: reading the request then fails with this text. */
  err: string;
}

/** A `lib.<ID>(...)` call site: the indicator is computed once over all bars, then read per bar. */
export interface LibSite {
  id: string;
  params: number[];
  /** One array per output, each as long as the bars. Filled by `hoistLibs`. */
  outs: Float64Array[];
}

export class Ctx implements BuiltinCtx, TaEnv {
  n = 0;
  cap: number;
  o: Float64Array;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
  t: Float64Array;
  /** The bar being run. */
  bar = 0;

  /** Variable values by slot. */
  slots: unknown[] = [];
  /** Slot -> ring of past values (only for variables read with `x[n]`); null for the others. */
  hist: (unknown[] | null)[] = [];
  /** Slot -> the ring length wanted (0 = none). Set while compiling; the rings are made at run start. */
  histCap: number[] = [];
  /** Slots that are reset to na at the start of every bar (everything except `var`). */
  resets: number[] = [];
  /** Objects with per-call-site memory (ta states, `var` flags ...): copied for live ticks. */
  states: object[] = [];

  /** Statements run on this bar / the most a bar may run. */
  sb = 0;
  barCap: number = LIMITS.stepsPerBar;
  steps = 0;

  memArr = 0;
  memMap = 0;
  maxLabels: number = LIMITS.drawingsPerKind;
  labels: LabelH[] = [];
  lines: LineH[] = [];
  boxes: BoxH[] = [];
  tables: TableH[] = [];
  alerts: Alert[] = [];

  outputs: OutRec[] = [];
  conditions: CondRec[] = [];
  requests: ReqSite[] = [];
  libs: LibSite[] = [];

  constructor(cap: number) {
    this.cap = cap;
    this.o = new Float64Array(cap);
    this.h = new Float64Array(cap);
    this.l = new Float64Array(cap);
    this.c = new Float64Array(cap);
    this.v = new Float64Array(cap);
    this.t = new Float64Array(cap).fill(NaN);
  }

  /** Make room for `cap` bars (bars, plot values, alert-condition values). */
  grow(cap: number): void {
    if (cap <= this.cap) return;
    const g = (a: Float64Array, fill: number) => {
      const b = new Float64Array(cap).fill(fill);
      b.set(a);
      return b;
    };
    this.o = g(this.o, 0);
    this.h = g(this.h, 0);
    this.l = g(this.l, 0);
    this.c = g(this.c, 0);
    this.v = g(this.v, 0);
    this.t = g(this.t, NaN);
    for (const o of this.outputs) if (o.values) o.values = g(o.values, NaN);
    for (const c of this.conditions) {
      const b = new Uint8Array(cap);
      b.set(c.values);
      c.values = b;
    }
    this.cap = cap;
  }

  /** Allocate the history rings the compiler asked for. */
  initHist(): void {
    for (let s = 0; s < this.histCap.length; s++) {
      const k = this.histCap[s];
      this.hist[s] = k > 0 ? new Array<unknown>(k).fill(NaN) : null;
    }
  }
}
