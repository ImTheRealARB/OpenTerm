/**
 * Pure parts of `useLiveRows` (quoteRows.ts), kept free of React and the DOM so vitest (Node) can test them.
 * The hook subscribes the symbols of a grid's rows and repaints only the rows a tick touched.
 */
import { bitSet, bitWords } from "../state/bitset";
import { NO_SYM, symId } from "../state/symbols";

/** Row position -> its live symbol, "" for rows with none (section headers, errors). */
export function symbolLayout<R>(rows: R[], symbolOf: (r: R) => string | undefined): string[] {
  const out = new Array<string>(rows.length);
  for (let i = 0; i < rows.length; i++) out[i] = symbolOf(rows[i]) ?? "";
  return out;
}

/** The symbols to subscribe, in first-seen order, joined with "," (a stable effect key). */
export function subscriptionKey(layout: readonly string[]): string {
  const seen = new Set<string>();
  for (const s of layout) if (s) seen.add(s);
  return [...seen].join(",");
}

/** Row position -> interned symbol id (NO_SYM for rows with no symbol). Built once per `rows` change, not per tick. */
export function rowIds(layout: readonly string[]): Uint32Array {
  const out = new Uint32Array(layout.length);
  for (let i = 0; i < layout.length; i++) out[i] = layout[i] ? symId(layout[i]) : NO_SYM;
  return out;
}

/**
 * Which grid rows show which symbol, as two flat integer arrays (a "linked list in arrays", also called CSR/chained index).
 * Idea: a Map<symbol, number[]> allocates an array per symbol and hashes strings on every lookup. Instead:
 *   head[id]  = the first row position that shows symbol `id`, or -1 if none
 *   next[row] = the next row position that shows the SAME symbol as `row`, or -1 at the end of the chain
 * To visit every row of symbol `id`:  for (r = head[id]; r >= 0; r = next[r]) ...
 * `dirty` is a bitset (one bit per row position): bit r set = "row r must be repainted this frame".
 * Allocated once per `rows` change and reused by every frame.
 */
export interface RowIndex {
  head: Int32Array;
  next: Int32Array;
  dirty: Uint32Array;
}

export function buildRowIndex(ids: Uint32Array): RowIndex {
  let max = -1;
  for (let i = 0; i < ids.length; i++) if (ids[i] !== NO_SYM && ids[i] > max) max = ids[i];
  const head = new Int32Array(max + 1).fill(-1);
  const next = new Int32Array(ids.length).fill(-1);
  // Walk backwards so each chain ends up in ascending row order (head = lowest row).
  for (let i = ids.length - 1; i >= 0; i--) {
    const id = ids[i];
    if (id === NO_SYM) continue;
    next[i] = head[id];
    head[id] = i;
  }
  return { head, next, dirty: new Uint32Array(bitWords(ids.length)) };
}

/**
 * Mark the rows of every symbol in `changed[0..count)` as dirty. Returns how many marks it made (0 = nothing to repaint).
 * No allocation: it only reads the two index arrays and writes bits.
 */
export function markHits(index: RowIndex, changed: Uint32Array, count: number): number {
  const { head, next, dirty } = index;
  let n = 0;
  for (let k = 0; k < count; k++) {
    const id = changed[k];
    if (id >= head.length) continue; // a symbol interned after this index was built: no row shows it
    for (let r = head[id]; r >= 0; r = next[r]) {
      bitSet(dirty, r);
      n++;
    }
  }
  return n;
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
