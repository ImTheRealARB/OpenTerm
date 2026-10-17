/**
 * BT MC / BT WF display helpers (pure: vitest covers them). A text histogram of the shuffled Sharpe ratios with the
 * actual value marked, and the plain-words definitions shown next to the numbers.
 */

export interface HistRow {
  lo: number;
  hi: number;
  count: number;
  /** Bar length 0..width, scaled to the fullest bin. */
  bar: number;
  /** The actual (unshuffled) value falls in this bin. */
  actual: boolean;
}

/**
 * `bins` equal-width bins over the sample range, widened to include `actual`. The top bin is closed on the right.
 * No samples (or a non-finite sample) gives no rows: nothing is drawn rather than something invented.
 */
export function histogram(samples: number[], bins: number, actual: number | null | undefined, width = 40): HistRow[] {
  const xs = samples.filter((x) => Number.isFinite(x));
  if (!xs.length || bins < 1) return [];
  const a = actual != null && Number.isFinite(actual) ? actual : null;
  let lo = Math.min(...xs, a ?? Infinity);
  let hi = Math.max(...xs, a ?? -Infinity);
  if (hi === lo) {
    lo -= 0.5;
    hi += 0.5;
  }
  const step = (hi - lo) / bins;
  const at = (v: number) => Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / step)));
  const counts = new Array<number>(bins).fill(0);
  for (const x of xs) counts[at(x)]++;
  const most = Math.max(...counts);
  const actualBin = a == null ? -1 : at(a);
  return counts.map((count, i) => ({
    lo: lo + i * step,
    hi: lo + (i + 1) * step,
    count,
    bar: most ? Math.round((count / most) * width) : 0,
    actual: i === actualBin,
  }));
}

/** A p-value as the share it is: 0.041 -> "4.1%". */
export const fmtP = (p: number | null | undefined): string => (p == null || !Number.isFinite(p) ? "—" : `${(p * 100).toFixed(1)}%`);

export const MC_NOTE =
  "SHUFFLING THE ORDER OF THE SAME TRADES TESTS PATH LUCK (SEQUENCE AND DRAWDOWN), NOT WHETHER THE RULE HAS AN EDGE";
