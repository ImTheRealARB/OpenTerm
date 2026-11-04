/**
 * Which column is under a mouse x position (pure, so it runs in Node tests).
 * `xs` = left edge of each column in canvas pixels (before scrolling), `end` = right edge of the last column,
 * `scrollX` = how far the grid is scrolled sideways (0 today: the grid does not scroll horizontally).
 * Returns the column index, or -1 when the mouse is past the last column.
 */
export function headerHit(x: number, xs: readonly number[], end: number, scrollX = 0): number {
  const px = x + scrollX;
  if (!xs.length || px < 0 || px >= end) return -1;
  let lo = 0;
  let hi = xs.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (xs[mid] <= px) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
