/**
 * Pure geometry and flag rules for the small graphics drawn inside board cells (WEI, FX, CMDTY): the 2DAY sparkline, the
 * %CHG bar and the one-letter data-status flag. No DOM and no canvas here (so vitest can test every rule); `Board.tsx` turns
 * these numbers into canvas calls through the `Column.draw` hook of `Grid.tsx`.
 *
 * DATA-STATUS FLAG (one letter after the LAST value). Only real evidence is used; when it cannot tell, the cell is blank.
 *   evidence                                                              flag
 *   a live tick whose source code is y (Yahoo stream), p (Yahoo poll),
 *     a (RT IEX), k (RT KITE) or s (SYNTHETIC)                            blank  (the code does not say whether the feed is
 *                                                                                 delayed: Yahoo's delay differs per exchange and
 *                                                                                 is not in the tick; a, k are real time)
 *   no live tick, snapshot marked STALE (our copy is older than its TTL)  d  delayed
 *   no live tick, fresh snapshot, last trade older than CLOSED_AFTER_S    c  close (the session is over: this is the last close)
 *   no live tick, fresh snapshot, last trade newer than that              blank
 *   error row, or no quote yet                                            blank
 * The only inference is the `c` rule: a fresh snapshot whose last trade is more than 20 minutes old means nothing traded since
 * (Yahoo's documented feed delay is up to 15 minutes, so 20 leaves headroom). It reads the trade time, never a guessed clock.
 */

/** A %CHG of this size (either way) fills the whole half-width of the bar cell; bigger moves are clamped to it. */
export const BAR_FULL_PCT = 3;

/** Last trade older than this (seconds), with no live tick and a fresh snapshot: the market is closed, show `c`. */
export const CLOSED_AFTER_S = 20 * 60;

/** Blank pixels kept free at each end of a bar cell. */
const BAR_INSET = 2;

/** Where to fill a change bar inside a cell of width `w`: `x` is relative to the cell's left edge. Null = draw nothing. */
export interface BarSpan {
  x: number;
  w: number;
  up: boolean;
}

/**
 * A bar growing from the cell centre: right for a rise (`up`), left for a fall. Length is |pct| / `fullPct` of the half-width,
 * clamped to 1, and at least one pixel for any real move. Zero, null and non-finite give null (no bar).
 */
export function barSpan(pct: number | null | undefined, w: number, fullPct: number = BAR_FULL_PCT): BarSpan | null {
  if (pct == null || !Number.isFinite(pct) || pct === 0 || !(w > 2 * BAR_INSET + 2)) return null;
  const centre = w / 2;
  const half = centre - BAR_INSET;
  const len = Math.max(1, Math.min(1, Math.abs(pct) / fullPct) * half);
  return pct > 0 ? { x: centre, w: len, up: true } : { x: centre - len, w: len, up: false };
}

/** Value range of a series (finite numbers only). `last` replaces the final point (the live price) when given. */
export interface Bounds {
  min: number;
  max: number;
  /** How many finite points were seen (the series is drawable from 2). */
  n: number;
}

/**
 * Fills `out` (reused by the caller: no allocation per paint) with the min / max of the finite points in `values`, with `last`
 * standing in for the final point when it is finite. Returns `out`.
 */
export function sparkBounds(values: readonly number[], last: number | null | undefined, out: Bounds): Bounds {
  let min = Infinity;
  let max = -Infinity;
  let n = 0;
  const end = values.length - 1;
  for (let i = 0; i <= end; i++) {
    const v = i === end && last != null && Number.isFinite(last) ? last : values[i];
    if (!Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
    n++;
  }
  out.min = min;
  out.max = max;
  out.n = n;
  return out;
}

/**
 * Pixel y for value `v` inside a box of height `h` with `pad` pixels free at top and bottom (value `max` at the top).
 * A flat series (min == max) sits on the middle line instead of dividing by zero.
 */
export function sparkY(v: number, min: number, max: number, h: number, pad: number): number {
  const inner = h - 2 * pad;
  return max > min ? pad + (1 - (v - min) / (max - min)) * inner : h / 2;
}

/** Pixel x for point `i` of `count` points across a box of width `w` with `pad` free at each end. */
export function sparkX(i: number, count: number, w: number, pad: number): number {
  return count > 1 ? pad + (i / (count - 1)) * (w - 2 * pad) : w / 2;
}

/** The facts the flag reads. All real values from the quote row (see the table above). */
export interface FlagInput {
  /** The row has no quote yet or failed to load. */
  missing: boolean;
  /** The row currently shows a live tick (stream or poll). */
  live: boolean;
  /** The snapshot is marked stale by the server. */
  stale: boolean;
  /** Epoch seconds of the last trade in the snapshot, or null when the quote does not say. */
  tradeTime: number | null;
  /** Now, epoch seconds (passed in so tests are deterministic). */
  now: number;
}

/** The one-letter status: "d" delayed, "c" close, "" when real time or when the evidence cannot say. */
export function statusFlag(f: FlagInput): "d" | "c" | "" {
  if (f.missing || f.live) return "";
  if (f.stale) return "d";
  if (f.tradeTime != null && f.now - f.tradeTime > CLOSED_AFTER_S) return "c";
  return "";
}
