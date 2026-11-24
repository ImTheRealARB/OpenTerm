/**
 * Phase 24: bar replay and the replay paper book. Pure (no React, no network), so vitest covers it.
 *
 * REPLAY hides every bar after a chosen one and reveals them one at a time. The chart is handed ONLY the revealed bars
 * (`revealed` returns views of the first n bars), so indicators, studies and profiles are computed from those bars alone and
 * cannot see the future: there is nothing after bar n in what they receive. `replay.test.ts` checks that for every built-in
 * indicator by changing the hidden bars and comparing.
 *
 * The paper book is practice only, never sent anywhere: an order typed during replay fills at the NEXT revealed bar's open
 * (you cannot trade at a price you have already seen close), one fixed quantity per key press, long or short.
 */
import type { BarData } from "./chartBase";

/** Bars per second for play. `s` cycles them. */
export const SPEEDS = [1, 2, 5, 10] as const;

/** How many bars to show first: the bars up to and including the last one before `startT` (epoch seconds). At least 1. */
export function firstReveal(t: Float64Array, startT: number): number {
  let lo = 0;
  let hi = t.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (t[mid] < startT) lo = mid + 1;
    else hi = mid;
  }
  return Math.max(1, Math.min(t.length, lo));
}

/** The first `n` bars, as views (no copy): what the chart and every study receive during replay. */
export function revealed(b: BarData, n: number): BarData {
  const k = Math.max(1, Math.min(b.t.length, n));
  return { ...b, t: b.t.subarray(0, k), o: b.o.subarray(0, k), h: b.h.subarray(0, k), l: b.l.subarray(0, k), c: b.c.subarray(0, k), v: b.v.subarray(0, k) };
}

/** `YYYY-MM-DD` -> epoch seconds at UTC midnight, or null. */
export function parseDay(s: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  const d = new Date(t);
  return d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3] ? t / 1000 : null;
}

// --- the replay paper book ---------------------------------------------------------------------------------------------
export interface Fill {
  t: number; // bar time of the fill (epoch seconds)
  side: "BUY" | "SELL";
  qty: number;
  price: number;
}

export interface Book {
  qty: number; // signed position: + long, - short
  avg: number; // average entry price of the open position (0 when flat)
  realized: number;
  fills: Fill[];
  pending: { side: "BUY" | "SELL"; qty: number }[]; // waiting for the next bar's open
}

export const emptyBook = (): Book => ({ qty: 0, avg: 0, realized: 0, fills: [], pending: [] });

/** Queue an order for the next revealed bar's open. `FLAT` queues whatever closes the position (nothing when flat). */
export function queue(b: Book, side: "BUY" | "SELL" | "FLAT", qty: number): Book {
  if (side === "FLAT") {
    const open = b.qty + b.pending.reduce((s, p) => s + (p.side === "BUY" ? p.qty : -p.qty), 0);
    if (!open) return b;
    return { ...b, pending: [...b.pending, { side: open > 0 ? "SELL" : "BUY", qty: Math.abs(open) }] };
  }
  return { ...b, pending: [...b.pending, { side, qty }] };
}

/** One fill against the position: closing part books P&L at the fill price, the rest opens / adds at that price. */
function apply(b: Book, f: Fill): Book {
  const signed = f.side === "BUY" ? f.qty : -f.qty;
  let { qty, avg, realized } = b;
  if (qty !== 0 && Math.sign(signed) !== Math.sign(qty)) {
    const closing = Math.min(Math.abs(signed), Math.abs(qty));
    realized += closing * (f.price - avg) * Math.sign(qty);
    qty += Math.sign(signed) * closing;
    const rest = Math.abs(signed) - closing;
    if (qty === 0) avg = 0;
    if (rest > 0) {
      qty = Math.sign(signed) * rest;
      avg = f.price;
    }
  } else {
    avg = (avg * Math.abs(qty) + f.price * Math.abs(signed)) / (Math.abs(qty) + Math.abs(signed));
    qty += signed;
  }
  return { ...b, qty, avg, realized, fills: [...b.fills, f] };
}

/** Bar `i` was just revealed: every pending order fills at its open. */
export function onReveal(b: Book, bars: BarData, i: number): Book {
  if (!b.pending.length || i >= bars.t.length || !Number.isFinite(bars.o[i])) return b;
  let out: Book = { ...b, pending: [] };
  for (const p of b.pending) out = apply(out, { t: bars.t[i], side: p.side, qty: p.qty, price: bars.o[i] });
  return out;
}

/** Open P&L at `price`. */
export const unrealized = (b: Book, price: number) => (b.qty ? b.qty * (price - b.avg) : 0);

/** The session's fills as the journal's GENERIC CSV (columns mapped one to one when importing). */
export function fillsCsv(symbol: string, fills: Fill[]): string {
  const rows = fills.map((f) => `${new Date(f.t * 1000).toISOString().slice(0, 19).replace("T", " ")},${symbol},${f.side},${f.qty},${f.price}`);
  return ["time,symbol,side,qty,price", ...rows].join("\n");
}
