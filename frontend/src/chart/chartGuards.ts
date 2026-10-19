/** Small pure helpers for ChartView (vitest runs in Node, so they live apart from the React file). */

/** A bar index kept inside `n` bars (-1 when there are none). */
export function clampIndex(i: number, n: number): number {
  return n <= 0 ? -1 : Math.max(0, Math.min(n - 1, i));
}

/** Identity-free key of a list prop: a caller passing a fresh `[]` every render must not rebuild the chart. */
export function listKey(list: readonly string[] | undefined): string {
  return list ? list.join(",") : "";
}
