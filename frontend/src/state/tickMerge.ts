/**
 * Pure helper for the tick buffer (ticks.ts imports perf/metrics, which needs `window`, so it cannot run in vitest).
 * Row layout: [symbol, price, change, pct, volume, high, low, time, src].
 */

/**
 * `next` replaces `prev` in the per-frame buffer. A null field means "not in this tick", so fill it from `prev`
 * (same frame, same symbol) instead of dropping it: the flush only applies the last row of a symbol.
 * Mutates `next` in place, no allocation.
 */
export function carryNulls(prev: (number | string | null)[] | undefined, next: (number | string | null)[]): void {
  if (!prev) return;
  for (let i = 2; i <= 6; i++) if (next[i] == null && prev[i] != null) next[i] = prev[i];
}
