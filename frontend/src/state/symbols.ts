/**
 * Symbol interning.
 *
 * "Interning" means: the first time we see a symbol string ("AAPL") we give it a small integer id
 * (0, 1, 2, ...) and remember it. From then on the hot code carries the integer, not the string.
 * Why: an integer indexes a flat typed array in one step (`price[id]`), while a Map<string, ...> lookup
 * has to hash the string every time. The string -> id lookup (`symId`) happens only at the edges: when a
 * WebSocket frame is decoded (the wire carries strings) and when a panel lays out its rows. Everything
 * between (batching, dirty tracking, painting) uses ids only.
 *
 * Ids are never reused or freed (a terminal sees a few thousand symbols per session at most), so an id
 * stays valid for the life of the page and arrays indexed by id only ever grow.
 */

const ids = new Map<string, number>(); // string -> id: used ONLY at the edges, never in a per-tick loop over rows
const names: string[] = []; // id -> string (flat array, O(1))

/** Id marking "no symbol" (a section header row, an error row). Never a valid id. */
export const NO_SYM = 0xffffffff;

/** The id of `s`, created on first use. */
export function symId(s: string): number {
  let id = ids.get(s);
  if (id === undefined) {
    id = names.length;
    ids.set(s, id);
    names.push(s);
  }
  return id;
}

/** The id of `s` if it was interned before, else -1 (never creates one). */
export function peekSymId(s: string): number {
  return ids.get(s) ?? -1;
}

/** The string for an id. */
export const symName = (id: number): string => names[id];

/** How many symbols are interned so far: arrays indexed by id need at least this many slots. */
export const symCount = (): number => names.length;
