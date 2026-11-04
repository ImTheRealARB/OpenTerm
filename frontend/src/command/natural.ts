/**
 * Plain-English commands ("apple stock price chart", "microsoft 5 year chart", "tesla news").
 *
 * Rule-based and offline: a few word tables and the company-name search of the GUI (gui/companySearch). No AI, no network
 * (the caller passes the company list in), no React and no `window`, so vitest runs it in Node.
 *
 * WHEN THIS FILE IS CONSULTED (decided in command/nlRun.ts `needsNatural`, not here):
 *   - Exact codes always win. If `parseCommand` accepts the input, natural language is never asked, with ONE exception:
 *     a single word that is not all upper case and is at least 3 letters ("apple", "Tesla"). That is a valid symbol token
 *     syntactically, but a ticker is normally typed in capitals, so it is looked up in the company list first:
 *     an exact ticker ("aapl") keeps its old meaning, a company name ("apple") becomes AAPL, and when the list cannot be
 *     loaded the old behaviour (treat it as a ticker) stays.
 *   - A failed parse ("apple chart", "bank of america news": BAD SYMBOL / UNKNOWN FUNCTION) asks natural language before
 *     the error is shown; "none" then shows the original error.
 *
 * AMBIGUITY RULE (never guess between companies): candidates are the name matches of the longest word run that matches.
 * An exact ticker wins outright. Otherwise the best name tier (name starts with the words beats a later word starts with them)
 * is kept and the hits are grouped by company (share classes of one company share a group). The top group wins only if its
 * market cap is at least DOMINANCE (10) times the next group's ("apple" -> Apple Inc., not Apple Hospitality REIT). A winning
 * group with several share classes ("alphabet": GOOGL / GOOG) and an unclear top both return `choices` (max 5).
 */
import { matchCompanies, type CompanyHit, type UniverseEntry } from "../gui/companySearch";

export type NlResult =
  | { kind: "command"; command: string; why: string }
  | { kind: "choices"; choices: { command: string; label: string }[] }
  | { kind: "none" };

export interface NlContext {
  isFunction(code: string): boolean;
  /** The screener universe, or null when it is not loaded (then only intent-only phrases work, e.g. "news"). */
  companies: readonly UniverseEntry[] | null;
}

/** The top company's market cap must be this many times the next company's to be picked without asking. */
export const DOMINANCE = 10;
const MAX_CHOICES = 5;

/** Ranges GP accepts (kept in step with gpArgs RANGES by natural.test.ts). */
export const GP_RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"];
/** Indicator words (kept in step with chart/indicators by natural.test.ts). */
const INDICATOR_WORDS: [RegExp, string][] = [
  [/\bbollinger(?: bands?)?\b|\bbb\b/, "BB"],
  [/\brsi\b|\brelative strength(?: index)?\b/, "RSI"],
  [/\bmacd\b/, "MACD"],
  [/\bvwap\b/, "VWAP"],
  [/\batr\b|\baverage true range\b/, "ATR"],
  [/\bstochastics?\b|\bstoch\b/, "STOCH"],
  [/\badx\b/, "ADX"],
  [/\bobv\b/, "OBV"],
  [/\bcci\b/, "CCI"],
  [/\bichimoku\b/, "ICHIMOKU"],
  [/\bsupertrend\b/, "SUPERTREND"],
  [/\bparabolic sar\b|\bpsar\b/, "PSAR"],
];
const SMA_PERIODS = new Set([20, 50]);
const EMA_PERIODS = new Set([20]);

/** Words that carry no meaning for the command (trimmed from both ends of the company phrase; kept inside it: "bank of america"). */
const FILLER = new Set(
  ("show me the a an for of please open get what whats is are how doing do does to see give display pull up on in at and with " +
    "my us tell about look looking check can could you i want need would like let lets go find view its it s share shares " +
    "company inc corp corporation ltd plc co now currently current latest recent recently over past last this vs versus " +
    "chart charts graph graphs stock stocks price prices").split(" "),
);

/** Intent phrases, first match wins (specific phrases before general ones). `codes`: first one that is registered. */
const INTENTS: [RegExp, string[], string[]?][] = [
  [/\bincome statements?\b|\bprofit and loss\b|\bp&l\b|\bp and l\b/, ["FA"], ["IS"]],
  [/\bbalance sheets?\b/, ["FA"], ["BS"]],
  [/\bcash ?flows?\b/, ["FA"], ["CF"]],
  [/\bfinancials?\b|\bfinancial statements?\b|\bearnings\b|\brevenue\b|\bfundamentals?\b/, ["FA"]],
  [/\b10-?k\b|\b10-?q\b|\bfilings?\b|\bsec\b|\bedgar\b/, ["FIL"]],
  [/\bhold(?:ers?|ings)\b|\bwho owns\b|\binstitutional\b|\b13f\b/, ["HDS", "OWN"]],
  [/\bownership\b|\binsiders?\b/, ["OWN", "HDS"]],
  [/\bpeers?\b|\bcompetitors?\b|\bcompare(?:d)? to peers\b|\bsimilar companies\b/, ["COMP"]],
  [/\bseasonality\b|\bseasonal\b/, ["SEAS"]],
  [/\bdividends?\b|\bpayouts?\b/, ["DVD"]],
  [/\bnews\b|\bheadlines?\b/, ["N"]],
  [/\boverview\b|\bprofile\b|\bdescription\b|\bdescribe\b|\bwhat does\b|\bwho is\b|\bsummary\b/, ["DES"]],
  [/\bcharts?\b|\bgraphs?\b|\bplot\b|\bprice history\b|\bstock price\b|\bprices?\b|\bstock\b/, ["GP"]],
];

const clean = (s: string): string =>
  s.toLowerCase().replace(/[’']s\b/g, "s").replace(/[’']/g, "").replace(/[,;:!?"()]+/g, " ").replace(/\s+/g, " ").trim();

/** Takes `re`'s first match out of the working text; returns the match or null. */
function take(state: { s: string }, re: RegExp): RegExpExecArray | null {
  const m = re.exec(state.s);
  if (m) state.s = (state.s.slice(0, m.index) + " " + state.s.slice(m.index + m[0].length)).replace(/\s+/g, " ");
  return m;
}

interface Parts {
  range?: string;
  type?: string;
  log: boolean;
  indicators: string[];
  period?: "A" | "Q";
  rest: string;
}

/** Pulls the chart/financials modifiers out of the text; what is left holds the intent and the company words. */
function extractModifiers(text: string): Parts {
  const st = { s: " " + text + " " };
  const p: Parts = { log: false, indicators: [], rest: "" };

  // Ranges.
  const num = "(\\d+|a|one|two|three|five|ten)";
  const n = (w: string) => ({ a: 1, one: 1, two: 2, three: 3, five: 5, ten: 10 })[w] ?? Number(w);
  let m: RegExpExecArray | null;
  if ((m = take(st, /\b(?:year to date|ytd)\b/))) p.range = "YTD";
  else if ((m = take(st, /\b(?:max|maximum|all time|all-time|alltime|full history|since inception|lifetime)\b/))) p.range = "MAX";
  else if ((m = take(st, new RegExp(`\\b${num} ?(?:years?|yrs?|y)\\b`)))) p.range = `${n(m[1])}Y`;
  else if ((m = take(st, new RegExp(`\\b${num} ?(?:months?|mos?|m)\\b`)))) p.range = `${n(m[1])}M`;
  else if ((m = take(st, new RegExp(`\\b${num} ?(?:weeks?|wks?|w)\\b`)))) p.range = n(m[1]) === 1 ? "5D" : n(m[1]) <= 4 ? "1M" : "3M";
  else if ((m = take(st, new RegExp(`\\b${num} ?(?:days?|d)\\b`)))) p.range = n(m[1]) === 1 ? "1D" : n(m[1]) <= 5 ? "5D" : "1M";
  else if ((m = take(st, /\b(?:today|intraday|todays|this morning)\b/))) p.range = "1D";
  else if ((m = take(st, /\b(?:this|past|last) year\b/))) p.range = "1Y";
  else if ((m = take(st, /\b(?:this|past|last) month\b/))) p.range = "1M";
  else if ((m = take(st, /\b(?:this|past|last) week\b/))) p.range = "5D";
  if (p.range && !GP_RANGES.includes(p.range)) p.range = undefined; // "4 years": not a GP range, the words are dropped

  // Chart type, log scale.
  if (take(st, /\bcandle ?sticks?\b|\bcandles?\b/)) p.type = "CANDLE";
  else if (take(st, /\bohlc\b|\bbar chart\b/)) p.type = "OHLC";
  else if (take(st, /\bline\b/)) p.type = "LINE";
  else if (take(st, /\barea\b/)) p.type = "AREA";
  if (take(st, /\blog(?:arithmic)?(?: scale)?\b/)) p.log = true;

  // Indicators: "moving average 50", "sma 50", "50 day moving average", "ema 20".
  const ma = (kind: "SMA" | "EMA", re: RegExp, ok: Set<number>) => {
    let r: RegExpExecArray | null;
    while ((r = take(st, re))) {
      const k = Number(r[1] ?? r[2]);
      if (ok.has(k) && !p.indicators.includes(`${kind}${k}`)) p.indicators.push(`${kind}${k}`);
    }
  };
  ma("EMA", /\bexponential(?: moving average)? ?(\d+)\b|\bema ?(\d+)\b/, EMA_PERIODS);
  ma("SMA", /\b(?:simple )?(?:moving average|sma|ma) ?(\d+)\b|\b(\d+) ?(?:day |d )?(?:simple )?(?:moving average|sma|ma)\b/, SMA_PERIODS);
  for (const [re, name] of INDICATOR_WORDS) if (take(st, re) && !p.indicators.includes(name)) p.indicators.push(name);
  take(st, /\bindicators?\b|\bmoving averages?\b/);

  // Financial statement period.
  if (take(st, /\bquarterly\b|\bquarter\b|\bqtr\b/)) p.period = "Q";
  else if (take(st, /\bannual(?:ly)?\b|\byearly\b/)) p.period = "A";

  p.rest = st.s.replace(/\s+/g, " ").trim();
  return p;
}

const baseName = (name: string): string =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\b(?:class [a-z]\b.*|capital stock.*|common stock.*|ordinary shares.*|american depositary.*)$/, "")
    .replace(/\s+/g, " ")
    .trim();

const simple = (s: string): string => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

type Resolved = { kind: "one"; hit: CompanyHit } | { kind: "many"; hits: CompanyHit[] } | { kind: "no" };

/** Resolves one phrase to a company, or several candidates when it is not clear (see the file header). */
function resolveRun(run: string, uni: readonly UniverseEntry[]): Resolved {
  const q = clean(run);
  if (!q) return { kind: "no" };
  const exact = !q.includes(" ") ? uni.find((e) => e.symbol.toLowerCase() === q) : undefined;
  if (exact) return { kind: "one", hit: { symbol: exact.symbol, name: exact.name, via: "symbol" } };
  const qn = simple(q);
  if (qn.length < 3) return { kind: "no" };
  const hits = matchCompanies(qn, uni, 40).filter((h) => h.via === "name");
  if (!hits.length) return { kind: "no" };
  const tierOf = (h: CompanyHit) => (simple(h.name).startsWith(qn) ? 2 : 1);
  const best = Math.max(...hits.map(tierOf));
  const top = hits.filter((h) => tierOf(h) === best);
  const mcap = (h: CompanyHit) => uni.find((e) => e.symbol === h.symbol)?.mcap ?? 0;
  const groups: CompanyHit[][] = [];
  for (const h of top) {
    const g = groups.find((x) => baseName(x[0].name) === baseName(h.name));
    if (g) g.push(h);
    else groups.push([h]);
  }
  const gcap = (g: CompanyHit[]) => Math.max(...g.map(mcap));
  groups.sort((a, b) => gcap(b) - gcap(a));
  const first = groups[0];
  const second = groups[1];
  const dominant = !second || gcap(first) >= DOMINANCE * gcap(second);
  if (dominant && first.length === 1) return { kind: "one", hit: first[0] };
  if (dominant) return { kind: "many", hits: [...first].sort((a, b) => mcap(b) - mcap(a)).slice(0, MAX_CHOICES) };
  return { kind: "many", hits: groups.map((g) => g[0]).slice(0, MAX_CHOICES) };
}

/** Longest run of the phrase's words that names a company (a run never starts or ends on a filler word). */
function findCompany(words: string[], uni: readonly UniverseEntry[]): Resolved {
  for (let len = words.length; len >= 1; len--) {
    for (let i = 0; i + len <= words.length; i++) {
      if (FILLER.has(words[i]) || FILLER.has(words[i + len - 1])) continue;
      const r = resolveRun(words.slice(i, i + len).join(" "), uni);
      if (r.kind !== "no") return r;
    }
  }
  return { kind: "no" };
}

export function interpretNatural(input: string, ctx: NlContext): NlResult {
  const text = clean(input);
  if (!text) return { kind: "none" };
  const p = extractModifiers(text);

  // Intent: the first phrase whose function is registered; then every intent word is removed from the company phrase.
  let fn: string | undefined;
  let fnArgs: string[] = [];
  let rest = p.rest;
  for (const [re, codes, args] of INTENTS) {
    if (!re.test(" " + rest + " ")) continue;
    const code = codes.find((c) => ctx.isFunction(c));
    if (!code) continue; // not registered: try the next phrase
    fn = code;
    fnArgs = args ?? [];
    break;
  }
  for (const [re] of INTENTS) rest = (" " + rest + " ").replace(new RegExp(re.source, "g"), " ").replace(/\s+/g, " ").trim();
  // Chart modifiers with no other intent mean a chart ("apple 5 year", "tesla rsi").
  const chartish = p.range !== undefined || p.type !== undefined || p.log || p.indicators.length > 0;
  if (!fn && chartish && ctx.isFunction("GP")) fn = "GP";

  const args: string[] = [];
  if (fn === "GP") {
    if (p.range) args.push(p.range);
    if (p.type) args.push(p.type);
    if (p.log) args.push("LOG");
    args.push(...p.indicators);
  } else if (fn === "FA") {
    if (p.period) args.push(p.period);
    args.push(...fnArgs);
  }

  const words = rest.split(" ").filter(Boolean);
  while (words.length && (FILLER.has(words[0]) || /^\d+$/.test(words[0]))) words.shift();
  while (words.length && (FILLER.has(words[words.length - 1]) || /^\d+$/.test(words[words.length - 1]))) words.pop();
  const make = (symbol: string | null): string => [symbol, fn, ...args].filter(Boolean).join(" ");

  if (!words.length) {
    // No company: only a phrase with an intent can still run ("news", "show me the chart" use the panel's security).
    return fn ? { kind: "command", command: make(null), why: fn } : { kind: "none" };
  }
  if (!ctx.companies) return { kind: "none" };
  const r = findCompany(words, ctx.companies);
  if (r.kind === "no") return { kind: "none" };
  if (r.kind === "one") return { kind: "command", command: make(r.hit.symbol), why: `${r.hit.symbol} ${fn ?? ""}`.trim() };
  return {
    kind: "choices",
    choices: r.hits.slice(0, MAX_CHOICES).map((h) => ({ command: make(h.symbol), label: `${h.symbol}  ${h.name}` })),
  };
}
