/**
 * Phase 23: TPO / market profile (time price opportunity), the pure part.
 *
 * For each trading day, time is cut into brackets (30 minutes by default) and each bracket gets a letter: A for the first,
 * B for the second ... A price row gets the bracket's letter when the bracket's high-low range touches it. Reading down a
 * day's column then shows WHERE the market spent its time. Built from the bars' high and low per bracket, which is the
 * standard construction (exact for the bars used; the panel names their candle length).
 *
 *   POC            the price row with the most letters (ties: the one nearest the middle of the day's range)
 *   value area     rows around the POC holding 70% of all letters (same growth rule as the volume profile)
 *   initial balance (IB) the range of the first two brackets (A and B)
 *   single prints  rows inside the day's range touched by exactly one bracket, away from the day's high and low
 *   poor high/low  the day's top (bottom) row was touched by two or more brackets: an unfinished auction, often revisited
 */
export interface TpoDay {
  day: string; // YYYY-MM-DD (exchange-local when the bars say their zone, else UTC)
  lo: number; // price of row 0
  step: number; // row height (the tick size used)
  rows: string[]; // letters per row, bottom row first, e.g. "ABCF"
  poc: number;
  vaLo: number;
  vaHi: number;
  ibLo: number; // price
  ibHi: number; // price
  singles: number[]; // row indexes
  poorHigh: boolean;
  poorLow: boolean;
  brackets: number;
}

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

/** A row height that gives ~`rows` rows for this price range, rounded to 1, 2 or 5 x a power of ten (readable prices). */
export function niceStep(range: number, rows = 40): number {
  if (!(range > 0)) return 1;
  const raw = range / rows;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

/**
 * Bars (epoch seconds, highs, lows) of ONE day -> its profile. `bracketS` is the bracket length in seconds; the first bar
 * opens bracket A. `step` is the row height (use the same for every day so the columns line up).
 */
export function tpoDay(day: string, t: number[], h: number[], l: number[], bracketS: number, step: number, vaPct = 0.7): TpoDay | null {
  if (!t.length) return null;
  const t0 = t[0];
  // Bracket index -> its high and low.
  const bh: number[] = [];
  const bl: number[] = [];
  for (let i = 0; i < t.length; i++) {
    if (!Number.isFinite(h[i]) || !Number.isFinite(l[i])) continue;
    const b = Math.floor((t[i] - t0) / bracketS);
    bh[b] = bh[b] === undefined ? h[i] : Math.max(bh[b], h[i]);
    bl[b] = bl[b] === undefined ? l[i] : Math.min(bl[b], l[i]);
  }
  const used = bh.map((_, i) => i).filter((i) => bh[i] !== undefined);
  if (!used.length) return null;
  const dayLo = Math.min(...used.map((i) => bl[i]));
  const dayHi = Math.max(...used.map((i) => bh[i]));
  const lo = Math.floor(dayLo / step) * step;
  const n = Math.floor((dayHi - lo) / step) + 1;
  const rows: string[] = new Array(n).fill("");
  const count = new Array<number>(n).fill(0);
  for (const b of used) {
    const letter = LETTERS[b % LETTERS.length];
    const a = Math.floor((bl[b] - lo) / step);
    const z = Math.floor((bh[b] - lo) / step);
    for (let r = Math.max(0, a); r <= Math.min(n - 1, z); r++) {
      rows[r] += letter;
      count[r]++;
    }
  }
  const total = count.reduce((a, b) => a + b, 0);
  const mid = (n - 1) / 2;
  let poc = 0;
  for (let r = 1; r < n; r++) if (count[r] > count[poc] || (count[r] === count[poc] && Math.abs(r - mid) < Math.abs(poc - mid))) poc = r;
  let vaLo = poc;
  let vaHi = poc;
  let inVa = count[poc];
  while (inVa < total * vaPct && (vaLo > 0 || vaHi < n - 1)) {
    const below = vaLo > 0 ? count[vaLo - 1] : -1;
    const above = vaHi < n - 1 ? count[vaHi + 1] : -1;
    if (above >= below) inVa += count[++vaHi];
    else inVa += count[--vaLo];
  }
  const ib = used.filter((b) => b < 2);
  const singles: number[] = [];
  for (let r = 1; r < n - 1; r++) if (count[r] === 1) singles.push(r);
  return {
    day, lo, step, rows, poc, vaLo, vaHi,
    ibLo: Math.min(...ib.map((b) => bl[b])), ibHi: Math.max(...ib.map((b) => bh[b])),
    singles, poorHigh: count[n - 1] >= 2, poorLow: count[0] >= 2, brackets: used.length,
  };
}

export const TPO_USAGE = "USAGE: TPO [SYM] [DAYS 1-20] [BRACKET=30]  E.G. TPO AAPL 5 BRACKET=30";

/** Pure: the panel's arguments. A word that is not a number or BRACKET= is the symbol (overrides the panel's security). */
export function parseTpoArgs(args: string[], sticky?: string): { symbol: string; days: number; bracket: number; error: string | null } {
  let days = 5;
  let bracket = 30;
  let symbol = sticky?.toUpperCase() ?? "";
  for (const raw of args) {
    const a = raw.toUpperCase();
    const b = /^BRACKET=(\d+)$/.exec(a);
    if (b) bracket = Number(b[1]);
    else if (/^\d+$/.test(a)) days = Number(a);
    else symbol = a;
  }
  const error = !symbol ? TPO_USAGE : days < 1 || days > 20 ? "DAYS MUST BE 1 TO 20" : bracket < 5 || bracket > 240 || bracket % 5 ? "BRACKET MUST BE 5 TO 240 MINUTES, A MULTIPLE OF 5" : null;
  return { symbol, days, bracket, error };
}
