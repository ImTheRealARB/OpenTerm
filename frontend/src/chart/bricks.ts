/**
 * "Brick" chart transforms: Renko, Kagi, Point and Figure, Three Line Break and Range bars.
 *
 * What they have in common: a new mark is added when PRICE moves far enough, and the clock is ignored. A quiet week can
 * add nothing and one wild day can add ten marks. That is why every mark needs its own time stamp (see `makeStamp`)
 * and why the time axis of such a chart is not linear (the screen says so, see `brickNote` in chartTypes.ts).
 *
 * Every function here is pure (arrays in, arrays out, no chart library), so vitest can check them with tiny hand-worked inputs.
 * Inputs are the source bars as columns: `t` (epoch seconds), `o`, `h`, `l`, `c`.
 *
 * The box size: the user may give one (`BOX=2.5` in the GP arguments, price units). With none given we use ATR(14), the
 * average true range of the source bars, so the box is about one typical bar of movement. Each transform returns the box it
 * really used (`box`), so the screen can print it.
 */
import type { BoxUsed, ChartType } from "./chartTypes";

/** The source bars the transforms read. A `BarData` fits this shape. */
export interface SrcBars {
  t: ArrayLike<number>;
  o: ArrayLike<number>;
  h: ArrayLike<number>;
  l: ArrayLike<number>;
  c: ArrayLike<number>;
}

/** Candle-shaped bricks (Renko, Three Line Break, Range). Column `i` of every array is one brick. */
export interface OhlcBricks {
  kind: "ohlc";
  type: "RENKO" | "LINEBREAK" | "RANGE";
  t: number[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  /** null for Three Line Break (it has no box). */
  box: BoxUsed | null;
  /** true when the 100,000-mark safety limit stopped the transform (a box far too small for the price). */
  capped: boolean;
}

/** Kagi turning points. `yang[i]` = the line that ENDS at point i is yang (thick on paper): it rose above the previous shoulder. */
export interface KagiLine {
  kind: "kagi";
  t: number[];
  v: number[];
  yang: boolean[];
  box: BoxUsed;
  capped: boolean;
}

/** Point and Figure columns. Column `i` spans price `lo` to `hi` (box edges); `up[i]` = a column of X (rising), else O (falling). */
export interface PnfColumns {
  kind: "pnf";
  t: number[];
  lo: number[];
  hi: number[];
  up: boolean[];
  box: BoxUsed;
  capped: boolean;
}

export type BrickResult = OhlcBricks | KagiLine | PnfColumns;

/** Safety limit: a box far smaller than the price (BOX=0.0001 on a 150 stock) would make millions of marks. */
export const MAX_MARKS = 100_000;
const ATR_PERIOD = 14;
const DEFAULT_REV = 3;
/** A tiny nudge so 0.3 / 0.1 = 2.9999999999999996 still counts as 3 whole boxes. */
const EPS = 1e-9;

/** How many whole `size` steps fit in `diff`. */
const steps = (diff: number, size: number): number => Math.floor(diff / size + EPS);

/**
 * Time stamps for the marks. lightweight-charts needs strictly increasing times, but one source bar can finish several
 * marks (a 5-box jump makes 5 bricks). Each mark takes the time of the source bar that finished it; when that is not later than the
 * previous mark's time it takes `previous + 1` second instead.
 */
function makeStamp(): (t: number) => number {
  let prev = -Infinity;
  return (t) => {
    prev = t > prev ? t : prev + 1;
    return prev;
  };
}

/**
 * ATR (average true range, Wilder's smoothing) of the bars, last value. True range of a bar = its high-low range,
 * widened to include a gap from the previous close. The first `period` values are averaged; after that each new one
 * is blended in with weight 1/period. Fewer bars than `period`: the plain average of those there are.
 */
export function atrLast(h: ArrayLike<number>, l: ArrayLike<number>, c: ArrayLike<number>, period = ATR_PERIOD): number {
  const n = c.length;
  let sum = 0;
  let atr = NaN;
  for (let i = 0; i < n; i++) {
    const tr = i === 0 ? h[0] - l[0] : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1]));
    if (i < period) {
      sum += tr;
      if (i === period - 1 || i === n - 1) atr = sum / (i + 1);
    } else {
      atr = (atr * (period - 1) + tr) / period;
    }
  }
  return atr;
}

/** The box to use: the user's `BOX=` when it is a positive number, else ATR(14) of the source bars. */
export function resolveBox(d: SrcBars, box?: number): BoxUsed {
  if (box !== undefined && Number.isFinite(box) && box > 0) return { size: box, atr: false, period: ATR_PERIOD };
  return { size: atrLast(d.h, d.l, d.c), atr: true, period: ATR_PERIOD };
}

const validSize = (b: BoxUsed): boolean => Number.isFinite(b.size) && b.size > 0;

function emptyOhlc(type: OhlcBricks["type"], box: BoxUsed | null): OhlcBricks {
  return { kind: "ohlc", type, t: [], o: [], h: [], l: [], c: [], box, capped: false };
}

/** Adds one brick from `from` to `to` (a Renko or line-break mark: high and low are just the body ends). */
function pushBody(r: OhlcBricks, t: number, from: number, to: number): void {
  r.t.push(t);
  r.o.push(from);
  r.c.push(to);
  r.h.push(Math.max(from, to));
  r.l.push(Math.min(from, to));
}

/**
 * RENKO. Bricks of a fixed size, built from closing prices only.
 *  - A brick in the trend direction is added each time the close moves one whole box beyond the last brick's close.
 *  - A reversal needs TWO boxes against the trend (beyond the last brick's close); its first brick then opens at the
 *    last brick's OPEN, so there is always a one-box gap before a color change ("standard 2-box reversal").
 */
export function renko(d: SrcBars, boxIn?: number): OhlcBricks {
  const box = resolveBox(d, boxIn);
  const out = emptyOhlc("RENKO", box);
  const n = d.c.length;
  if (n === 0 || !validSize(box)) return out;
  const size = box.size;
  const stamp = makeStamp();
  let last = d.c[0]; // close of the newest brick (the very first close until a brick exists)
  let dir = 0; // 0 = no brick yet, 1 = last brick rose, -1 = last brick fell
  for (let i = 1; i < n && !out.capped; i++) {
    const c = d.c[i];
    const t = d.t[i];
    const up = steps(c - last, size);
    const down = steps(last - c, size);
    // Moves that continue the trend (or start one when there is no brick yet).
    if (up > 0 && dir >= 0) {
      for (let k = 0; k < up; k++) {
        if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
        pushBody(out, stamp(t), last, last + size);
        last += size;
      }
      dir = 1;
    } else if (down > 0 && dir <= 0) {
      for (let k = 0; k < down; k++) {
        if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
        pushBody(out, stamp(t), last, last - size);
        last -= size;
      }
      dir = -1;
    } else if (dir === 1 && down >= 2) {
      // Reversal from a rising trend: the first falling brick opens at the last brick's open (one box below its close).
      let from = last - size;
      for (let k = 1; k < down; k++) {
        if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
        pushBody(out, stamp(t), from, from - size);
        from -= size;
      }
      last = from;
      dir = -1;
    } else if (dir === -1 && up >= 2) {
      let from = last + size;
      for (let k = 1; k < up; k++) {
        if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
        pushBody(out, stamp(t), from, from + size);
        from += size;
      }
      last = from;
      dir = 1;
    }
  }
  return out;
}

/**
 * KAGI. A line that runs up or down with the closes and turns only when price reverses by the `reversal` amount from the
 * latest extreme. Output: the turning points, ending with the line still being drawn (its extreme so far).
 * Drawn as a step line (a vertical run, a short sideways hop at each turn).
 *
 * Yang / yin (thick / thin on paper): a rising line turns YANG when it rises above the previous shoulder (the last peak);
 * a falling line turns YIN when it falls below the previous waist (the last trough). It keeps that state until the other happens.
 * Thickness cannot change per point in lightweight-charts, so the screen colours yang up-colour and yin down-colour. A line that
 * crosses the old shoulder/waist is coloured as a whole (its state at its end), not split at the crossing price.
 */
export function kagi(d: SrcBars, reversalIn?: number): KagiLine {
  const box = resolveBox(d, reversalIn);
  const out: KagiLine = { kind: "kagi", t: [], v: [], yang: [], box, capped: false };
  const n = d.c.length;
  if (n === 0 || !validSize(box)) return out;
  const R = box.size;
  const stamp = makeStamp();
  const start = d.c[0];
  let dir = 0; // 0 = no line yet, 1 = rising, -1 = falling
  let ext = start; // the line's extreme so far (a high while rising, a low while falling)
  let tExt = stamp(d.t[0]);
  let shoulder = NaN; // last completed peak
  let waist = NaN; // last completed trough
  let yang = true;
  const origin = out.t.length; // 0: the first point is filled in once we know the first line's colour
  out.t.push(tExt);
  out.v.push(start);
  out.yang.push(true);
  for (let i = 1; i < n; i++) {
    const c = d.c[i];
    const t = d.t[i];
    if (dir === 0) {
      // Waiting for the first move of at least one reversal amount from the first close.
      if (c - start >= R - R * EPS) { dir = 1; waist = start; yang = true; ext = c; tExt = t; }
      else if (start - c >= R - R * EPS) { dir = -1; shoulder = start; yang = false; ext = c; tExt = t; }
      if (dir !== 0) out.yang[origin] = yang;
    } else if (dir === 1) {
      if (c > ext) {
        ext = c;
        tExt = t;
        if (ext > shoulder) yang = true; // rose above the previous shoulder (NaN compares false: no shoulder yet)
      } else if (ext - c >= R - R * EPS) {
        // Reversal: the rising line ends at its peak; a falling line starts from there.
        out.t.push(stamp(tExt));
        out.v.push(ext);
        out.yang.push(yang);
        if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
        shoulder = ext;
        dir = -1;
        ext = c;
        tExt = t;
        if (ext < waist) yang = false; // fell below the previous waist at once
      }
    } else if (c < ext) {
      // Falling line (dir === -1) goes lower.
      ext = c;
      tExt = t;
      if (ext < waist) yang = false; // fell below the previous waist
    } else if (c - ext >= R - R * EPS) {
      // Falling line reverses: it ends at its trough; a rising line starts from there.
      out.t.push(stamp(tExt));
      out.v.push(ext);
      out.yang.push(yang);
      if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
      waist = ext;
      dir = 1;
      ext = c;
      tExt = t;
      if (ext > shoulder) yang = true;
    }
  }
  // The line still being drawn.
  if (dir !== 0 && !out.capped) {
    out.t.push(stamp(tExt));
    out.v.push(ext);
    out.yang.push(yang);
  }
  return out;
}

/**
 * POINT AND FIGURE. Columns of X (price rising) and O (price falling), one box per mark, built from highs and lows.
 * Box `k` covers prices k*size up to (k+1)*size. An X column grows when a high reaches a new box; a column of O when a
 * low does. A column reverses when price moves `rev` boxes back from its end (default 3): the new column starts one box
 * inside the old one's end. A source bar that both extends the column and reaches the reversal counts as an extension
 * (bars do not record which came first).
 */
export function pointAndFigure(d: SrcBars, boxIn?: number, revIn?: number): PnfColumns {
  const box = resolveBox(d, boxIn);
  const rev = revIn !== undefined && Number.isInteger(revIn) && revIn >= 1 ? revIn : DEFAULT_REV;
  box.rev = rev;
  const out: PnfColumns = { kind: "pnf", t: [], lo: [], hi: [], up: [], box, capped: false };
  const n = d.c.length;
  if (n === 0 || !validSize(box)) return out;
  const size = box.size;
  const stamp = makeStamp();
  const idx = (p: number) => Math.floor(p / size + EPS); // box number holding price p
  const ref = idx(d.c[0]);
  let up = true; // direction of the column being built
  let started = false;
  let bottom = ref; // lowest / highest box of the column being built
  let top = ref;
  let tCol = d.t[0]; // the time of the last bar that grew the column
  const push = () => {
    out.t.push(stamp(tCol));
    out.lo.push(bottom * size);
    out.hi.push((top + 1) * size);
    out.up.push(up);
  };
  for (let i = 1; i < n; i++) {
    const hi = idx(d.h[i]);
    const lo = idx(d.l[i]);
    const t = d.t[i];
    if (!started) {
      // No column yet: wait for price to leave the starting box. Both ways in one bar: follow the bar's own direction.
      const goesUp = hi - ref >= 1;
      const goesDown = ref - lo >= 1;
      if (!goesUp && !goesDown) continue;
      started = true;
      up = goesUp && (!goesDown || d.c[i] >= d.o[i]);
      if (up) { bottom = ref; top = hi; } else { top = ref; bottom = lo; }
      tCol = t;
    } else if (up) {
      if (hi > top) { top = hi; tCol = t; }
      else if (top - lo >= rev) {
        push();
        if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
        up = false;
        top = top - 1;
        bottom = lo;
        tCol = t;
      }
    } else if (lo < bottom) { bottom = lo; tCol = t; }
    else if (hi - bottom >= rev) {
      push();
      if (out.t.length >= MAX_MARKS) { out.capped = true; break; }
      up = true;
      bottom = bottom + 1;
      top = hi;
      tCol = t;
    }
  }
  if (started && !out.capped) push();
  return out;
}

/**
 * THREE LINE BREAK. A line is drawn from closing prices, each starting at the previous line's close.
 *  - In the trend: a new line when the close goes beyond the previous line's end.
 *  - Against the trend: a new line only when the close goes beyond the highest high / lowest low of the last 3 lines (the "break").
 */
export function lineBreak(d: SrcBars): OhlcBricks {
  const out = emptyOhlc("LINEBREAK", null);
  const n = d.c.length;
  if (n < 2) return out;
  const stamp = makeStamp();
  for (let i = 1; i < n; i++) {
    const c = d.c[i];
    const m = out.t.length;
    if (m === 0) {
      // The first line: from the first close to the first close that differs from it.
      if (c !== d.c[0]) pushBody(out, stamp(d.t[i]), d.c[0], c);
      continue;
    }
    const lastUp = out.c[m - 1] > out.o[m - 1];
    const prevClose = out.c[m - 1];
    // Highest and lowest point of the last 3 lines.
    let hi = -Infinity;
    let lo = Infinity;
    for (let k = Math.max(0, m - 3); k < m; k++) {
      hi = Math.max(hi, out.h[k]);
      lo = Math.min(lo, out.l[k]);
    }
    const trendUp = lastUp ? c > out.h[m - 1] : c > hi; // a white line: beyond the last high (trend up) or beyond the 3-line high (reversal)
    const trendDown = lastUp ? c < lo : c < out.l[m - 1];
    if (trendUp || trendDown) {
      if (m >= MAX_MARKS) { out.capped = true; break; }
      pushBody(out, stamp(d.t[i]), prevClose, c);
    }
  }
  return out;
}

/**
 * RANGE BARS. Every bar has the same high-low range (`range`); a bar ends when price has moved that far, and the next
 * bar opens at its close. Source bars only record open / high / low / close, not the order the prices happened in, so
 * each source bar is walked as: open, then whichever of high / low is NEARER the open, then the other one, then the close.
 * That order is an assumption (the screen says so).
 */
export function rangeBars(d: SrcBars, rangeIn?: number): OhlcBricks {
  const box = resolveBox(d, rangeIn);
  const out = emptyOhlc("RANGE", box);
  const n = d.c.length;
  if (n === 0 || !validSize(box)) return out;
  const R = box.size;
  const stamp = makeStamp();
  let o = d.o[0]; // the bar being built
  let h = o;
  let l = o;
  /** Feeds one price of the walk. A price can complete several bars (a big gap), so it loops until the price is absorbed. */
  const walk = (p: number, t: number) => {
    while (!out.capped) {
      if (p > h) {
        if (p - l >= R - R * EPS) {
          const close = l + R; // the bar ends exactly one range above its low
          if (out.t.length >= MAX_MARKS) { out.capped = true; return; }
          out.t.push(stamp(t));
          out.o.push(o);
          out.h.push(close);
          out.l.push(l);
          out.c.push(close);
          o = h = l = close;
          continue; // the same price may complete more bars
        }
        h = p;
      } else if (p < l) {
        if (h - p >= R - R * EPS) {
          const close = h - R;
          if (out.t.length >= MAX_MARKS) { out.capped = true; return; }
          out.t.push(stamp(t));
          out.o.push(o);
          out.h.push(h);
          out.l.push(close);
          out.c.push(close);
          o = h = l = close;
          continue;
        }
        l = p;
      }
      return;
    }
  };
  for (let i = 0; i < n && !out.capped; i++) {
    const t = d.t[i];
    const highFirst = d.h[i] - d.o[i] <= d.o[i] - d.l[i]; // is the high nearer the open than the low?
    walk(d.o[i], t);
    walk(highFirst ? d.h[i] : d.l[i], t);
    walk(highFirst ? d.l[i] : d.h[i], t);
    walk(d.c[i], t);
  }
  return out;
}

/** Runs the transform for a brick chart type, or returns null when `type` is not a brick type. */
export function buildBricks(type: ChartType, d: SrcBars, opts: { box?: number; rev?: number } = {}): BrickResult | null {
  switch (type) {
    case "RENKO": return renko(d, opts.box);
    case "KAGI": return kagi(d, opts.box);
    case "PNF": return pointAndFigure(d, opts.box, opts.rev);
    case "LINEBREAK": return lineBreak(d);
    case "RANGE": return rangeBars(d, opts.box);
    default: return null;
  }
}

// ---- What the crosshair and the readout line see: the bricks, not the source bars --------------------------------------

/** How many marks the chart shows. */
export function brickCount(r: BrickResult): number {
  return r.t.length;
}

/** Time of mark `i` (epoch seconds, strictly increasing). */
export function brickTime(r: BrickResult, i: number): number {
  return r.t[i];
}

/** The price the crosshair sits on for mark `i`: a brick's close, a kagi point, the end of a P&F column. */
export function brickPrice(r: BrickResult, i: number): number {
  if (r.kind === "ohlc") return r.c[i];
  if (r.kind === "kagi") return r.v[i];
  return r.up[i] ? r.hi[i] : r.lo[i];
}

/** 1 = rising mark, -1 = falling mark (drives the readout colour). */
export function brickDir(r: BrickResult, i: number): number {
  if (r.kind === "ohlc") return r.c[i] >= r.o[i] ? 1 : -1;
  if (r.kind === "kagi") return i > 0 && r.v[i] < r.v[i - 1] ? -1 : 1;
  return r.up[i] ? 1 : -1;
}

/** The readout text for mark `i` (without the date). `fp` formats a price. */
export function brickText(r: BrickResult, i: number, fp: (x: number) => string): string {
  if (r.kind === "ohlc") {
    return r.type === "RANGE"
      ? `RANGE  O ${fp(r.o[i])}  H ${fp(r.h[i])}  L ${fp(r.l[i])}  C ${fp(r.c[i])}`
      : `${r.type === "RENKO" ? "RENKO" : "3LB"}  O ${fp(r.o[i])}  C ${fp(r.c[i])}`;
  }
  if (r.kind === "kagi") return `KAGI  ${fp(r.v[i])}  ${r.yang[i] ? "YANG" : "YIN"}`;
  return `P&F  ${r.up[i] ? "X" : "O"}  ${fp(r.lo[i])} - ${fp(r.hi[i])}`;
}
