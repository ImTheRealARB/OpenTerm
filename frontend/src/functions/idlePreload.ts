/**
 * Warms function chunks a few at a time while the browser is idle, instead of starting all ~88 downloads at once
 * right after first paint (which competes with the user's first keystrokes and the first quote fetch).
 * `schedule` runs a callback when idle; `load` downloads one function. Pure, so vitest can drive it with fakes.
 */
export function idlePreload(
  codes: string[],
  load: (code: string) => Promise<unknown>,
  schedule: (cb: () => void) => void,
  batch = 3,
): void {
  let next = 0;
  const step = () => {
    const mine = codes.slice(next, next + batch);
    next += batch;
    // Wait for this batch to settle (a failed download is ignored), then ask for the next idle slot.
    void Promise.all(mine.map((c) => load(c).catch(() => {}))).then(() => {
      if (next < codes.length) schedule(step);
    });
  };
  if (codes.length) schedule(step);
}
