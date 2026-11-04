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

/**
 * Library indicators and formulas live in the GP args as single tokens, so the command line, layouts (`replaceView` args) and
 * history all keep them with no extra view state:
 *   `ATR(14)` / `BB(20,2)` / `LIB:ATR:14` / `LIB:CMF`  library id with optional parameters (serialized as `ATR(14)`, or `LIB:CMF`)
 *   `F:<formula>`                                      a formula, percent-encoded when it has spaces (serialized encoded)
 * Chart keys: `LIB:ID:p1:p2` and `F:<encoded formula>`. The id is checked by the worker ("UNKNOWN INDICATOR X"), not here,
 * so this file stays free of the 109-indicator catalog (startup bundle).
 */
export interface CustomInd {
  key: string;
  /** What serializeGp writes back. */
  token: string;
  /** Short title for the chart series. */
  label: string;
  id?: string;
  params?: number[];
  formula?: string;
}
export const MAX_CUSTOM = 20;
const MAX_FORMULA = 500;

const FN_TOKEN = /^([A-Z][A-Z0-9_]*)\(([0-9.,\s-]*)\)$/i;
const LIB_TOKEN = /^LIB:([A-Z][A-Z0-9_]*)((?::-?[0-9.]+)*)$/i;

function nums(list: string[]): number[] | null {
  const out = list.filter((x) => x.trim() !== "").map(Number);
  return out.every((n) => Number.isFinite(n)) ? out : null;
}

export function libraryInd(id: string, params: number[]): CustomInd {
  const ID = id.toUpperCase();
  return {
    key: `LIB:${ID}${params.map((p) => `:${p}`).join("")}`,
    token: params.length ? `${ID}(${params.join(",")})` : `LIB:${ID}`,
    label: params.length ? `${ID}(${params.join(",")})` : ID,
    id: ID,
    params: params.length ? params : undefined,
  };
}

export function formulaInd(formula: string): CustomInd {
  const f = formula.trim();
  const enc = `F:${encodeURIComponent(f)}`;
  return { key: enc, token: enc, label: f.length > 24 ? `${f.slice(0, 24)}…` : f, formula: f };
}

/** One GP arg as a library / formula entry, or null when it is neither. */
export function parseCustomToken(raw: string): CustomInd | null {
  if (/^F:/i.test(raw)) {
    let f: string;
    try {
      f = decodeURIComponent(raw.slice(2));
    } catch {
      return null;
    }
    return f.trim() && f.length <= MAX_FORMULA ? formulaInd(f) : null;
  }
  let m = FN_TOKEN.exec(raw);
  if (m) {
    const ps = nums(m[2].split(","));
    return ps ? libraryInd(m[1], ps) : null;
  }
  m = LIB_TOKEN.exec(raw);
  if (m) {
    const ps = nums(m[2].split(":"));
    return ps ? libraryInd(m[1], ps) : null;
  }
  return null;
}

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
  /** Library indicators and formulas, in the order given (at most MAX_CUSTOM). */
  custom: CustomInd[];
}

function isKeyword(raw: string): boolean {
  const a = raw.toUpperCase();
  return (
    a === "VS" || a === "PANE" || a === "EVT" || a === "LOG" || a === "PAT:ICHI" || RANGES.includes(a) || YAHOO_INTERVALS.has(raw) || INTERVAL_WORDS.has(a) ||
    (CHART_TYPES as string[]).includes(a) || (INDICATORS as readonly string[]).includes(a) || parseCustomToken(raw) !== null
  );
}

/** `defaults`: the SETTINGS default range and chart type (Phase 10). */
export function parseGpArgs(args: string[], defaults: { range: string; type: ChartType } = { range: "1Y", type: "CANDLE" }): GpParsed {
  const p: GpParsed = { range: defaults.range, type: defaults.type, log: false, compare: [], pane: false, evt: false, indicators: [], custom: [] };
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
    else if ((INDICATORS as readonly string[]).includes(a)) {
      if (!p.indicators.includes(a as IndicatorName)) p.indicators.push(a as IndicatorName);
    } else {
      const c = parseCustomToken(raw);
      if (c && p.custom.length < MAX_CUSTOM && !p.custom.some((x) => x.key === c.key)) p.custom.push(c);
    }
  }
  p.compare = [...new Set(p.compare)];
  return p;
}

/** The candle lengths the GUI dropdown offers: [label, token]. An empty token means "Auto" (the range picks the interval). */
export const INTERVAL_CHOICES: readonly (readonly [string, string])[] = [
  ["Auto", ""], ["1 min", "1m"], ["5 min", "5m"], ["15 min", "15m"], ["30 min", "30m"], ["1 hour", "60m"], ["Daily", "1d"], ["Weekly", "1wk"], ["Monthly", "1mo"],
];

/** The args of a GP view with its candle length replaced ("" = back to Auto). Everything else (range, indicators...) is kept. */
export function withInterval(args: string[], interval: string, defaults: { range: string; type: ChartType }): string[] {
  return serializeGp({ ...parseGpArgs(args, defaults), interval: interval || undefined }, defaults.type);
}

/** The args of a GP view with its chart type replaced (candles, line, ...). Everything else is kept. */
export function withChartType(args: string[], type: ChartType, defaults: { range: string; type: ChartType }): string[] {
  return serializeGp({ ...parseGpArgs(args, defaults), type }, defaults.type);
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
    ...p.custom.map((c) => c.token),
  ];
}
