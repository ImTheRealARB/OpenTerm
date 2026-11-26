/**
 * GP CONE (Phase 28, pure, unit-tested): where the probability cone's points sit on the chart.
 *
 * The server sends, per listed expiry, the 1 and 2 standard-deviation price range from that expiry's ATM IV. Expiries are in the
 * future, past the last bar, so their x is a LOGICAL index (bar count) beyond the last bar: for daily or longer bars it counts
 * weekdays (the chart has no weekend bars), divided by the bar's length in days; intraday bars extrapolate by time.
 */
export interface ConePoint {
  time: number; // expiry, epoch seconds
  lo1: number;
  hi1: number;
  lo2: number;
  hi2: number;
}

/** One vertex of the cone: x as a logical bar index, then the four prices. The first vertex is the last bar at its close. */
export interface ConeVertex {
  x: number;
  lo1: number;
  hi1: number;
  lo2: number;
  hi2: number;
}

const DAY = 86400;

/** Weekdays strictly after `from` up to and including `to` (both epoch seconds, UTC days). */
export function weekdaysBetween(from: number, to: number): number {
  let n = 0;
  for (let d = Math.floor(from / DAY) + 1; d <= Math.floor(to / DAY); d++) {
    const wd = new Date(d * DAY * 1000).getUTCDay();
    if (wd !== 0 && wd !== 6) n++;
  }
  return n;
}

export function coneVertices(points: ConePoint[], t: ArrayLike<number>, lastClose: number): ConeVertex[] {
  const n = t.length;
  if (n < 2 || !points.length) return [];
  const last = t[n - 1];
  const step = t[n - 1] - t[n - 2];
  const daysPerBar = Math.max(1, Math.round(step / DAY));
  const out: ConeVertex[] = [{ x: n - 1, lo1: lastClose, hi1: lastClose, lo2: lastClose, hi2: lastClose }];
  for (const p of [...points].sort((a, b) => a.time - b.time)) {
    if (p.time <= last) continue;
    const ahead = step >= DAY * 0.9 ? weekdaysBetween(last, p.time) / (daysPerBar === 7 ? 5 : daysPerBar) : (p.time - last) / step;
    out.push({ x: n - 1 + ahead, lo1: p.lo1, hi1: p.hi1, lo2: p.lo2, hi2: p.hi2 });
  }
  return out.length > 1 ? out : [];
}
