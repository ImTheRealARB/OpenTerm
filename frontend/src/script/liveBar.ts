/**
 * The pure parts of live script alerts (`liveAlerts.ts`): turning history rows into columns, turning live prices into the
 * newest daily bar, and choosing which messages to fire. No DOM, no network: unit-tested in `liveBar.test.ts`.
 */
import type { Bar, BarCols } from "./index";

/** One day in seconds. Live script alerts run on DAILY bars (chart timeframe 1D). */
export const DAY = 86400;

/** The history answer's columns: `null` = a missing value. */
export interface HistoryCols {
  t: readonly number[];
  o: readonly (number | null)[];
  h: readonly (number | null)[];
  l: readonly (number | null)[];
  c: readonly (number | null)[];
  v: readonly (number | null)[];
}

/**
 * History rows to script columns. A row with a missing open, high, low, close or time is dropped (the script cannot run on a
 * hole); a missing volume counts as 0. Returns null when nothing is left.
 */
export function toCols(h: HistoryCols): BarCols | null {
  const o: number[] = [], hi: number[] = [], l: number[] = [], c: number[] = [], v: number[] = [], t: number[] = [];
  for (let i = 0; i < h.t.length; i++) {
    const [oo, hh, ll, cc] = [h.o[i], h.h[i], h.l[i], h.c[i]];
    if (oo == null || hh == null || ll == null || cc == null || !Number.isFinite(h.t[i])) continue;
    o.push(oo);
    hi.push(hh);
    l.push(ll);
    c.push(cc);
    v.push(h.v[i] ?? 0);
    t.push(h.t[i]);
  }
  return t.length ? { o, h: hi, l, c, v, t } : null;
}

/** The newest bar the run holds (all fields known). */
export type LastBar = Required<Bar>;

/** Prices that arrived since the last run, folded into four numbers: the first, the highest, the lowest and the latest. */
export interface Fold {
  first: number;
  hi: number;
  lo: number;
  last: number;
}

/** Start a fold with one price. */
export const foldOf = (price: number): Fold => ({ first: price, hi: price, lo: price, last: price });
/** Add a price to a fold. */
export function addPrice(f: Fold, price: number): Fold {
  return { first: f.first, hi: Math.max(f.hi, price), lo: Math.min(f.lo, price), last: price };
}

/**
 * What the newest bar becomes after `fold` at time `nowSec` (epoch seconds).
 * Rule: a price belongs to the newest bar until a whole day has passed since that bar OPENED; then a new bar opens at the
 * bar's open time plus a whole number of days (so a Monday tick after a Friday bar opens at the same time of day, whatever
 * the exchange's session hours are). Inside the day, the bar's open and volume stay, its high / low widen, its close is the
 * latest price. Ticks carry no volume: a new bar starts at volume 0.
 */
export function applyFold(last: LastBar, fold: Fold, nowSec: number): { append: boolean; bar: LastBar } {
  if (nowSec >= last.t + DAY) {
    const t = last.t + Math.floor((nowSec - last.t) / DAY) * DAY;
    return { append: true, bar: { t, o: fold.first, h: fold.hi, l: fold.lo, c: fold.last, v: 0 } };
  }
  return { append: false, bar: { t: last.t, o: last.o, h: Math.max(last.h, fold.hi), l: Math.min(last.l, fold.lo), c: fold.last, v: last.v } };
}

/** What a live tick says about alerts (a subset of the engine's `ScriptTick`). */
export interface TickAlerts {
  alerts: readonly { bar: number; message: string }[];
  conditions: readonly number[];
}

/**
 * The messages to fire for one alert on the newest bar.
 * `cond` null = the script's own `alert(...)` calls on the newest bar. A title = that `alertcondition` when it is 1 on the
 * newest bar (its message, else its title). A title the script no longer has gives nothing: the runner checks titles when it starts.
 */
export function messagesToFire(tick: TickAlerts, conds: readonly { title: string; message: string }[], cond: string | null): string[] {
  if (cond === null) return tick.alerts.map((a) => a.message);
  const i = conds.findIndex((c) => c.title === cond);
  return i >= 0 && tick.conditions[i] === 1 ? [conds[i].message || conds[i].title] : [];
}

/** The condition whose title equals `want` ignoring case and outer spaces (the user types it), or null. */
export function findCondition(conds: readonly { title: string }[], want: string): string | null {
  const w = want.trim().toLowerCase();
  return conds.find((c) => c.title.trim().toLowerCase() === w)?.title ?? null;
}

/** `NO CONDITION "X" IN NAME (HAS: A, B)`: the error for a condition the script does not have. */
export function noConditionText(want: string, script: string, conds: readonly { title: string }[]): string {
  return `NO CONDITION "${want}" IN ${script} (HAS: ${conds.length ? conds.map((c) => c.title).join(", ") : "NONE"})`;
}

/** The key of an alert message on a bar, for "already true when the run started" bookkeeping. */
export const seedKey = (barTime: number, message: string): string => `${barTime}|${message}`;

/** The first compile error as one screen line: `SCRIPT NAME DOES NOT COMPILE: LINE 3:5 EXPECTED )`. */
export function compileErrorText(script: string, e: { msg: string; line: number; col: number }): string {
  return `SCRIPT ${script} DOES NOT COMPILE: LINE ${e.line}:${e.col} ${e.msg}`;
}

/** A run error as one screen line (spec 1.7): `SCRIPT ERROR AT BAR 12: DIVISION BY ZERO (LINE 4)`. */
export function runErrorText(e: { msg: string; line: number; bar?: number }): string {
  return `SCRIPT ERROR${e.bar === undefined ? "" : ` AT BAR ${e.bar}`}: ${e.msg} (LINE ${e.line})`;
}

/** The wording of the history request for a `request(...)` timeframe, or null when live alerts cannot fetch it. */
export function requestRange(timeframe: string): { range: string; interval: string } | null {
  switch (timeframe) {
    case "1D":
      return { range: "1Y", interval: "1d" };
    case "1W":
      return { range: "5Y", interval: "1wk" };
    case "1M":
      return { range: "10Y", interval: "1mo" };
    default:
      return null;
  }
}
