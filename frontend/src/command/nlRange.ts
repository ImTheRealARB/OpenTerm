/**
 * "How far back?" in plain English -> a GP range. Pure (no React, no network); today's date is passed in so tests are stable.
 *
 * GP (the price chart) only has FIXED ranges: 1D 5D 1M 3M 6M YTD 1Y 2Y 5Y 10Y MAX. It has no "from 2019" and no "18 months".
 * So a request is mapped to the SMALLEST fixed range that still covers it ("4 years" -> 5Y, "since 2020" -> 10Y) and the
 * `why` text says so out loud, e.g. "since 2020: 10Y, the closest range". Nothing is silently dropped any more.
 *
 * Understood: "5 years", "5y", "five years", "a couple of years", "18 months", "2 weeks", "10 days", "last year / month / week",
 * "this year" (= year to date), "ytd", "last quarter", "a decade", "since 2020", "since march 2021", "from 2019 (to 2023)",
 * "5 years ago", "since ipo / inception / listing", "all time / max".
 */

/** The ranges GP accepts, kept in step with functions/gpArgs.ts RANGES by natural.test.ts. */
export const GP_RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"];

/** Fixed ranges that are plain "this many months back" (YTD is a calendar thing, handled apart). */
const SPANS: [string, number][] = [["1M", 1], ["3M", 3], ["6M", 6], ["1Y", 12], ["2Y", 24], ["5Y", 60], ["10Y", 120]];

/** Takes `re`'s first match out of the working text (state.s); returns the match or null. Shared with natural.ts. */
export function take(state: { s: string }, re: RegExp): RegExpExecArray | null {
  const m = re.exec(state.s);
  if (m) state.s = (state.s.slice(0, m.index) + " " + state.s.slice(m.index + m[0].length)).replace(/\s+/g, " ");
  return m;
}

export interface RangeFound {
  /** One of GP_RANGES. */
  range: string;
  /** Said when the asked-for span is not exactly a GP range ("since 2020: 10Y, the closest range"). */
  note?: string;
  /** "last quarter": also means "the latest quarter" to a financials request, so natural.ts may use it that way instead. */
  quarter?: boolean;
}

/** Smallest fixed range covering `months` months (MAX when longer than 10 years). */
export function coverMonths(months: number): string {
  for (const [r, m] of SPANS) if (months <= m + 1e-9) return r;
  return "MAX";
}

/** Same for a span given in days: 1 day -> 1D, up to 5 -> 5D, longer -> by months. */
function coverDays(days: number): string {
  if (days <= 1) return "1D";
  if (days <= 5) return "5D";
  return coverMonths(days / 30.44);
}

const NUM_WORDS: Record<string, number> = {
  a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12,
  thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19, twenty: 20,
  "a couple of": 2, "couple of": 2, "a couple": 2, couple: 2,
};
const NUM_WORD_RE = Object.keys(NUM_WORDS).sort((a, b) => b.length - a.length).join("|");

const MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const MONTH_RE = "(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?";
const monthIndex = (w?: string): number => (w ? MONTH_NAMES.indexOf(w.slice(0, 3)) : 0);

/** Optional lead-in that belongs to the range phrase, so it leaves the company words alone ("over the last 5 years"). */
const LEAD = "(?:(?:over|for|in|during|within) )?(?:the )?(?:(?:last|past|previous) )?";
const UNIT_SHORT = "(decades?|years?|yrs?|y|months?|mos?|mo|m|weeks?|wks?|w|days?|d)";
const UNIT_FULL = "(decades?|years?|yrs?|months?|weeks?|days?)";

const RE_SINCE_START = /\b(?:since|from) (?:the )?(?:ipo|inception|listing|listed|launch|founding|beginning|start|day one)\b|\bsince (?:it )?(?:ipo'?d|went public|listed)\b/;
const RE_SINCE_YEAR = new RegExp(
  `\\b(?:since|from|starting(?: in)?|beginning(?: in)?) (?:(?:early|mid|late) )?(?:(${MONTH_RE}) )?((?:19|20)\\d\\d)\\b` +
    `(?: (?:to|until|till|through|and) (?:(?:${MONTH_RE}) )?(?:(?:19|20)\\d\\d|now|today|present|date))?`,
);
const RE_YTD = /\b(?:year to date|ytd|this year)\b/;
const RE_ALL = /\b(?:max|maximum|all time|all-time|alltime|full history|since inception|lifetime)\b/;
const RE_QUARTER = /\b(?:the )?(?:last|past|previous|this) quarter\b/;
const RE_DECADE = /\b(?:the )?(?:last|past|previous) decade\b/;
const RE_HALF = /\bhalf (?:a |an )?year\b|\bhalf-year\b/;
const RE_DIGITS = new RegExp(`\\b${LEAD}(\\d+(?:\\.\\d+)?) ?${UNIT_SHORT}\\b( ago)?`);
const RE_WORDS = new RegExp(`\\b${LEAD}(${NUM_WORD_RE}) ${UNIT_FULL}\\b( ago)?`);
const RE_SIMPLE: [RegExp, string][] = [
  [/\b(?:today|intraday|todays|this morning)\b/, "1D"],
  [/\b(?:past|last) year\b/, "1Y"], // "this year" is YTD, matched earlier
  [/\b(?:this|past|last) month\b/, "1M"],
  [/\b(?:this|past|last) week\b/, "5D"],
];

/** `n` of `unit` as a GP range (and whether that is an exact fit). */
function fromUnit(n: number, unit: string): { range: string; exact: boolean } | null {
  if (!(n > 0)) return null;
  if (unit.startsWith("dec")) return rangeFor(n * 120); // decades
  if (unit[0] === "y") return rangeFor(n * 12);
  if (unit[0] === "m") return rangeFor(n); // "m", "mo", "mos", "month(s)"
  if (unit[0] === "w") {
    if (n === 1) return { range: "5D", exact: true }; // one week is the 5-trading-day button
    return { range: coverDays(n * 7), exact: false };
  }
  if (unit[0] === "d") {
    const range = coverDays(n);
    return { range, exact: (range === "1D" && n === 1) || (range === "5D" && n === 5) };
  }
  return null;
}

/** A span of `months` months -> the covering range; `exact` when it equals a button. */
function rangeFor(months: number): { range: string; exact: boolean } {
  const range = coverMonths(months);
  const exact = SPANS.some(([r, m]) => r === range && m === months);
  return { range, exact };
}

/** Months from the first day of (year, monthIdx) until `now` (fractional; a start in the future gives 0). */
function monthsSince(year: number, monthIdx: number, now: Date): number {
  return Math.max(0, (now.getFullYear() - year) * 12 + (now.getMonth() - monthIdx) + now.getDate() / 31);
}

/**
 * Finds the first range phrase in `st.s`, removes it, and returns the GP range for it (null when there is none).
 * `now` only matters for "since 2020"-style phrases.
 */
export function extractRange(st: { s: string }, now: Date): RangeFound | null {
  let m: RegExpExecArray | null;
  const said = (x: RegExpExecArray) => x[0].trim().replace(/\s+/g, " ");

  // Dates first: "since 2020", "from 2019 to 2023", "since march 2021".
  if ((m = take(st, RE_SINCE_START))) return { range: "MAX" };
  if ((m = RE_SINCE_YEAR.exec(st.s))) {
    const year = Number(m[2]);
    if (year >= 1970 && year <= now.getFullYear()) {
      take(st, RE_SINCE_YEAR);
      const months = monthsSince(year, monthIndex(m[1]), now);
      const range = coverMonths(months);
      const ranged = / (?:to|until|till|through|and) /.test(m[0]) ? "; GP always ends today" : "";
      return { range, note: `${said(m)}: ${range}, the closest range${ranged}` };
    }
  }

  // Calendar words.
  if ((m = take(st, RE_YTD))) return { range: "YTD" };
  if ((m = take(st, RE_ALL))) return { range: "MAX" };
  if ((m = take(st, RE_QUARTER))) return { range: "3M", quarter: true };
  if ((m = take(st, RE_DECADE))) return { range: "10Y" };
  if ((m = take(st, RE_HALF))) return { range: "6M" };

  // Counted spans: "5 years", "five years", "a couple of months", "18 months", "2 weeks ago".
  let hit: { r: { range: string; exact: boolean }; m: RegExpExecArray } | null = null;
  if ((m = take(st, RE_DIGITS))) {
    const r = fromUnit(Number(m[1]), m[2]);
    if (r) hit = { r, m };
  } else if ((m = take(st, RE_WORDS))) {
    const r = fromUnit(NUM_WORDS[m[1]], m[2]);
    if (r) hit = { r, m };
  }
  if (hit) {
    const { r, m: mm } = hit;
    return r.exact ? { range: r.range } : { range: r.range, note: `${said(mm)}: ${r.range}, the closest range` };
  }

  for (const [re, range] of RE_SIMPLE) if (take(st, re)) return { range };
  return null;
}
