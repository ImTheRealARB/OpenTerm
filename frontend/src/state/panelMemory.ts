import type { PanelState } from "./workspace";

/**
 * Per-panel memory that outlives the React component.
 *
 * A typed command (`AI what drove margins?`) adds a history entry, which REMOUNTS the panel
 * (Panel.tsx keys the component on `pos`), so anything held in `useState` is lost. AI keeps its
 * chat and loaded document here instead, SWARM its run, so a remount finds them again.
 * Plain module-level Map, no React and no browser APIs, so it is unit-testable in Node.
 *
 * Entries are keyed by (function code, panel id, slot). They are forgotten by `pruneMemory`
 * when the panel is closed, or no longer has that function anywhere in its history.
 * Panel ids are reused (`split` takes the lowest free id), so stale entries MUST go, or a new
 * panel would show a dead panel's conversation.
 */
interface Entry {
  fn: string;
  id: number;
  value: unknown;
  /** What a fresh panel starts with; `memResetAll` puts this back. */
  initial: unknown;
  listeners: Set<() => void>;
}

const entries = new Map<string, Entry>();
const keyOf = (fn: string, id: number, slot: string) => `${fn}\u0000${id}\u0000${slot}`;

/** Current value; the first read stores `initial` so the same reference comes back every time. */
export function memGet<T>(fn: string, id: number, slot: string, initial: T): T {
  const k = keyOf(fn, id, slot);
  let e = entries.get(k);
  if (!e) {
    e = { fn, id, value: initial, initial, listeners: new Set() };
    entries.set(k, e);
  }
  return e.value as T;
}

/**
 * Writes a new value (or `update(previous)`) and tells every mounted reader.
 * Does nothing when the entry is gone (panel closed): a late write from a finished stream
 * must not bring a dead panel's memory back.
 */
export function memSet<T>(fn: string, id: number, slot: string, next: T | ((prev: T) => T)): void {
  const e = entries.get(keyOf(fn, id, slot));
  if (!e) return;
  const value = typeof next === "function" ? (next as (prev: T) => T)(e.value as T) : next;
  if (Object.is(value, e.value)) return;
  e.value = value;
  // Copy first: a listener may unsubscribe while we notify.
  [...e.listeners].forEach((l) => l());
}

/** Subscribes to one slot (React's `useSyncExternalStore` shape). Creates the entry if needed. */
export function memSubscribe<T>(fn: string, id: number, slot: string, initial: T, listener: () => void): () => void {
  memGet(fn, id, slot, initial);
  const e = entries.get(keyOf(fn, id, slot));
  if (!e) return () => undefined;
  e.listeners.add(listener);
  return () => {
    e.listeners.delete(listener);
  };
}

/** Drops entries whose panel is gone or never showed that function. Call on every workspace change. */
export function pruneMemory(s: { panels: Record<number, PanelState> }): void {
  for (const [k, e] of entries) {
    const p = s.panels[e.id];
    if (!p || !p.views.some((v) => v.fn === e.fn)) entries.delete(k);
  }
}

/**
 * Puts every entry back to its initial value and tells the mounted readers.
 * A layout load replaces the whole workspace, so no panel may inherit a conversation, document
 * or run from whatever held its id before. `pruneMemory` is not enough: when the old and the new
 * layout both have an AI panel under the same id, the function is still "in its history" and the
 * old chat would survive. The entries are kept (not deleted) so panels that stay mounted through
 * the load keep their subscription and show the empty state.
 */
export function memResetAll(): void {
  for (const e of entries.values()) {
    if (Object.is(e.value, e.initial)) continue;
    e.value = e.initial;
    [...e.listeners].forEach((l) => l());
  }
}

/** Test helper: forget everything. */
export function memClear(): void {
  entries.clear();
}
