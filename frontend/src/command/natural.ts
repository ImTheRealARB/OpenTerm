/**
 * Plain-English commands ("apple stock price chart", "microsoft 5 year chart", "tesla news", "reliance stock price 5 years").
 *
 * Rule-based and offline: word tables plus the company-name search of nlIndex.ts. No AI, no network (the caller passes the
 * company list in), no React and no `window`, so vitest runs it in Node. The one network step, Yahoo's name search for names
 * nothing local knows, lives in nlResolve.ts and is only asked for through the `lookup` field of a `none` result.
 *
 * Files: this one reads the sentence (chart modifiers, intent, assembling the command); nlRange.ts reads "how far back";
 * nlIndex.ts finds the company; nlAliases.ts is the data for indices / commodities / crypto / currencies / nicknames / Indian
 * names; nlWords.ts has the filler and everyday-word lists.
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
 * AMBIGUITY RULE (never guess between companies): see nlIndex.ts. Short version: share classes of one company are one company
 * (the most traded class wins), preferred shares and warrants never match, and the biggest company wins only if it is 10 times
 * bigger than the next; otherwise `choices` (max 5).
 */
import { closestCompanies, type UniverseEntry } from "../gui/companySearch";
import { closestAliases } from "./nlAliases";
import { findCompanies, findCompany, isFiller, toYahoo, unresolvedWords } from "./nlIndex";
import { GP_RANGES, extractRange, take } from "./nlRange";

export { DOMINANCE } from "./nlIndex";
export { GP_RANGES };

export type NlResult =
  | { kind: "command"; command: string; why: string }
  | { kind: "choices"; choices: { command: string; label: string }[] }
  /**
   * Nothing understood. `lookup` (only when a company phrase was left over) lets the async caller try Yahoo's name search for
   * `phrase` and put the symbol it finds where `{S}` is in `template` (e.g. "{S} GP 5Y"). This file never does the search.
   */
  | { kind: "none"; lookup?: { phrase: string; template: string } };

export interface NlContext {
  isFunction(code: string): boolean;
  /** The screener universe, or null when it is not loaded (then only intent-only phrases and the alias table work). */
  companies: readonly UniverseEntry[] | null;
  /** Today; only used for "since 2020"-style ranges. Defaults to the real date (tests pass a fixed one). */
  now?: Date;
}

/** Chart indicators (kept in step with chart/indicators by natural.test.ts). Each is [pattern, GP token]. */
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
/** Moving-average lengths the chart can draw (chart/indicators.ts INDICATORS). Others are named in the `why`, not drawn. */
const SMA_PERIODS = new Set([20, 50, 100, 200]);
const EMA_PERIODS = new Set([20, 50, 200]);

/**
 * Intent phrases, first match wins (specific phrases before general ones). `codes`: first one that is registered.
 * Every row is only mapped to a function that really shows the thing: valuation numbers (P/E, market cap) are in DES, analyst
 * numbers in EE (EPS and revenue estimates) and ANR (ratings, price targets), the option chain in OMON, news in N.
 */
const INTENTS: [RegExp, string[], string[]?][] = [
  [/\banalyst(?:s)? (?:price )?targets?\b|\bprice targets?\b|\banalyst ratings?\b|\banalysts?\b|\bupgrades?\b|\bdowngrades?\b|\brecommendations?\b|\bwall street (?:rating|target)s?\b/, ["ANR"]],
  [/\b(?:eps |revenue |earnings |analyst )?estimates?\b|\bconsensus\b|\bforecasts?\b|\bexpected (?:eps|earnings|revenue)\b|\bguidance\b/, ["EE"]],
  [/\boption chains?\b|\boptions?\b|\bcalls and puts\b|\bimplied vol(?:atility)?\b/, ["OMON"]],
  [/\bp\/e\b|\bpe ratios?\b|\bpe\b|\bprice[- ]to[- ]earnings\b|\bprice earnings\b|\bvaluations?\b|\bmarket cap(?:italization|italisation)?\b|\bmarket value\b|\bmcap\b|\bworth\b|\bhow big\b/, ["DES"]],
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
  [/\bnews\b|\bheadlines?\b|\bwhat(?:s| is)? (?:happening|going on|new)(?: with| at| in)?\b|\blatest on\b|\bupdates? on\b|\bany news\b/, ["N"]],
  [/\boverview\b|\bprofile\b|\bdescription\b|\bdescribe\b|\bwhat does\b|\bwho is\b|\bsummary\b/, ["DES"]],
  [/\bcharts?\b|\bgraphs?\b|\bplot\b|\bprice history\b|\bstock price\b|\bprices?\b|\bstock\b/, ["GP"]],
];

/**
 * "earnings date" / "when does X report": no function shows a company's next report date (ERN is a calendar of all companies,
 * EE shows estimates by period), so the words are dropped and the `why` says so, instead of opening financials by mistake.
 */
const EARNINGS_DATE = /\b(?:earnings|results|report|reporting) dates?\b|\bnext earnings\b|\bwhen (?:does|do|is|will)\b.*\b(?:report|earnings)\b|\bearnings (?:call|report)\b/;

/** Lower case, possessives and apostrophes dropped ("apple's" -> "apple"), sentence punctuation to spaces. */
const clean = (s: string): string =>
  s
    .toLowerCase()
    .replace(/[’']s\b/g, "") // possessive: "apple's" must not become "apples"
    .replace(/[’']/g, "")
    .replace(/[,;:!?"()]+/g, " ")
    .replace(/\.(?=\s|$)/g, " ") // "inc." -> "inc", but "amazon.com" keeps its dot
    .replace(/\bclass ([a-c])\b/g, "class_$1") // "class a" is part of a name, not the filler word "a"
    .replace(/\s+/g, " ")
    .trim();

interface Parts {
  range?: string;
  /** The range came from "last quarter": financials may read it as the quarterly period instead. */
  quarter?: boolean;
  type?: string;
  log: boolean;
  indicators: string[];
  period?: "A" | "Q";
  /** Things the user asked for that could not be done exactly; shown in the `why`. */
  notes: string[];
  rest: string;
}

/** Pulls the chart/financials modifiers out of the text; what is left holds the intent and the company words. */
function extractModifiers(text: string, now: Date): Parts {
  // "200-day" -> "200 day", "5-year" -> "5 year"
  const st = { s: " " + text.replace(/(\d)-(?=day|week|month|year|yr)/g, "$1 ") + " " };
  const p: Parts = { log: false, indicators: [], notes: [], rest: "" };

  // Moving averages FIRST (before ranges, so "200 day moving average" is not read as 200 days):
  // "sma 50", "50 day moving average", "200 dma", "ema 20", "exponential moving average 50".
  const WORD = String.raw`(?:simple |exponential )?(?:moving averages?|smas?|emas?|dmas?|mas?)`;
  // "50 day and 200 day moving average" -> "50 day moving average 200 day moving average"
  st.s = st.s.replace(
    new RegExp(String.raw`(\d+)(?: days?| d)? (?:and|&) (\d+)(?: days?| d)? (${WORD})`, "g"),
    (_m, a: string, b: string, w: string) => ` ${a} day ${w} ${b} day ${w} `,
  );
  const after = new RegExp(String.raw`\b${WORD} ?(\d+)\b`);
  const before = new RegExp(String.raw`\b(\d+) ?(?:days? |d )?${WORD}\b`);
  for (const re of [before, after]) {
    let r: RegExpExecArray | null;
    while ((r = take(st, re))) {
      const kind = /ema|exponential/.test(r[0]) ? "EMA" : "SMA";
      const k = Number(r[1]);
      if ((kind === "EMA" ? EMA_PERIODS : SMA_PERIODS).has(k)) {
        if (!p.indicators.includes(`${kind}${k}`)) p.indicators.push(`${kind}${k}`);
      } else p.notes.push(`${kind}${k} is not on the chart (SMA 20 50 100 200, EMA 20 50 200)`);
    }
  }

  // How far back.
  const found = extractRange(st, now);
  if (found) {
    p.range = found.range;
    p.quarter = found.quarter;
    if (found.note) p.notes.push(found.note);
  }

  // Chart type, log scale.
  if (take(st, /\bcandle ?sticks?\b|\bcandles?\b/)) p.type = "CANDLE";
  else if (take(st, /\bohlc\b|\bbar chart\b/)) p.type = "OHLC";
  else if (take(st, /\bline\b/)) p.type = "LINE";
  else if (take(st, /\barea\b/)) p.type = "AREA";
  if (take(st, /\blog(?:arithmic)?(?: scale)?\b/)) p.log = true;

  // Named indicators.
  for (const [re, name] of INDICATOR_WORDS) if (take(st, re) && !p.indicators.includes(name)) p.indicators.push(name);
  take(st, /\bindicators?\b|\bmoving averages?\b/);

  // Financial statement period.
  if (take(st, /\bquarterly\b|\bquarter\b|\bqtr\b/)) p.period = "Q";
  else if (take(st, /\bannual(?:ly)?\b|\byearly\b/)) p.period = "A";

  p.rest = st.s.replace(/\s+/g, " ").trim();
  return p;
}

const isNum = (w: string): boolean => /^\d+$/.test(w);

export function interpretNatural(input: string, ctx: NlContext): NlResult {
  const text = clean(input);
  if (!text) return { kind: "none" };
  // Words the user typed in CAPITALS may be tickers even when they are English words ("NOW", "HAS"); an all-caps sentence says nothing.
  const upper = new Set(input === input.toUpperCase() ? [] : (input.match(/\b[A-Z][A-Z0-9]+\b/g) ?? []).map((w) => w.toLowerCase()));
  const p = extractModifiers(text, ctx.now ?? new Date());
  let rest = p.rest;
  const notes = p.notes;

  if (EARNINGS_DATE.test(rest)) {
    rest = rest.replace(EARNINGS_DATE, " ").replace(/\s+/g, " ").trim();
    notes.push("no screen shows a company's next earnings date yet");
  }

  // Intent: the first phrase whose function is registered; then every intent word is removed from the company phrase.
  let fn: string | undefined;
  let fnArgs: string[] = [];
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

  const words = rest.split(" ").filter(Boolean);
  while (words.length && isFiller(words[0], upper)) words.shift();
  while (words.length && isFiller(words[words.length - 1], upper)) words.pop();
  // "3m stock": the range reader took "3m" as three months, but it is also the company 3M.
  if (!words.length && /\b3m\b/.test(text) && p.range === "3M") {
    words.push("3m");
    p.range = undefined;
    notes.length = 0;
  }
  // "last quarter" next to a financials request means the quarterly figures, not a 3-month chart.
  let range = p.range;
  let period = p.period;
  if (fn === "FA" && p.quarter) {
    range = undefined;
    period = "Q";
  }

  const args: string[] = [];
  if (fn === "GP") {
    if (range) args.push(range);
    if (p.type) args.push(p.type);
    if (p.log) args.push("LOG");
    args.push(...p.indicators);
  } else if (fn === "FA") {
    if (period) args.push(period);
    args.push(...fnArgs);
  }

  const make = (symbol: string | null): string => [symbol, fn, ...args].filter(Boolean).join(" ");
  const why = (head: string, label?: string): string => [head + (label ? ` (${label})` : ""), ...notes].join(" · ");

  if (!words.length || words.every(isNum)) {
    // No company: only a phrase with an intent can still run ("news", "show me the chart" use the panel's security).
    return fn ? { kind: "command", command: make(null), why: why(fn) } : { kind: "none" };
  }

  const found = findCompany(words, ctx.companies, upper);
  if (found) {
    // "apple microsoft nvidia 1 year": several companies and no "vs" -> one chart comparing them (GP takes up to 3 after VS).
    if (found.len < words.length && (!fn || fn === "GP") && ctx.isFunction("GP")) {
      const many = findCompanies(words, ctx.companies, upper);
      if (many) {
        const symbols = many.map((f) => (f.res.kind === "one" ? f.res.symbol : "")).slice(0, 4);
        const [first, ...others] = symbols;
        const cmd = [first, "GP", ...(fn ? args : []), "VS", ...others].join(" ");
        const cut = many.length > 4 ? ["GP compares at most 4 names; the rest were left out"] : [];
        return { kind: "command", command: cmd, why: [`${first} GP VS ${others.join(" ")}`, ...notes, ...cut].join(" · ") };
      }
    }
    const r = found.res;
    if (r.kind === "one") return { kind: "command", command: make(r.symbol), why: why(`${r.symbol} ${fn ?? ""}`.trim(), r.label) };
    if (r.kind === "many") {
      return { kind: "choices", choices: r.picks.slice(0, 5).map((h) => ({ command: make(h.symbol), label: `${h.symbol}  ${h.name}` })) };
    }
  }

  // Nothing matched. A mistyped name ("mircosoft", "appl") gets "did you mean" only when a company's name is a letter or two away.
  if (ctx.companies) {
    for (const w of unresolvedWords(words)) {
      const near = [
        ...closestAliases(w).map((a) => ({ symbol: a.symbol, name: a.label })),
        ...closestCompanies(w, ctx.companies, 3, { strict: true }).map((h) => ({ symbol: toYahoo(h.symbol), name: h.name })),
      ].filter((h, i, all) => all.findIndex((x) => x.symbol === h.symbol) === i);
      if (near.length) return { kind: "choices", choices: near.slice(0, 4).map((h) => ({ command: make(h.symbol), label: `${h.symbol}  ${h.name}` })) };
    }
    // Still nothing: let the async side try Yahoo's name search for what is left (a short phrase of real words).
    const left = words.filter((w) => !isFiller(w, upper) && !isNum(w));
    if (left.length && left.length <= 4 && left.join(" ").length >= 3) {
      return { kind: "none", lookup: { phrase: left.join(" "), template: make("{S}") } };
    }
  }
  return { kind: "none" };
}
