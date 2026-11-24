/**
 * Pure layout maths for the FOOT footprint canvas (no DOM, no React): which bars and price levels are on screen, how a cell's text is
 * cut, how the cumulative delta line maps to pixels. Kept apart from FOOT.tsx so vitest can check it without a canvas.
 *
 * Vocabulary: a bar is one column (one time interval); a level is one row (one price step). `back` = how many bars the view is
 * scrolled away from the newest one; `shift` = how many levels the view is scrolled away from centring on the last price.
 */
import { fmtQty } from "./flowArgs";

export const COL_CH_MIN = 7; // narrowest column, in characters
export const COL_CH_MAX = 21;
export const COL_CH_DEFAULT = 13;
/** Fixed rows under the ladder: DELTA, CUM, and the cumulative delta line (3 rows tall). Plus 1 time header row on top. */
export const FOOTER_ROWS = 2 + 3;
export const HEADER_ROWS = 1;

/** Keeps `back` (bars hidden at the newest end) inside what exists: 0 shows the newest bar, total - cols the oldest page. */
export function clampBack(back: number, total: number, cols: number): number {
  return Math.max(0, Math.min(back, Math.max(0, total - cols)));
}

/** Bars shown: [start, end) indexes into the bar list, `cols` wide, ending `back` bars before the newest. */
export function visibleBars(total: number, cols: number, back: number): [number, number] {
  const b = clampBack(back, total, cols);
  const end = total - b;
  return [Math.max(0, end - cols), end];
}

/** Whole columns that fit in `width` px after the price axis. At least 1. */
export function columnsFit(width: number, axisPx: number, colPx: number): number {
  return Math.max(1, Math.floor((width - axisPx) / colPx));
}

/** Ladder rows that fit in `height` px. At least 3, so a tiny panel still shows something. */
export function ladderRows(height: number, rowPx: number): number {
  return Math.max(3, Math.floor(height / rowPx) - HEADER_ROWS - FOOTER_ROWS);
}

/**
 * Index of the HIGHEST level on screen. `center` is the level to keep in the middle (the last price), `shift` moves the view up
 * (positive) or down (negative). Clamped so the ladder never shows rows past either end.
 */
export function levelTop(nLevels: number, rows: number, center: number, shift: number): number {
  const shown = Math.min(rows, nLevels);
  const want = center + Math.floor(shown / 2) + shift;
  return Math.max(shown - 1, Math.min(nLevels - 1, want));
}

/** The level index nearest to `price` (levels ascend by `step` from `levels[0]`), clamped to the ladder. */
export function levelOf(price: number, levels: readonly number[], step: number): number {
  if (levels.length === 0) return 0;
  return Math.max(0, Math.min(levels.length - 1, Math.floor((price - levels[0]) / step + 1e-9)));
}

/** Decimals needed to print a price at this step: 0.5 -> 1, 0.01 -> 2, 5 -> 0, 1e-6 -> 6 (capped at 8). */
export function stepDecimals(step: number): number {
  if (!(step > 0)) return 2;
  return Math.min(8, Math.max(0, Math.ceil(-Math.log10(step) - 1e-9)));
}

/** The two halves of a footprint cell, "bid x ask": bid = aggressor sells (left), ask = aggressor buys (right). */
export function cellParts(bid: number, ask: number): { bid: string; ask: string } {
  return { bid: bid > 0 ? fmtQty(bid) : "", ask: ask > 0 ? fmtQty(ask) : "" };
}

/** Does a cell's text fit? Each half gets half the column minus room for the "x" in the middle. */
export function halfFits(textChars: number, colCh: number): boolean {
  return textChars <= (colCh - 3) / 2;
}

/** Pixel y of each value of a line drawn in a strip `h` tall starting at `top`: min at the bottom, max at the top, flat = middle. */
export function lineY(values: readonly number[], top: number, h: number): number[] {
  if (values.length === 0) return [];
  const lo = Math.min(...values, 0); // always include zero, so the zero line is on the strip
  const hi = Math.max(...values, 0);
  if (hi === lo) return values.map(() => top + h / 2);
  return values.map((v) => top + h - ((v - lo) / (hi - lo)) * h);
}

/** Pixel y of the zero line for the same strip as `lineY`. */
export function zeroY(values: readonly number[], top: number, h: number): number {
  return lineY([...values, 0], top, h).at(-1) ?? top + h / 2;
}
