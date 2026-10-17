/** Return math for HIST and COMP (pure, unit-tested). Percentages, e.g. 12.5 = +12.5 %. */

export interface BarsLike {
  t: number[];
  o: (number | null)[];
  h: (number | null)[];
  l: (number | null)[];
  c: (number | null)[];
  v: (number | null)[];
  /** Adjusted close, when the source has it. */
  adj?: (number | null)[] | null;
}

export const pctChange = (from: number | null | undefined, to: number | null | undefined): number | null =>
  from == null || to == null || !Number.isFinite(from) || !Number.isFinite(to) || from === 0 ? null : (to / from - 1) * 100;

/**
 * Return over a calendar lookback ending at the last bar: last close vs the close of the last bar at or before
 * (last time - days). Null when the history does not reach that far back. Uses adjusted closes when present
 * so dividends and splits do not show up as losses.
 */
export function periodReturn(b: Pick<BarsLike, "t" | "c" | "adj">, days: number): number | null {
  const c = b.adj && b.adj.length === b.t.length ? b.adj : b.c;
  let last = -1;
  for (let i = b.t.length - 1; i >= 0; i--)
    if (c[i] != null) {
      last = i;
      break;
    }
  if (last < 0) return null;
  const cutoff = b.t[last] - days * 86400;
  if (b.t[0] > cutoff) return null; // history too short (allow a bar exactly at the cutoff)
  for (let i = last - 1; i >= 0; i--) if (b.t[i] <= cutoff && c[i] != null) return pctChange(c[i], c[last]);
  return null;
}

export interface HistRow {
  t: number;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  adj: number | null;
  volume: number | null;
  /** Close vs the previous bar's close; null for the oldest bar. */
  changePct: number | null;
}

/** Newest first, with change % against the previous (older) bar. Bars without a close are dropped. */
export function histRows(b: BarsLike): HistRow[] {
  const out: HistRow[] = [];
  let prev: number | null = null;
  for (let i = 0; i < b.t.length; i++) {
    const close = b.c[i];
    if (close == null) continue;
    out.push({
      t: b.t[i], open: b.o[i], high: b.h[i], low: b.l[i], close,
      adj: b.adj && b.adj.length === b.t.length ? b.adj[i] : null,
      volume: b.v[i], changePct: pctChange(prev, close),
    });
    prev = close;
  }
  return out.reverse();
}

/** Args "[range] [D|W|MO]" in any order, e.g. ["W", "5Y"]. Unknown tokens are reported, not guessed. */
export function histArgs(args: string[]): { range: string; interval: string; bad: string[] } {
  let range = "1Y";
  let interval = "D";
  const bad: string[] = [];
  for (const a of args.map((x) => x.toUpperCase()).filter(Boolean)) {
    if (/^(1D|5D|1M|3M|6M|YTD|1Y|2Y|5Y|10Y|MAX)$/.test(a)) range = a;
    else if (/^(D|DAILY|W|WEEKLY|MO|MONTHLY)$/.test(a)) interval = a[0] === "D" ? "D" : a[0] === "W" ? "W" : "MO";
    else bad.push(a);
  }
  return { range, interval, bad };
}
