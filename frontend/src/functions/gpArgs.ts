/**
 * GP command arguments (pure, so vitest can run it): [range] [interval] [VS SYM...] [PANE] [EVT] [CANDLE|OHLC|LINE|AREA] [LOG] [studies...].
 * Order is free. `VS` takes up to three symbols; with `PANE` each gets its own pane, without it the first one is overlaid (rebased to %).
 */
import { CHART_TYPES, type ChartType } from "../chart/chartTypes";
import { INDICATORS, type IndicatorName } from "../chart/indicators";

export const RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"];
/** Number keys 1..8 jump to these. */
export const KEY_RANGES = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"];
const INTERVAL_WORDS = new Set(["1MIN", "2MIN", "5MIN", "15MIN", "30MIN", "60MIN", "90MIN", "1H", "D", "1D", "DAILY", "W", "1W", "1WK", "WEEKLY", "MO", "1MO", "MONTHLY"]);
const YAHOO_INTERVALS = new Set(["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1d", "1wk", "1mo"]);
export const MAX_COMPARE = 3;

export interface GpParsed {
  range: string;
  interval?: string;
  /** Compare symbols (uppercase), at most MAX_COMPARE. */
  compare: string[];
  pane: boolean;
  evt: boolean;
  type: ChartType;
  log: boolean;
  indicators: IndicatorName[];
}

function isKeyword(raw: string): boolean {
  const a = raw.toUpperCase();
  return (
    a === "VS" || a === "PANE" || a === "EVT" || a === "LOG" || a === "PAT:ICHI" || RANGES.includes(a) || YAHOO_INTERVALS.has(raw) || INTERVAL_WORDS.has(a) ||
    (CHART_TYPES as string[]).includes(a) || (INDICATORS as readonly string[]).includes(a)
  );
}

/** `defaults`: the SETTINGS default range and chart type (Phase 10). */
export function parseGpArgs(args: string[], defaults: { range: string; type: ChartType } = { range: "1Y", type: "CANDLE" }): GpParsed {
  const p: GpParsed = { range: defaults.range, type: defaults.type, log: false, compare: [], pane: false, evt: false, indicators: [] };
  for (let i = 0; i < args.length; i++) {
    const raw = args[i];
    const a = raw.toUpperCase();
    if (a === "VS" && args[i + 1]) {
      i++;
      p.compare.push(args[i].toUpperCase());
      while (p.compare.length < MAX_COMPARE && args[i + 1] && !isKeyword(args[i + 1])) p.compare.push(args[++i].toUpperCase());
    } else if (a === "PANE") p.pane = true;
    else if (a === "EVT") p.evt = true;
    else if (RANGES.includes(a)) p.range = a;
    else if (YAHOO_INTERVALS.has(raw) || INTERVAL_WORDS.has(a)) p.interval = raw;
    else if ((CHART_TYPES as string[]).includes(a)) p.type = a as ChartType;
    else if (a === "LOG") p.log = true;
    else if (a === "PAT:ICHI" && !p.indicators.includes("ICHIMOKU")) p.indicators.push("ICHIMOKU");
    else if ((INDICATORS as readonly string[]).includes(a) && !p.indicators.includes(a as IndicatorName)) p.indicators.push(a as IndicatorName);
  }
  p.compare = [...new Set(p.compare)];
  return p;
}

export function serializeGp(p: GpParsed, defaultType: ChartType = "CANDLE"): string[] {
  return [
    p.range,
    ...(p.interval ? [p.interval] : []),
    ...(p.compare.length ? ["VS", ...p.compare] : []),
    ...(p.pane ? ["PANE"] : []),
    ...(p.evt ? ["EVT"] : []),
    ...(p.type !== defaultType ? [p.type] : []),
    ...(p.log ? ["LOG"] : []),
    ...p.indicators,
  ];
}
