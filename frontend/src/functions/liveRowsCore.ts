/**
 * Pure parts of `useLiveRows` (quoteRows.ts), kept free of React and the DOM so vitest (Node) can test them.
 * The hook subscribes the symbols of a grid's rows and repaints only the rows a tick touched.
 */

/** Row position -> its live symbol, "" for rows with none (section headers, errors). */
export function symbolLayout<R>(rows: R[], symbolOf: (r: R) => string | undefined): string[] {
  const out = new Array<string>(rows.length);
  for (let i = 0; i < rows.length; i++) out[i] = symbolOf(rows[i]) ?? "";
  return out;
}

export function sameLayout(a: readonly string[], b: readonly string[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/** Symbol -> the row positions that show it (a symbol can sit on more than one row). */
export function buildSymbolIndex(layout: readonly string[]): Map<string, number[]> {
  const index = new Map<string, number[]>();
  for (let i = 0; i < layout.length; i++) {
    const s = layout[i];
    if (!s) continue;
    const at = index.get(s);
    if (at) at.push(i);
    else index.set(s, [i]);
  }
  return index;
}

/** The symbols to subscribe, in first-seen order, joined with "," (a stable effect key). */
export function subscriptionKey(layout: readonly string[]): string {
  const seen = new Set<string>();
  for (const s of layout) if (s) seen.add(s);
  return [...seen].join(",");
}

/** Row positions to repaint for the symbols that changed. */
export function hitRows(index: ReadonlyMap<string, number[]>, changed: Iterable<string>): number[] {
  const hit: number[] = [];
  for (const s of changed) {
    const idx = index.get(s);
    if (idx) for (const i of idx) hit.push(i);
  }
  return hit;
}

/**
 * Memo keyed on the symbol layout, not on the `rows` array identity: a REST refresh that returns the same
 * symbols in the same order keeps the old index. `cache` lives in a ref owned by the caller.
 */
export interface IndexCache {
  layout: string[];
  index: Map<string, number[]>;
}
export function cachedIndex(cache: { current: IndexCache | null }, layout: string[]): Map<string, number[]> {
  const c = cache.current;
  if (c && sameLayout(c.layout, layout)) return c.index;
  const index = buildSymbolIndex(layout);
  cache.current = { layout, index };
  return index;
}

/** The slice of `document` the age timer needs. */
export interface VisibilityDoc {
  hidden: boolean;
  addEventListener(type: "visibilitychange", fn: () => void): void;
  removeEventListener(type: "visibilitychange", fn: () => void): void;
}

/**
 * Calls `redraw` every `ms` while the page is visible. While hidden no timer runs; becoming visible
 * redraws once at once (the AGE/STALE text jumped on while hidden), then resumes the interval.
 */
export function startAgeRedraw(redraw: () => void, ms: number, doc: VisibilityDoc | undefined): () => void {
  let timer: ReturnType<typeof setInterval> | undefined;
  const start = () => {
    if (timer === undefined) timer = setInterval(redraw, ms);
  };
  const stop = () => {
    if (timer !== undefined) clearInterval(timer);
    timer = undefined;
  };
  const onVis = () => {
    if (doc?.hidden) stop();
    else {
      stop();
      redraw();
      start();
    }
  };
  if (!doc?.hidden) start();
  doc?.addEventListener("visibilitychange", onVis);
  return () => {
    stop();
    doc?.removeEventListener("visibilitychange", onVis);
  };
}
