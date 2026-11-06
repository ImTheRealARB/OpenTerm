/**
 * Plain-English compare (pure, unit-tested): "apple vs microsoft 1 year", "compare tesla and ford", "aapl versus msft 5y"
 * -> the GP compare command `AAPL GP 1Y VS MSFT` (syntax of functions/gpArgs.ts: `VS` takes up to three more symbols).
 *
 * The company-name -> symbol step is injected (`resolve`), so this file does not depend on natural.ts or the network:
 *   const r = compareCommand("apple vs microsoft 1 year", (phrase) => symbolOrNull(phrase));
 *   if (r.command) execute(r.command); else show(r.error);
 * A phrase the resolver cannot map is an error naming it; nothing is guessed.
 */
import { GP_RANGES } from "../chart/gpRanges";

export interface CompareParse {
  /** First company phrase (as typed, lowercase, filler words removed). */
  a: string;
  /** Second company phrase. */
  b: string;
  /** Up to two more phrases ("a vs b vs c"). */
  more: string[];
  /** A valid GP range (1D 5D 1M 3M 6M YTD 1Y 2Y 5Y 10Y MAX) when one was asked for. */
  range?: string;
  /** A range the text asked for that GP has no button for ("3 years"); the caller should say so. */
  badRange?: string;
}

export interface CompareResult {
  command?: string;
  error?: string;
  parse?: CompareParse;
}

const GP_RANGE_SET = new Set<string>(GP_RANGES);
const MAX_VS = 3;
const LEAD = /^(?:please\s+|can you\s+|show me\s+|show\s+|chart\s+|plot\s+|graph\s+|draw\s+)*(?:compare|comparing|comparison of|comparison)?\s*/;
const HAS_COMPARE_LEAD = /^(?:please\s+|can you\s+|show me\s+|show\s+|chart\s+|plot\s+|graph\s+|draw\s+)*(?:compare|comparing|comparison)\b/;
const STRONG_SPLIT = /\s+(?:vs\.?|versus|v\.?|against|compared\s+(?:to|with)|relative\s+to)\s+/;
const SOFT_SPLIT = /\s+(?:and|with|&|,)\s+|\s*,\s*/;

/** "5 years" -> "5Y", "6 months" -> "6M", "ytd" -> "YTD". Null when the text is not a range at all. */
export function rangeFrom(num: number | null, unit: string): string | null {
  const u = unit.toLowerCase();
  if (u === "ytd") return "YTD";
  if (/^(max|maximum|all)$/.test(u)) return "MAX";
  if (num === null) return null;
  if (/^(y|yr|yrs|year|years)$/.test(u)) return `${num}Y`;
  if (/^(m|mo|mos|month|months)$/.test(u)) return `${num}M`;
  if (/^(d|day|days)$/.test(u)) return `${num}D`;
  if (/^(w|wk|wks|week|weeks)$/.test(u)) return num === 1 ? "5D" : `${num * 5}D`;
  return null;
}

const RANGE_END = /(?:\b(?:over|for|in|during|within)\s+)?(?:\bthe\s+)?(?:\b(?:last|past|previous)\s+)?(?:(\d+)\s*(y|yr|yrs|years?|mo|mos|months?|m|d|days?|wk|wks|weeks?|w)|(ytd|year to date|this year|all time|max|maximum|a year|one year|a month|one month|a week))\s*$/;
const RANGE_PREFIXED = /\b(?:over|for|during|within)\s+(?:the\s+)?(?:(?:last|past|previous)\s+)?(?:(\d+)\s*(y|yr|yrs|years?|mo|mos|months?|m|d|days?|wk|wks|weeks?|w)|(ytd|year to date|this year|all time|max|maximum|a year|one year|a month|one month|a week))\b/;
const WORD_RANGE: Record<string, string> = { "year to date": "YTD", ytd: "YTD", "this year": "YTD", "all time": "MAX", max: "MAX", maximum: "MAX", "a year": "1Y", "one year": "1Y", "a month": "1M", "one month": "1M", "a week": "5D" };

const FILLER = /\b(?:stock|stocks|shares|share price|share|price|prices|performance|chart|charts|please|inc|corp|corporation)\b/g;

function clean(s: string): string {
  return s.replace(FILLER, " ").replace(/^(?:the|a|an)\s+/, "").replace(/\s+/g, " ").trim();
}

/** Splits "apple vs microsoft 1 year" into phrases and a range. Null when it is not a two-company comparison. */
export function parseCompare(input: string): CompareParse | null {
  let t = input.toLowerCase().replace(/[?!]+/g, " ").replace(/\s+/g, " ").trim();
  if (!t) return null;
  const hasLead = HAS_COMPARE_LEAD.test(t);

  let range: string | undefined;
  let badRange: string | undefined;
  const take = (m: RegExpExecArray) => {
    const word = m[3] ? WORD_RANGE[m[3]] : null;
    const r = word ?? rangeFrom(Number(m[1]), m[2]);
    if (r && GP_RANGE_SET.has(r)) range = r;
    else badRange = m[0].trim().toUpperCase();
    t = (t.slice(0, m.index) + " " + t.slice(m.index + m[0].length)).replace(/\s+/g, " ").trim();
  };
  // Try the end of the text first, then "over/for the last N years" anywhere; keep the range only if two sides remain.
  const before = t;
  for (const re of [RANGE_PREFIXED, RANGE_END]) {
    const m = re.exec(t);
    if (m) {
      take(m);
      break;
    }
  }

  t = t.replace(LEAD, "").trim();
  let parts = t.split(STRONG_SPLIT);
  if (parts.length < 2 && (hasLead || /\bbetween\b/.test(t))) {
    t = t.replace(/^between\s+/, "");
    parts = t.split(SOFT_SPLIT);
  }
  let phrases = parts.map(clean).filter(Boolean);
  if (phrases.length < 2 && (range || badRange)) {
    // The "range" may have been part of a name ("apple vs 3m"): retry without taking a range.
    t = before.replace(LEAD, "").trim();
    range = undefined;
    badRange = undefined;
    parts = t.split(STRONG_SPLIT);
    if (parts.length < 2 && hasLead) parts = t.replace(/^between\s+/, "").split(SOFT_SPLIT);
    phrases = parts.map(clean).filter(Boolean);
  }
  if (phrases.length < 2) return null;
  const [a, b, ...rest] = phrases;
  return { a, b, more: rest.slice(0, MAX_VS - 1), ...(range ? { range } : {}), ...(badRange ? { badRange } : {}) };
}

/**
 * The GP compare command for a sentence. `resolve` maps one company phrase to a symbol (or null when unknown).
 * Example: "apple vs microsoft 1 year" -> `AAPL GP 1Y VS MSFT`.
 */
export function compareCommand(input: string, resolve: (phrase: string) => string | null): CompareResult {
  const parse = parseCompare(input);
  if (!parse) return { error: "COMPARE NEEDS TWO NAMES, E.G. APPLE VS MICROSOFT 1 YEAR" };
  const phrases = [parse.a, parse.b, ...parse.more];
  const symbols: string[] = [];
  const unknown: string[] = [];
  for (const p of phrases) {
    const s = resolve(p);
    if (s) symbols.push(s.toUpperCase());
    else unknown.push(p.toUpperCase());
  }
  if (unknown.length) return { parse, error: `UNKNOWN COMPANY: ${unknown.join(", ")}` };
  if (new Set(symbols).size < 2) return { parse, error: "THE TWO NAMES ARE THE SAME SECURITY" };
  const [first, ...vs] = symbols;
  const command = `${first} GP${parse.range ? ` ${parse.range}` : ""} VS ${[...new Set(vs)].filter((s) => s !== first).join(" ")}`;
  return { parse, command };
}
