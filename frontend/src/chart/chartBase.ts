/**
 * Small pieces shared by ChartView (the plain price chart) and gpLayer (the GP-only extras).
 * They live here so the two files never import each other's values (that would be a circular import).
 */
import type { UTCTimestamp } from "lightweight-charts";

/** Bars as parallel typed arrays (cheap to hand to the indicator worker). */
export interface BarData {
  symbol: string;
  interval: string;
  tz: string;
  t: Float64Array; // epoch seconds
  o: Float64Array;
  h: Float64Array;
  l: Float64Array;
  c: Float64Array;
  v: Float64Array;
}

/** lightweight-charts wants a branded timestamp type; this is only a type cast. */
export const toTime = (s: number) => s as UTCTimestamp;

/** Chart colours read from the CSS variables (once per theme change, never per frame). */
export function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), line: v("--line"), acc: v("--accent"), warn: v("--warn"), sel: v("--sel"), val: v("--val") || v("--fg"), bar: v("--bar") || v("--sel"), grid: v("--chart-grid") || v("--bar") || v("--line"), cup: v("--chart-up") || v("--up"), cdown: v("--chart-down") || v("--down"), cline: v("--chart-line") || v("--val") || v("--fg"), font: v("--font"), fs: Math.round(parseFloat(v("--fs")) - 1) || 11 };
}
export type ThemeColors = ReturnType<typeof themeColors>;
