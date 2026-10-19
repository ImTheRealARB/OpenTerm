/** Pure wheel maths for components/Grid.tsx (the component itself needs a canvas, so it cannot run in vitest). */

/** New first-visible-row after a wheel event: 3 rows per event, clamped to the data. */
export function wheelTop(top: number, deltaY: number, rowCount: number, visible: number): number {
  const step = Math.sign(deltaY) * 3;
  return Math.max(0, Math.min(top + step, Math.max(0, rowCount - visible)));
}
