/**
 * OpenTerm Script `ta.*` functions, computed ONE BAR AT A TIME (spec 1.6 has the exact rules; both engines must match).
 *
 * Every call site in a script gets its own state object, made by `makeTa(name, ...)`. The state remembers what the call
 * site has seen so far (a ring of recent source values, a running EMA, the previous values for a crossover ...). On each
 * bar the compiler evaluates the arguments and calls `step(args)`. The state only moves when the call actually runs
 * (a call inside an `if` that did not run on a bar does not see that bar).
 *
 * "Ring" = a fixed-size array used as a loop: new values overwrite the oldest. It avoids allocating on every bar.
 *
 * A state object holds ONLY numbers, typed arrays, plain number arrays and nested state objects, so `snapState` /
 * `restoreState` can copy it generically (live ticks re-run the newest bar from a saved state: runtime.ts).
 */
import { LIMITS } from "./names";
import { ScriptRuntimeError } from "./values";

/** What the bar-based functions (tr, atr, vwma) read: the current bar index and the chart's columns. */
export interface TaEnv {
  bar: number;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
}

export interface TaFn {
  /** Evaluate for this bar. `a` = the argument values in the order of names.ts (defaults already filled in). */
  step(a: unknown[]): unknown;
}

/** Hints from the compiler: a length / occurrence that is a constant lets us size the ring exactly. */
export interface TaHint {
  len?: number;
  occ?: number;
}

// ---------------------------------------------------------------- argument checks

function num(v: unknown): number {
  if (typeof v !== "number") throw new ScriptRuntimeError(`EXPECTED A NUMBER, GOT ${typeof v === "string" ? "TEXT" : "ANOTHER KIND OF VALUE"}`);
  return v;
}

/** A length argument: NaN = na (the result is na), otherwise a whole number of at least 1. */
function lenOf(v: unknown, cap?: number): number {
  const n = num(v);
  if (n !== n) return NaN;
  if (n < 1 || n !== Math.floor(n)) throw new ScriptRuntimeError("LENGTH MUST BE A WHOLE NUMBER OF AT LEAST 1");
  if (n > LIMITS.lookback || (cap !== undefined && n >= cap)) throw new ScriptRuntimeError(`LENGTH TOO LARGE (MAX ${LIMITS.lookback})`);
  return n;
}

// ---------------------------------------------------------------- the building blocks

/** The last `cap` values this call site has seen. */
class Win {
  buf: Float64Array;
  /** Where the next value goes. */
  pos = 0;
  /** How many values were pushed in total (not capped). */
  seen = 0;
  constructor(public cap: number) {
    this.buf = new Float64Array(cap);
  }
  push(x: number): void {
    this.buf[this.pos] = x;
    if (++this.pos === this.cap) this.pos = 0;
    this.seen++;
  }
  /** The value k pushes ago (0 = newest). The caller makes sure k < min(seen, cap). */
  at(k: number): number {
    let i = this.pos - 1 - k;
    if (i < 0) i += this.cap;
    return this.buf[i];
  }
  /** Index of the oldest of the last n values. */
  start(n: number): number {
    let i = this.pos - n;
    if (i < 0) i += this.cap;
    return i;
  }
}

/** EMA (alpha 2/(n+1)) or Wilder's RMA (alpha 1/n). Seed = mean of the first n non-na values. A na input is skipped. */
class Ema {
  cnt = 0;
  sum = 0;
  prev = NaN;
  seeded = 0;
  constructor(private wilder: number) {}
  next(x: number, n: number): number {
    if (x !== x || n !== n) return NaN;
    if (this.seeded === 0) {
      this.sum += x;
      this.cnt++;
      if (this.cnt < n) return NaN;
      this.prev = this.sum / this.cnt;
      this.seeded = 1;
      return this.prev;
    }
    const alpha = this.wilder === 1 ? 1 / n : 2 / (n + 1);
    this.prev = this.prev + alpha * (x - this.prev);
    return this.prev;
  }
}

const winCap = (hint: TaHint, extra = 0) => (hint.len !== undefined && hint.len >= 1 ? Math.floor(hint.len) + extra + 1 : LIMITS.lookback + extra + 1);

// ---------------------------------------------------------------- window functions

type WinKind = "sma" | "stdev" | "variance" | "highest" | "lowest" | "wma" | "linreg" | "vwma";

class WinTa implements TaFn {
  w: Win;
  /** vwma only: the volume window (the first one holds src * volume). */
  w2: Win | null;
  constructor(
    private kind: WinKind,
    private env: TaEnv,
    hint: TaHint,
  ) {
    this.w = new Win(winCap(hint));
    this.w2 = kind === "vwma" ? new Win(winCap(hint)) : null;
  }
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const n = lenOf(a[1], this.w.cap);
    const w = this.w;
    if (this.kind === "vwma") {
      const vol = this.env.v[this.env.bar];
      w.push(x * vol);
      (this.w2 as Win).push(vol);
    } else w.push(x);
    if (n !== n || w.seen < n) return NaN;
    const buf = w.buf;
    const cap = w.cap;
    let i = w.start(n);
    switch (this.kind) {
      case "sma": {
        let s = 0;
        for (let j = 0; j < n; j++) {
          s += buf[i];
          if (++i === cap) i = 0;
        }
        return s / n;
      }
      case "variance":
      case "stdev": {
        let s = 0;
        const i0 = i;
        for (let j = 0; j < n; j++) {
          s += buf[i];
          if (++i === cap) i = 0;
        }
        const mean = s / n;
        let ss = 0;
        i = i0;
        for (let j = 0; j < n; j++) {
          const d = buf[i] - mean;
          ss += d * d;
          if (++i === cap) i = 0;
        }
        const variance = ss / n;
        return this.kind === "variance" ? variance : Math.sqrt(variance);
      }
      case "highest": {
        let m = -Infinity;
        for (let j = 0; j < n; j++) {
          const v = buf[i];
          if (v !== v) return NaN;
          if (v > m) m = v;
          if (++i === cap) i = 0;
        }
        return m;
      }
      case "lowest": {
        let m = Infinity;
        for (let j = 0; j < n; j++) {
          const v = buf[i];
          if (v !== v) return NaN;
          if (v < m) m = v;
          if (++i === cap) i = 0;
        }
        return m;
      }
      case "wma": {
        let s = 0;
        for (let j = 0; j < n; j++) {
          s += buf[i] * (j + 1);
          if (++i === cap) i = 0;
        }
        return s / ((n * (n + 1)) / 2);
      }
      case "vwma": {
        const w2 = this.w2 as Win;
        let s1 = 0;
        let s2 = 0;
        let i2 = w2.start(n);
        for (let j = 0; j < n; j++) {
          s1 += buf[i];
          s2 += w2.buf[i2];
          if (++i === cap) i = 0;
          if (++i2 === cap) i2 = 0;
        }
        const den = s2 / n;
        return den === 0 ? NaN : s1 / n / den;
      }
      case "linreg": {
        const off = num(a[2]);
        if (off !== off) return NaN;
        let sy = 0;
        let sxy = 0;
        for (let j = 0; j < n; j++) {
          sy += buf[i];
          sxy += j * buf[i];
          if (++i === cap) i = 0;
        }
        const sx = (n * (n - 1)) / 2;
        const sxx = ((n - 1) * n * (2 * n - 1)) / 6;
        const den = n * sxx - sx * sx;
        const slope = den === 0 ? 0 : (n * sxy - sx * sy) / den;
        const intercept = (sy - slope * sx) / n;
        return intercept + slope * (n - 1 - off);
      }
    }
  }
}

// ---------------------------------------------------------------- smoothing

class EmaTa implements TaFn {
  e: Ema;
  constructor(wilder: number) {
    this.e = new Ema(wilder);
  }
  step(a: unknown[]): unknown {
    return this.e.next(num(a[0]), lenOf(a[1]));
  }
}

class RsiTa implements TaFn {
  up = new Ema(1);
  down = new Ema(1);
  prev = NaN;
  has = 0;
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const n = lenOf(a[1]);
    // change since the value this call site saw last time; the very first call has no previous value
    const d = this.has === 1 ? x - this.prev : NaN;
    this.prev = x;
    this.has = 1;
    const u = this.up.next(Math.max(d, 0), n);
    const dn = this.down.next(Math.max(-d, 0), n);
    if (u !== u || dn !== dn) return NaN;
    return dn === 0 ? 100 : u === 0 ? 0 : 100 - 100 / (1 + u / dn);
  }
}

function trueRange(env: TaEnv): number {
  const i = env.bar;
  const hl = env.h[i] - env.l[i];
  if (i === 0) return hl;
  const pc = env.c[i - 1];
  return Math.max(hl, Math.abs(env.h[i] - pc), Math.abs(env.l[i] - pc));
}

class TrTa implements TaFn {
  constructor(private env: TaEnv) {}
  step(): unknown {
    return trueRange(this.env);
  }
}

class AtrTa implements TaFn {
  r = new Ema(1);
  constructor(private env: TaEnv) {}
  step(a: unknown[]): unknown {
    return this.r.next(trueRange(this.env), lenOf(a[0]));
  }
}

// ---------------------------------------------------------------- change, momentum, rate of change

class ChangeTa implements TaFn {
  w: Win;
  constructor(
    private kind: "change" | "roc",
    hint: TaHint,
  ) {
    this.w = new Win(winCap(hint));
  }
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const n = lenOf(a[1], this.w.cap);
    this.w.push(x);
    if (n !== n || this.w.seen <= n) return NaN;
    const old = this.w.at(n);
    if (this.kind === "change") return x - old;
    return old === 0 ? NaN : (100 * (x - old)) / old;
  }
}

class CumTa implements TaFn {
  sum = 0;
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    if (x === x) this.sum += x;
    return this.sum;
  }
}

// ---------------------------------------------------------------- crossings and conditions

class CrossTa implements TaFn {
  prevA = NaN;
  prevB = NaN;
  has = 0;
  constructor(private kind: "over" | "under" | "either") {}
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const y = num(a[1]);
    let r = 0;
    if (this.has === 1) {
      const over = x > y && this.prevA <= this.prevB;
      const under = x < y && this.prevA >= this.prevB;
      r = (this.kind === "over" ? over : this.kind === "under" ? under : over || under) ? 1 : 0;
    }
    this.prevA = x;
    this.prevB = y;
    this.has = 1;
    return r;
  }
}

class RisingTa implements TaFn {
  w: Win;
  constructor(
    private rising: boolean,
    hint: TaHint,
  ) {
    this.w = new Win(winCap(hint));
  }
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const n = lenOf(a[1], this.w.cap);
    this.w.push(x);
    if (n !== n || this.w.seen <= n) return 0;
    for (let k = 1; k <= n; k++) {
      const o = this.w.at(k);
      if (this.rising ? !(x > o) : !(x < o)) return 0;
    }
    return 1;
  }
}

const isTrue = (v: unknown): boolean => (typeof v === "number" ? v !== 0 && v === v : v !== undefined && v !== null && v !== "");

class BarsSinceTa implements TaFn {
  calls = 0;
  last = -1;
  step(a: unknown[]): unknown {
    const idx = this.calls++;
    if (isTrue(a[0])) this.last = idx;
    return this.last < 0 ? NaN : idx - this.last;
  }
}

class ValueWhenTa implements TaFn {
  w: Win;
  constructor(hint: TaHint) {
    this.w = new Win(hint.occ !== undefined && hint.occ >= 0 ? Math.floor(hint.occ) + 1 : LIMITS.lookback + 1);
  }
  step(a: unknown[]): unknown {
    const k = num(a[2]);
    if (k !== k) return NaN;
    if (k < 0 || k !== Math.floor(k)) throw new ScriptRuntimeError("OCCURRENCE MUST BE A WHOLE NUMBER OF AT LEAST 0");
    if (k >= this.w.cap) throw new ScriptRuntimeError(`OCCURRENCE TOO LARGE (MAX ${LIMITS.lookback})`);
    if (isTrue(a[0])) this.w.push(num(a[1]));
    return this.w.seen <= k ? NaN : this.w.at(k);
  }
}

// ---------------------------------------------------------------- tuples

class MacdTa implements TaFn {
  ef = new Ema(0);
  es = new Ema(0);
  sg = new Ema(0);
  out = [NaN, NaN, NaN];
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const m = this.ef.next(x, lenOf(a[1])) - this.es.next(x, lenOf(a[2])); // both EMAs always advance
    const s = this.sg.next(m, lenOf(a[3]));
    this.out[0] = m;
    this.out[1] = s;
    this.out[2] = m - s;
    return this.out;
  }
}

class BbTa implements TaFn {
  w: Win;
  out = [NaN, NaN, NaN];
  constructor(hint: TaHint) {
    this.w = new Win(winCap(hint));
  }
  step(a: unknown[]): unknown {
    const x = num(a[0]);
    const n = lenOf(a[1], this.w.cap);
    const mult = num(a[2]);
    const w = this.w;
    w.push(x);
    if (n !== n || w.seen < n) {
      this.out[0] = this.out[1] = this.out[2] = NaN;
      return this.out;
    }
    let i = w.start(n);
    const i0 = i;
    let s = 0;
    for (let j = 0; j < n; j++) {
      s += w.buf[i];
      if (++i === w.cap) i = 0;
    }
    const mid = s / n;
    let ss = 0;
    i = i0;
    for (let j = 0; j < n; j++) {
      const d = w.buf[i] - mid;
      ss += d * d;
      if (++i === w.cap) i = 0;
    }
    const sd = Math.sqrt(ss / n);
    this.out[0] = mid;
    this.out[1] = mid + mult * sd;
    this.out[2] = mid - mult * sd;
    return this.out;
  }
}

class StochTa implements TaFn {
  hw: Win;
  lw: Win;
  constructor(hint: TaHint) {
    this.hw = new Win(winCap(hint));
    this.lw = new Win(winCap(hint));
  }
  step(a: unknown[]): unknown {
    const src = num(a[0]);
    const hi = num(a[1]);
    const lo = num(a[2]);
    const n = lenOf(a[3], this.hw.cap);
    this.hw.push(hi);
    this.lw.push(lo);
    if (n !== n || this.hw.seen < n) return NaN;
    let ih = this.hw.start(n);
    let il = this.lw.start(n);
    let hh = -Infinity;
    let ll = Infinity;
    for (let j = 0; j < n; j++) {
      const vh = this.hw.buf[ih];
      const vl = this.lw.buf[il];
      if (vh !== vh || vl !== vl) return NaN;
      if (vh > hh) hh = vh;
      if (vl < ll) ll = vl;
      if (++ih === this.hw.cap) ih = 0;
      if (++il === this.lw.cap) il = 0;
    }
    const range = hh - ll;
    return range === 0 ? NaN : (100 * (src - ll)) / range;
  }
}

// ---------------------------------------------------------------- the factory

/** The names `makeTa` knows (without the `ta.` prefix). Checked against names.ts by a test. */
export const TA_NAMES = [
  "sma", "ema", "wma", "rma", "vwma", "rsi", "stdev", "variance", "highest", "lowest", "change", "mom", "roc", "cum", "tr", "atr",
  "crossover", "crossunder", "cross", "rising", "falling", "barssince", "valuewhen", "linreg", "macd", "bb", "stoch",
];

export function makeTa(name: string, env: TaEnv, hint: TaHint): TaFn {
  switch (name) {
    case "sma":
    case "stdev":
    case "variance":
    case "highest":
    case "lowest":
    case "wma":
    case "vwma":
    case "linreg":
      return new WinTa(name, env, hint);
    case "ema":
      return new EmaTa(0);
    case "rma":
      return new EmaTa(1);
    case "rsi":
      return new RsiTa();
    case "tr":
      return new TrTa(env);
    case "atr":
      return new AtrTa(env);
    case "change":
    case "mom":
      return new ChangeTa("change", hint);
    case "roc":
      return new ChangeTa("roc", hint);
    case "cum":
      return new CumTa();
    case "crossover":
      return new CrossTa("over");
    case "crossunder":
      return new CrossTa("under");
    case "cross":
      return new CrossTa("either");
    case "rising":
      return new RisingTa(true, hint);
    case "falling":
      return new RisingTa(false, hint);
    case "barssince":
      return new BarsSinceTa();
    case "valuewhen":
      return new ValueWhenTa(hint);
    case "macd":
      return new MacdTa();
    case "bb":
      return new BbTa(hint);
    case "stoch":
      return new StochTa(hint);
    default:
      throw new Error(`no such ta function ${name}`);
  }
}

// ---------------------------------------------------------------- copying a state (live ticks)

/** Copy a state object (numbers, typed arrays, number arrays, nested states). */
export function snapState(o: object): unknown {
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(o)) {
    if (k === "env") continue; // the shared run context, not state
    const v = (o as Record<string, unknown>)[k];
    if (v instanceof Float64Array) out[k] = v.slice();
    else if (Array.isArray(v)) out[k] = v.slice();
    else if (typeof v === "object" && v !== null) out[k] = snapState(v);
    else out[k] = v;
  }
  return out;
}

/** Put a copy made by `snapState` back, in place (the compiled closures hold on to the state objects themselves). */
export function restoreState(o: object, snap: unknown): void {
  const s = snap as Record<string, unknown>;
  const t = o as Record<string, unknown>;
  for (const k of Object.keys(s)) {
    const cur = t[k];
    const v = s[k];
    if (cur instanceof Float64Array) cur.set(v as Float64Array);
    else if (Array.isArray(cur)) {
      const src = v as unknown[];
      for (let i = 0; i < src.length; i++) cur[i] = src[i];
      cur.length = src.length;
    } else if (typeof cur === "object" && cur !== null) restoreState(cur, v);
    else t[k] = v;
  }
}
