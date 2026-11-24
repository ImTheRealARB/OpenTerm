/**
 * Phase 23: anchored VWAP with standard-deviation bands. Pure (runs in the indicators worker; vitest covers it).
 *
 * VWAP = sum(typical price x volume) / sum(volume) since the anchor, where typical price = (high + low + close) / 3.
 * The bands are VWAP +- k x sigma, with sigma the VOLUME-WEIGHTED standard deviation of the typical price since the same
 * anchor: sigma^2 = sum(v x tp^2) / sum(v) - VWAP^2. That is the usual construction, so a bar with a lot of volume pulls
 * both the line and the band width more than a quiet bar.
 *
 * Where the sum restarts ("the anchor"):
 *   SESSION  a gap of more than 4 hours between two bars (a new trading day), like the plain VWAP study
 *   WEEK     a new ISO week (UTC)
 *   MONTH    a new calendar month (UTC)
 *   ANCHOR   once, at the first bar at or after a chosen time (bars before it get no value)
 */
export type AvwapReset = "SESSION" | "WEEK" | "MONTH" | "ANCHOR";

export interface AvwapBands {
  mid: Float64Array;
  up1: Float64Array;
  lo1: Float64Array;
  up2: Float64Array;
  lo2: Float64Array;
  up3: Float64Array;
  lo3: Float64Array;
}

const SESSION_GAP_S = 4 * 3600;

/** Monday 00:00 UTC of the week holding `t` (epoch seconds), as a whole-week number. 1970-01-01 was a Thursday, hence +3 days. */
const weekOf = (t: number) => Math.floor((t / 86_400 + 3) / 7);
const monthOf = (t: number) => {
  const d = new Date(t * 1000);
  return d.getUTCFullYear() * 12 + d.getUTCMonth();
};

/** True when bar `i` starts a new sum. */
function restarts(t: Float64Array, i: number, reset: AvwapReset, anchorT: number): boolean {
  if (reset === "ANCHOR") return t[i] >= anchorT && (i === 0 || t[i - 1] < anchorT);
  if (i === 0) return true;
  if (reset === "SESSION") return t[i] - t[i - 1] > SESSION_GAP_S;
  if (reset === "WEEK") return weekOf(t[i]) !== weekOf(t[i - 1]);
  return monthOf(t[i]) !== monthOf(t[i - 1]);
}

export function avwap(t: Float64Array, h: Float64Array, l: Float64Array, c: Float64Array, v: Float64Array, reset: AvwapReset, anchorT = 0): AvwapBands {
  const n = c.length;
  const mk = () => new Float64Array(n).fill(NaN);
  const out: AvwapBands = { mid: mk(), up1: mk(), lo1: mk(), up2: mk(), lo2: mk(), up3: mk(), lo3: mk() };
  let sv = 0; // sum of volume
  let spv = 0; // sum of tp x volume
  let sp2v = 0; // sum of tp^2 x volume
  let on = reset !== "ANCHOR"; // with an anchor, nothing is drawn before it
  for (let i = 0; i < n; i++) {
    if (restarts(t, i, reset, anchorT)) {
      sv = spv = sp2v = 0;
      on = true;
    }
    if (!on) continue;
    const vol = Number.isFinite(v[i]) ? v[i] : 0; // a missing volume counts as 0, like the plain VWAP
    const tp = (h[i] + l[i] + c[i]) / 3;
    if (!Number.isFinite(tp)) continue;
    sv += vol;
    spv += tp * vol;
    sp2v += tp * tp * vol;
    if (sv <= 0) continue;
    const m = spv / sv;
    // Rounding can make the variance a tiny negative number when every price is equal: clamp it to 0.
    const sd = Math.sqrt(Math.max(0, sp2v / sv - m * m));
    out.mid[i] = m;
    out.up1[i] = m + sd;
    out.lo1[i] = m - sd;
    out.up2[i] = m + 2 * sd;
    out.lo2[i] = m - 2 * sd;
    out.up3[i] = m + 3 * sd;
    out.lo3[i] = m - 3 * sd;
  }
  return out;
}
