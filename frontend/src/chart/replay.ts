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
 *
 * Stop and target exits (`GP ... REPLAY STOP=5 TARGET=10`, percent from the average entry price) follow the SAME rule as
 * BT's exits (backend/openterm/bt/stops.py `decide`, ported below): a bar that opened beyond a level exits at its open; a bar
 * that reached one level exits at that level; a bar that reached BOTH is settled by finer bars when the caller has them
 * (a daily replay can load 60-minute bars), else the stop counts first and the book's `stats` says so. Paper only.
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
  /** Set when a stop or target closed the position (absent for orders you queued). */
  why?: "STOP" | "TARGET";
}

/** How the exits were decided so far (the same four words as the backtester's EXITS line). */
export interface ExitStats { gap: number; single: number; intrabar: number; stop_first: number }

export interface Book {
  qty: number; // signed position: + long, - short
  avg: number; // average entry price of the open position (0 when flat)
  realized: number;
  fills: Fill[];
  pending: { side: "BUY" | "SELL"; qty: number }[]; // waiting for the next bar's open
  stats: ExitStats;
}

export const emptyBook = (): Book => ({ qty: 0, avg: 0, realized: 0, fills: [], pending: [], stats: { gap: 0, single: 0, intrabar: 0, stop_first: 0 } });

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

// --- stop and target exits (the backtester's rule, ported from backend/openterm/bt/stops.py) --------------------------------
/** Percent distances from the average entry price; absent = no such exit. */
export interface Exits { stop?: number; target?: number }

/** Stop and target prices of a position (a short's stop is ABOVE its entry). `direction` is +1 long, -1 short. */
export function exitLevels(entry: number, direction: number, ex: Exits): [number | null, number | null] {
  return [ex.stop ? entry * (1 - (direction * ex.stop) / 100) : null, ex.target ? entry * (1 + (direction * ex.target) / 100) : null];
}

function reached(direction: number, high: number, low: number, stop: number | null, target: number | null): [boolean, boolean] {
  if (direction > 0) return [stop !== null && low <= stop, target !== null && high >= target];
  return [stop !== null && high >= stop, target !== null && low <= target];
}

export type ExitHow = keyof ExitStats;

/**
 * Did this bar exit the position? `intraday` = the bar's finer (high, low) pairs in time order, or null.
 * -> [reason, exit price, how it was decided] or null. Same four outcomes as `stops.decide`: "gap" (opened beyond a level: exit at
 * the open), "single" (one level reached), "intrabar" (both, settled by the finer bars), "stop_first" (both, no answer: the stop).
 */
export function decideExit(direction: number, o: number, h: number, l: number, stop: number | null, target: number | null, intraday: [number, number][] | null): ["STOP" | "TARGET", number, ExitHow] | null {
  const [hitStop, hitTarget] = reached(direction, h, l, stop, target);
  if (!hitStop && !hitTarget) return null;
  const [gapStop, gapTarget] = reached(direction, o, o, stop, target);
  if (gapStop) return ["STOP", o, "gap"];
  if (gapTarget) return ["TARGET", o, "gap"];
  if (hitStop && !hitTarget) return ["STOP", stop as number, "single"];
  if (hitTarget && !hitStop) return ["TARGET", target as number, "single"];
  for (const [ih, il] of intraday ?? []) {
    const [s, t] = reached(direction, ih, il, stop, target);
    if (s && t) break; // one finer bar holds both: still ambiguous at this resolution
    if (s) return ["STOP", stop as number, "intrabar"];
    if (t) return ["TARGET", target as number, "intrabar"];
  }
  return ["STOP", stop as number, "stop_first"];
}

/** The finer bars (as [high, low]) that START inside [from, to), in time order. `t` must be ascending. */
export function finerBetween(t: ArrayLike<number>, h: ArrayLike<number | null>, l: ArrayLike<number | null>, from: number, to: number): [number, number][] {
  let lo = 0;
  let hi = t.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (t[mid] < from) lo = mid + 1;
    else hi = mid;
  }
  const out: [number, number][] = [];
  for (let k = lo; k < t.length && t[k] < to; k++) {
    const hk = h[k];
    const lk = l[k];
    if (hk !== null && lk !== null && Number.isFinite(hk) && Number.isFinite(lk)) out.push([hk, lk]);
  }
  return out;
}

/** Where finer bars can be looked up for a replayed bar: (start, end of that bar) -> its finer (high, low) bars, or null. */
export type FinerLookup = (from: number, to: number) => [number, number][] | null;

/**
 * Bar `i` was just revealed: every pending order fills at its open, then the open position's stop / target is checked on this
 * same bar (the backtester does the same: exits are decided after the bar's fills). `finer` settles a bar that reached both.
 */
export function onReveal(b: Book, bars: BarData, i: number, ex?: Exits, finer?: FinerLookup): Book {
  if (i >= bars.t.length || !Number.isFinite(bars.o[i])) return b;
  let out: Book = b;
  if (b.pending.length) {
    out = { ...b, pending: [] };
    for (const p of b.pending) out = apply(out, { t: bars.t[i], side: p.side, qty: p.qty, price: bars.o[i] });
  }
  if (!ex || (!ex.stop && !ex.target) || out.qty === 0) return out;
  const dir = Math.sign(out.qty);
  const [stop, target] = exitLevels(out.avg, dir, ex);
  // The bar's end: the next bar's start, or one more bar-length when it is the last one.
  const end = i + 1 < bars.t.length ? bars.t[i + 1] : bars.t[i] + (i > 0 ? bars.t[i] - bars.t[i - 1] : 86_400);
  const hit = decideExit(dir, bars.o[i], bars.h[i], bars.l[i], stop, target, finer ? finer(bars.t[i], end) : null);
  if (!hit) return out;
  const [why, price, how] = hit;
  const closed = apply(out, { t: bars.t[i], side: dir > 0 ? "SELL" : "BUY", qty: Math.abs(out.qty), price, why });
  return { ...closed, stats: { ...closed.stats, [how]: closed.stats[how] + 1 } };
}

/** Open P&L at `price`. */
export const unrealized = (b: Book, price: number) => (b.qty ? b.qty * (price - b.avg) : 0);

/** The session's fills as the journal's GENERIC CSV (columns mapped one to one when importing). */
export function fillsCsv(symbol: string, fills: Fill[]): string {
  const rows = fills.map((f) => `${new Date(f.t * 1000).toISOString().slice(0, 19).replace("T", " ")},${symbol},${f.side},${f.qty},${f.price}`);
  return ["time,symbol,side,qty,price", ...rows].join("\n");
}
