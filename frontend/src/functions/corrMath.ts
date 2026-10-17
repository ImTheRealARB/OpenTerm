/**
 * CORR math (pure, unit-tested): align daily closes by exchange-local date, keep only dates every
 * symbol traded, take log returns between consecutive common dates, then a Pearson correlation matrix.
 *
 * Cost: 20 symbols x 5 years (about 1,250 returns) is 190 pairs x 1,250 = 0.24 M multiply-adds, well under
 * 1 ms in V8, so it runs on the main thread (measured in corr.test.ts; see PHASE_9_NOTES.md).
 */

export interface CloseSeries {
  symbol: string;
  /** Bar times, epoch seconds. */
  t: number[];
  /** Closes (adjusted when the source has them); nulls are skipped. */
  c: (number | null)[];
  /** Exchange time zone, used to turn bar times into trading dates. */
  tz?: string | null;
}

const fmts = new Map<string, Intl.DateTimeFormat>();
// Intl formatting costs ~2 us a call; symbols on one exchange share bar times, so cache per zone + time.
const keys = new Map<string, string>();

/** Trading date "YYYY-MM-DD" of a bar in its exchange's time zone (UTC when unknown or invalid). */
export function dayKey(t: number, tz?: string | null): string {
  const zone = tz || "UTC";
  const ck = `${zone}|${t}`;
  const hit = keys.get(ck);
  if (hit !== undefined) return hit;
  if (keys.size > 200_000) keys.clear();
  const key = formatter(zone).format(new Date(t * 1000));
  keys.set(ck, key);
  return key;
}

function formatter(zone: string): Intl.DateTimeFormat {
  let f = fmts.get(zone);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" });
    } catch {
      f = new Intl.DateTimeFormat("en-CA", { timeZone: "UTC", year: "numeric", month: "2-digit", day: "2-digit" });
    }
    fmts.set(zone, f);
  }
  return f;
}

export interface Aligned {
  dates: string[];
  /** closes[k][i]: close of series k on dates[i]. */
  closes: number[][];
}

/** Dates on which every series has a positive close, in ascending order. */
export function alignCloses(series: CloseSeries[]): Aligned {
  if (!series.length) return { dates: [], closes: [] };
  const maps = series.map((s) => {
    const m = new Map<string, number>();
    for (let i = 0; i < s.t.length; i++) {
      const c = s.c[i];
      if (c != null && Number.isFinite(c) && c > 0) m.set(dayKey(s.t[i], s.tz), c); // last bar of a day wins
    }
    return m;
  });
  const dates = [...maps[0].keys()].filter((d) => maps.every((m) => m.has(d))).sort();
  return { dates, closes: maps.map((m) => dates.map((d) => m.get(d)!)) };
}

export function logReturns(closes: number[]): number[] {
  const out = new Array<number>(Math.max(0, closes.length - 1));
  for (let i = 1; i < closes.length; i++) out[i - 1] = Math.log(closes[i] / closes[i - 1]);
  return out;
}

/** Pearson correlation; NaN when either side is constant or there are fewer than 2 points. */
export function pearson(x: number[], y: number[]): number {
  const n = Math.min(x.length, y.length);
  if (n < 2) return NaN;
  let mx = 0;
  let my = 0;
  for (let i = 0; i < n; i++) {
    mx += x[i];
    my += y[i];
  }
  mx /= n;
  my /= n;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < n; i++) {
    const dx = x[i] - mx;
    const dy = y[i] - my;
    sxy += dx * dy;
    sxx += dx * dx;
    syy += dy * dy;
  }
  if (sxx === 0 || syy === 0) return NaN;
  return Math.max(-1, Math.min(1, sxy / Math.sqrt(sxx * syy)));
}

export interface CorrResult {
  symbols: string[];
  /** Symmetric matrix, 1 on the diagonal (NaN where undefined). */
  matrix: number[][];
  /** Trading dates common to every symbol. */
  overlap: number;
  /** Returns used per pair (overlap - 1). */
  returns: number;
  first: string | null;
  last: string | null;
}

export function correlationMatrix(series: CloseSeries[]): CorrResult {
  const { dates, closes } = alignCloses(series);
  const rets = closes.map(logReturns);
  const k = series.length;
  const matrix = Array.from({ length: k }, () => new Array<number>(k).fill(NaN));
  for (let a = 0; a < k; a++) {
    matrix[a][a] = rets[a].length >= 2 ? 1 : NaN;
    for (let b = a + 1; b < k; b++) matrix[a][b] = matrix[b][a] = pearson(rets[a], rets[b]);
  }
  return {
    symbols: series.map((s) => s.symbol),
    matrix,
    overlap: dates.length,
    returns: Math.max(0, dates.length - 1),
    first: dates[0] ?? null,
    last: dates[dates.length - 1] ?? null,
  };
}

export type CorrBand = "" | "z" | "p1" | "p2" | "p3" | "m1" | "m2" | "m3";

/**
 * Discrete heat step: |r| < 0.2 is "z" (no meaningful relation), then weak / moderate / strong
 * (0.2, 0.4, 0.7) positive "p1..p3" or negative "m1..m3". "" = undefined.
 */
export function corrBand(r: number): CorrBand {
  if (!Number.isFinite(r)) return "";
  const a = Math.abs(r);
  if (a < 0.2) return "z";
  const lvl = a >= 0.7 ? 3 : a >= 0.4 ? 2 : 1;
  return `${r > 0 ? "p" : "m"}${lvl}` as CorrBand;
}

const CORR_RANGES = new Set(["1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"]);
export const CORR_MAX_SYMBOLS = 20;

/** CORR args: symbols and one optional range (default 1Y) in any order. Returns de-duplicated upper-case symbols. */
export function parseCorrArgs(args: string[]): { symbols: string[]; range: string; error: string | null } {
  let range = "1Y";
  const symbols: string[] = [];
  for (const raw of args.flatMap((a) => a.split(",")).map((a) => a.trim().toUpperCase()).filter(Boolean)) {
    if (CORR_RANGES.has(raw)) range = raw;
    else if (!symbols.includes(raw)) symbols.push(raw);
  }
  const error =
    symbols.length < 2 ? "USAGE: CORR SYM SYM... [1M|3M|6M|YTD|1Y|2Y|5Y|10Y|MAX] (AT LEAST 2 SYMBOLS)"
    : symbols.length > CORR_MAX_SYMBOLS ? `AT MOST ${CORR_MAX_SYMBOLS} SYMBOLS` : null;
  return { symbols, range, error };
}
