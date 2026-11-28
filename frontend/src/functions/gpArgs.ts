/**
 * GP command arguments (pure, so vitest can run it): [range] [interval] [VS SYM...] [PANE] [EVT] [CANDLE|OHLC|LINE|AREA|RENKO|KAGI|PNF|...] [BOX=n] [REV=n] [LOG] [SCRIPT=NAME[(inputs)][,NAME2]] [studies...].
 * Order is free. `VS` takes up to three symbols; with `PANE` each gets its own pane, without it the first one is overlaid (rebased to %).
 */
import { CHART_TYPES, type ChartType } from "../chart/chartTypes";
import { GP_RANGES } from "../chart/gpRanges";
import { INDICATORS, type IndicatorName } from "../chart/indicators";

/** The shared range list (chart/gpRanges.ts; startup code imports it from there, never from this file). */
export const RANGES = GP_RANGES;
/** Number keys 1..8 jump to these. */
export const KEY_RANGES = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"];
/**
 * Phase 21 candle lengths, typed word (UPPER CASE) -> the id the server uses. Mirror of the new aliases in backend `ranges.py` INTERVALS.
 * 2h..12h are built by the server from 60 minute candles, 2d / 3d from daily, 2wk from weekly, 3mo (quarter) / 12mo (year) from monthly;
 * 1s is Binance spot only. None of these words is a range (`RANGES`), so a range token and an interval token never clash.
 */
const LONG_WORDS: Readonly<Record<string, string>> = {
  "1S": "1s", "1SEC": "1s",
  "2H": "2h", "3H": "3h", "4H": "4h", "6H": "6h", "8H": "8h", "12H": "12h",
  "2D": "2d", "3D": "3d",
  "2W": "2wk", "2WK": "2wk",
  Q: "3mo", "3MO": "3mo", QUARTERLY: "3mo",
  "12MO": "12mo", YEARLY: "12mo",
};
const INTERVAL_WORDS = new Set(["1MIN", "2MIN", "5MIN", "15MIN", "30MIN", "60MIN", "90MIN", "1H", "D", "1D", "DAILY", "W", "1W", "1WK", "WEEKLY", "MO", "1MO", "MONTHLY", ...Object.keys(LONG_WORDS)]);
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

/**
 * OpenTerm Script on a chart (Phase 25): `SCRIPT=NAME`, several as `SCRIPT=A,B`. Per-chart input overrides follow a name in
 * parentheses, in the order of the script's `input.*` calls, empty = the script's default: `SCRIPT=RSI_BANDS(14,70)`,
 * `SCRIPT=A(,70),B`. Text values are percent-encoded (`SCRIPT=X(%28a%29)`), so one chart's whole script state is ONE token with
 * no spaces: the command line, layouts (`replaceView` args) and history keep it as they keep `ATR(14)`.
 * The values stay RAW TEXT here ("14", "true", "close"); `script/inputArgs.ts` turns them into typed values using the
 * script's own input definitions, so this file never imports the script engine (startup bundle).
 */
export interface ScriptRef {
  /** Stored name, upper case (backend `STORED_NAME_RE`). */
  name: string;
  /** Raw positional input values; "" = use the default. Trailing empties are never kept. */
  inputs: string[];
}
/** The five-studies budget of spec section 2 (a tick runs every script on the chart). */
export const MAX_SCRIPTS = 5;
const SCRIPT_ENTRY = /^([A-Z0-9][A-Z0-9_.-]{0,31})(?:\((.*)\))?$/i;

/** Encodes one input value so it cannot clash with the token's own `( ) ,` (encodeURIComponent keeps `( )`). */
function encodeInput(v: string): string {
  return encodeURIComponent(v).replace(/[()!'*]/g, (ch) => `%${ch.charCodeAt(0).toString(16).toUpperCase()}`);
}

/** Splits at commas that are not inside parentheses. */
function splitTop(text: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of text) {
    if (ch === "(") depth++;
    else if (ch === ")") depth = Math.max(0, depth - 1);
    if (ch === "," && depth === 0) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

/** One `SCRIPT=...` arg as its script list, or null when it is not a well-formed SCRIPT arg (the whole token is then ignored). */
export function parseScriptToken(raw: string): ScriptRef[] | null {
  const m = /^SCRIPT=(.+)$/i.exec(raw);
  if (!m) return null;
  const out: ScriptRef[] = [];
  for (const part of splitTop(m[1])) {
    const e = SCRIPT_ENTRY.exec(part);
    if (!e) return null;
    let inputs: string[] = [];
    if (e[2] !== undefined && e[2] !== "") {
      try {
        inputs = e[2].split(",").map((x) => decodeURIComponent(x));
      } catch {
        return null;
      }
      while (inputs.length && inputs[inputs.length - 1] === "") inputs.pop();
    }
    out.push({ name: e[1].toUpperCase(), inputs });
  }
  return out;
}

/** The single `SCRIPT=...` arg for a list of scripts ("" for none). */
export function serializeScripts(list: ScriptRef[]): string {
  if (!list.length) return "";
  return "SCRIPT=" + list.map((s) => (s.inputs.length ? `${s.name}(${s.inputs.map(encodeInput).join(",")})` : s.name)).join(",");
}

export interface GpParsed {
  range: string;
  interval?: string;
  /** Compare symbols (uppercase), at most MAX_COMPARE. */
  compare: string[];
  pane: boolean;
  evt: boolean;
  type: ChartType;
  /** `BOX=<number>`: box size / kagi reversal / range-bar range in price units for the brick types. Absent = ATR(14) of the source bars. */
  box?: number;
  /** `REV=<n>`: point and figure reversal in boxes (whole number, default 3). */
  rev?: number;
  log: boolean;
  indicators: IndicatorName[];
  /** Library indicators and formulas, in the order given (at most MAX_CUSTOM). */
  custom: CustomInd[];
  /** Phase 25: scripts drawn on the chart (`SCRIPT=NAME`), at most MAX_SCRIPTS, with their per-chart input overrides. */
  scripts: ScriptRef[];
  /** Phase 24: `REPLAY [YYYY-MM-DD]`: bar replay from that day (absent date = the last 100 bars are hidden). */
  replay?: { start: string | null };
  /** Phase 24 gap: `STOP=5 TARGET=10` (percent from the average entry): the replay practice book's exits. Used only with REPLAY. */
  exits?: { stop?: number; target?: number };
  /** Phase 28: `CONE`: the options' 1 and 2 standard-deviation price ranges to each listed expiry. */
  cone?: boolean;
}

const DAY_TOKEN = /^\d{4}-\d{2}-\d{2}$/;

/** `BOX=2.5` -> 2.5 (positive, plain decimal); anything else -> null. */
const BOX_TOKEN = /^BOX=(\d+\.?\d*|\.\d+)$/i;
/** `REV=3` -> 3 (a whole number from 1 to 20); anything else -> null. */
const REV_TOKEN = /^REV=(\d{1,2})$/i;
/** `STOP=5` / `TARGET=12.5` -> the percent (> 0; a stop under 100); anything else -> null. */
const EXIT_TOKEN = /^(STOP|TARGET)=(\d+\.?\d*|\.\d+)$/i;

function parseExit(raw: string): ["stop" | "target", number] | null {
  const m = EXIT_TOKEN.exec(raw);
  if (!m) return null;
  const v = Number(m[2]);
  const which = m[1].toLowerCase() as "stop" | "target";
  return v > 0 && v <= (which === "stop" ? 99 : 1000) ? [which, v] : null;
}

function parseBox(raw: string): number | null {
  const m = BOX_TOKEN.exec(raw);
  const v = m ? Number(m[1]) : NaN;
  return v > 0 && Number.isFinite(v) ? v : null;
}

function parseRev(raw: string): number | null {
  const m = REV_TOKEN.exec(raw);
  const v = m ? Number(m[1]) : NaN;
  return v >= 1 && v <= 20 ? v : null;
}

function isKeyword(raw: string): boolean {
  const a = raw.toUpperCase();
  return (
    a === "VS" || a === "PANE" || a === "EVT" || a === "LOG" || a === "REPLAY" || a === "CONE" || a === "PAT:ICHI" || RANGES.includes(a) || YAHOO_INTERVALS.has(raw) || INTERVAL_WORDS.has(a) ||
    parseBox(raw) !== null || parseRev(raw) !== null || parseExit(raw) !== null || parseScriptToken(raw) !== null ||
    (CHART_TYPES as string[]).includes(a) || (INDICATORS as readonly string[]).includes(a) || parseCustomToken(raw) !== null
  );
}

/** `defaults`: the SETTINGS default range and chart type (Phase 10). */
export function parseGpArgs(args: string[], defaults: { range: string; type: ChartType } = { range: "1Y", type: "CANDLE" }): GpParsed {
  const p: GpParsed = { range: defaults.range, type: defaults.type, log: false, compare: [], pane: false, evt: false, indicators: [], custom: [], scripts: [] };
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
    else if (BOX_TOKEN.test(raw)) {
      // A BOX= that is not a positive number is ignored (the brick types then use ATR(14), and the on-screen note says so).
      const v = parseBox(raw);
      if (v !== null) p.box = v;
    } else if (REV_TOKEN.test(raw)) {
      const v = parseRev(raw);
      if (v !== null) p.rev = v;
    } else if (EXIT_TOKEN.test(raw)) {
      // An out-of-range STOP= / TARGET= is ignored (no exit of that kind), like BOX=.
      const e = parseExit(raw);
      if (e) p.exits = { ...p.exits, [e[0]]: e[1] };
    } else if (a === "LOG") p.log = true;
    else if (a === "CONE") p.cone = true;
    else if (a === "REPLAY") p.replay = { start: args[i + 1] && DAY_TOKEN.test(args[i + 1]) ? args[++i] : null };
    else if (a.startsWith("SCRIPT=")) {
      // A malformed SCRIPT= arg is ignored whole (like a bad BOX=); a name already on the chart keeps its first inputs.
      for (const sc of parseScriptToken(raw) ?? []) if (p.scripts.length < MAX_SCRIPTS && !p.scripts.some((x) => x.name === sc.name)) p.scripts.push(sc);
    } else if (a === "PAT:ICHI" && !p.indicators.includes("ICHIMOKU")) p.indicators.push("ICHIMOKU");
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
  ["Auto", ""], ["1 second", "1s"], ["5 min", "5m"], ["15 min", "15m"], ["30 min", "30m"], ["1 hour", "60m"],
  ["2 hours", "2h"], ["3 hours", "3h"], ["4 hours", "4h"], ["6 hours", "6h"], ["8 hours", "8h"], ["12 hours", "12h"],
  ["Daily", "1d"], ["2 days", "2d"], ["3 days", "3d"], ["Weekly", "1wk"], ["2 weeks", "2wk"], ["Monthly", "1mo"], ["Quarterly", "3mo"], ["Yearly", "12mo"],
];

/**
 * How many days back each minute candle length reaches for one symbol, as the BACKEND reports it (GET /api/history/limits):
 * the deepest source that is switched on for that symbol decides (Yahoo 60 days; a deeper source such as Kite once a
 * login is valid). Lengths the backend does not list (daily, weekly, monthly) are unlimited. `undefined` = not known yet: show
 * everything and let the server's own error be the authority.
 */
export type IntradayLimits = Readonly<Record<string, number>>;

/** Days each range covers (copy of `_RANGE_DAYS` in backend/openterm/ranges.py; ranges not listed have no limit check). */
const RANGE_DAYS: Readonly<Record<string, number>> = { "1D": 1, "5D": 5, "1M": 31, "3M": 92, "6M": 183, YTD: 366, "1Y": 366, "2Y": 731, "5Y": 1827, "10Y": 3653, MAX: 100_000 };
const MINUTE_WORDS: Readonly<Record<string, string>> = { "1MIN": "1m", "2MIN": "2m", "5MIN": "5m", "15MIN": "15m", "30MIN": "30m", "60MIN": "60m", "1H": "60m", "90MIN": "90m" };

/** The Yahoo token for a candle length typed either way ("15min" and "15m" both give "15m"). */
export function intervalToken(raw: string): string {
  return YAHOO_INTERVALS.has(raw) ? raw : (MINUTE_WORDS[raw.toUpperCase()] ?? LONG_WORDS[raw.toUpperCase()] ?? raw.toLowerCase());
}

/** Does this candle length reach back far enough for this range? (Daily and longer, or limits not known yet: yes.) */
export function intervalFits(range: string, interval: string, limits?: IntradayLimits): boolean {
  const limit = limits?.[intervalToken(interval)];
  const days = RANGE_DAYS[range.toUpperCase()];
  return limit === undefined || days === undefined || days <= limit;
}

/** The longest range that fits within `days` of history. 60 -> "1M", 7 -> "5D". */
export function longestRangeWithin(days: number): string | null {
  const fitting = Object.entries(RANGE_DAYS).filter(([, d]) => d <= days);
  return fitting.length ? fitting.reduce((best, cur) => (cur[1] >= best[1] ? cur : best))[0] : null;
}

/** "up to 60 days", "up to 4 years": how far back a candle length reaches. */
export function limitText(days: number): string {
  if (days < 120) return `up to ${days} days`;
  if (days < 730) return `up to ${Math.round(days / 30)} months`;
  return `up to ${(days / 365).toFixed(1).replace(/\.0$/, "")} years`;
}

/** The days in the server's depth message ("INTERVAL 5m ONLY AVAILABLE FOR THE LAST 60 DAYS"), or null for any other error. */
export function depthLimitFromError(message: string): number | null {
  const m = /ONLY AVAILABLE FOR THE LAST (\d+) DAYS/i.exec(message);
  return m ? Number(m[1]) : null;
}

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
    ...(p.box !== undefined ? [`BOX=${p.box}`] : []),
    ...(p.rev !== undefined ? [`REV=${p.rev}`] : []),
    ...(p.log ? ["LOG"] : []),
    ...(p.cone ? ["CONE"] : []),
    ...(p.replay ? ["REPLAY", ...(p.replay.start ? [p.replay.start] : [])] : []),
    ...(p.exits?.stop ? [`STOP=${p.exits.stop}`] : []),
    ...(p.exits?.target ? [`TARGET=${p.exits.target}`] : []),
    ...p.indicators,
    ...p.custom.map((c) => c.token),
    ...(p.scripts.length ? [serializeScripts(p.scripts)] : []),
  ];
}
