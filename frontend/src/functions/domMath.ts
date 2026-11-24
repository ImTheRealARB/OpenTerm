/**
 * Phase 23: DOM (depth ladder) and LIQH (liquidity heatmap), the pure part. Read-only views of an order book; nothing here
 * can send anything to an exchange.
 *
 * Levels come from the existing crypto depth route (`/api/world/cdep`) as `[price, qty, ...]`, best price first.
 */
export type Lvl = readonly number[]; // [price, qty, cumQty?, cumNotional?]

export interface DomRow {
  price: number;
  side: "ask" | "bid";
  qty: number;
}

/** One vertical ladder: asks above the spread (highest at the top), bids below, `n` levels a side. */
export function domRows(bids: Lvl[], asks: Lvl[], n: number): DomRow[] {
  const a = asks.slice(0, n).map((l): DomRow => ({ price: l[0], side: "ask", qty: l[1] }));
  const b = bids.slice(0, n).map((l): DomRow => ({ price: l[0], side: "bid", qty: l[1] }));
  return [...a.reverse(), ...b];
}

export interface Snapshot {
  t: number; // epoch ms when it was taken
  bids: Lvl[];
  asks: Lvl[];
}

/** At most this many snapshots are kept in memory (5 s apart: 2 hours). Nothing is written to disk (recorder is off). */
export const MAX_SNAPS = 1440;

/** Appends a snapshot, dropping the oldest past the cap. Returns a new array (React state). */
export function pushSnap(list: Snapshot[], s: Snapshot): Snapshot[] {
  const out = list.length >= MAX_SNAPS ? list.slice(list.length - MAX_SNAPS + 1) : list.slice();
  out.push(s);
  return out;
}

export interface Heat {
  lo: number;
  step: number;
  rows: number;
  /** cells[snapshot][row] = resting quantity in that price row (bids and asks together). */
  cells: Float64Array[];
  max: number;
}

/**
 * The heatmap grid: price rows between the lowest and highest level seen, `rows` of them, one column per snapshot.
 * Quantity is summed per row; the painter shades each cell by qty / max.
 */
export function heatGrid(snaps: Snapshot[], rows = 60): Heat | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of snaps)
    for (const l of [...s.bids, ...s.asks]) {
      if (l[0] < lo) lo = l[0];
      if (l[0] > hi) hi = l[0];
    }
  if (!Number.isFinite(lo) || !(hi > lo)) return null;
  const step = (hi - lo) / rows;
  let max = 0;
  const cells = snaps.map((s) => {
    const col = new Float64Array(rows);
    for (const l of [...s.bids, ...s.asks]) {
      const r = Math.min(rows - 1, Math.floor((l[0] - lo) / step));
      col[r] += l[1];
      if (col[r] > max) max = col[r];
    }
    return col;
  });
  return { lo, step, rows, cells, max };
}
