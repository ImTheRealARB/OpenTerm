/**
 * Timeframe spelling between a chart and a script (pure). The chart speaks Yahoo intervals ("5m", "60m", "1d", "1wk"), the script
 * speaks its own ("5m", "1h", "1D", "1W"). The chart host (`chart/scriptLayer.ts`) uses these to
 *  - tell the engine the chart's timeframe (so `request` can refuse a SHORTER one),
 *  - fetch the bars a `request(SYMBOL, TF, expr)` needs from another symbol.
 */
import { normTimeframe } from "./resample";

/** Chart interval -> script timeframe. Intervals a script has no word for (2m, 90m, 3h, 2d ...) give undefined: the check is skipped. */
const CHART_TF: Readonly<Record<string, string>> = {
  "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "1h", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D", "1wk": "1W", "1mo": "1M",
};

export function scriptChartTf(interval: string): string | undefined {
  return CHART_TF[interval] ?? CHART_TF[interval.toLowerCase()];
}

/** Script timeframe ("1h", "60", "D") -> the history interval token the server knows, or undefined for a word it has no candle for. */
const HIST: Readonly<Record<string, string>> = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "2h": "2h", "4h": "4h", "1D": "1d", "1W": "1wk", "1M": "1mo" };

export function historyInterval(tf: string): string | undefined {
  const n = normTimeframe(tf);
  return n ? HIST[n] : undefined;
}

const ORDER = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"];
/** The least history a candle length needs to be useful: a daily request on a 1D chart still wants a year of days. */
const MIN_RANGE: Readonly<Record<string, string>> = { "1D": "1Y", "1W": "5Y", "1M": "10Y" };

/** The range to ask for a request series: the chart's own range, or more when the candle is long (never less). */
export function requestRange(tf: string, chartRange: string): string {
  const need = MIN_RANGE[normTimeframe(tf) ?? ""];
  if (!need) return chartRange;
  return ORDER.indexOf(chartRange.toUpperCase()) >= ORDER.indexOf(need) ? chartRange : need;
}
