/**
 * Phase 29 filings functions: pure argument parsing (no DOM, no network; vitest runs it).
 *
 * The command line splits on spaces, so a quoted phrase arrives as several words (`"going`, `concern"`). `joinArgs` puts the line back
 * together and `splitWords` takes the quoted phrase out. `KEY=value` words may stand anywhere. Dates are checked by the server
 * (YYYY-MM-DD), so a typo is answered with its own message instead of being guessed here.
 *
 *   FTS "going concern" FORM=10-K FROM=2024-01-01 TO=2024-12-31 [AAPL]      (CO=AAPL also names the company)
 *   MA [SYMBOL] [FROM=..] [TO=..]          with no symbol: market-wide deal filings of the last 90 days
 *   BIO <CIK | NAME WORDS> [FROM=..] [TO=..]
 *   ESG <SYMBOL> [YEAR=2023] [NAME=<company words>]
 */

export interface FtsArgs {
  q: string;
  forms: string;
  start: string;
  end: string;
  symbol: string;
}

const KV = /^(FORMS?|FROM|TO|CO|YEAR|NAME)=(.*)$/i;
const TICKER = /^[A-Z][A-Z0-9.-]{0,6}$/;

export function joinArgs(args: string[]): string {
  return args.filter(Boolean).join(" ");
}

interface Split {
  phrase: string;
  words: string[];
  kv: Record<string, string>;
}

/** Quoted phrase (if any), the other bare words, and the KEY=value pairs (keys upper-cased, later ones win). */
export function splitWords(args: string[]): Split {
  let text = joinArgs(args);
  let phrase = "";
  const m = /"([^"]*)"/.exec(text);
  if (m) {
    phrase = m[1].trim();
    text = text.slice(0, m.index) + " " + text.slice(m.index + m[0].length);
  }
  text = text.replace(/"/g, " "); // a stray quote is dropped, never sent
  const words: string[] = [];
  const kv: Record<string, string> = {};
  for (const w of text.split(/\s+/).filter(Boolean)) {
    const k = KV.exec(w);
    if (k) kv[k[1].toUpperCase()] = k[2];
    else words.push(w);
  }
  return { phrase, words, kv };
}

export function parseFtsArgs(args: string[]): FtsArgs {
  const { phrase, words, kv } = splitWords(args);
  // With a quoted phrase, a bare upper-case word after it is the company ("... TO=2024-12-31 AAPL"); without one every bare word is search text.
  const ticker = phrase ? words.find((w) => TICKER.test(w)) : undefined;
  return {
    q: phrase || words.join(" "),
    forms: kv.FORM ?? kv.FORMS ?? "",
    start: kv.FROM ?? "",
    end: kv.TO ?? "",
    symbol: (kv.CO ?? ticker ?? "").toUpperCase(),
  };
}

export const FTS_USAGE = 'USAGE: FTS "<WORDS>" [FORM=10-K] [FROM=YYYY-MM-DD] [TO=YYYY-MM-DD] [TICKER], E.G. FTS "going concern" FORM=10-K FROM=2024-01-01 TO=2024-12-31';

/** MA: the symbol is the panel's security, else the first ticker-looking bare word. Empty = market-wide. */
export function parseMaArgs(args: string[], security?: string): { symbol: string; start: string; end: string } {
  const { words, kv } = splitWords(args);
  return { symbol: (security ?? words.find((w) => TICKER.test(w.toUpperCase())) ?? "").toUpperCase(), start: kv.FROM ?? "", end: kv.TO ?? "" };
}

/** BIO: a number is a CIK, anything else is the owner's name (quotes dropped). */
export function parseBioArgs(args: string[]): { q: string; start: string; end: string } {
  const { phrase, words, kv } = splitWords(args);
  return { q: phrase || words.join(" "), start: kv.FROM ?? "", end: kv.TO ?? "" };
}

export const BIO_USAGE = 'USAGE: BIO <CIK> OR BIO "<OWNER NAME>" [FROM=YYYY-MM-DD] [TO=YYYY-MM-DD], E.G. BIO 1214156';

/** ESG: symbol from the security (or first ticker-looking word), optional YEAR= and NAME= (the company words EPA's parent text is searched for). */
export function parseEsgArgs(args: string[], security?: string): { symbol: string; name: string; year: string } {
  const { phrase, words, kv } = splitWords(args);
  const symbol = (security ?? words.find((w) => TICKER.test(w.toUpperCase())) ?? "").toUpperCase();
  return { symbol, name: kv.NAME || phrase, year: kv.YEAR ?? "" };
}

/** Query parameters without the empty ones (the server treats a missing parameter and an empty one the same, but the URL stays short). */
export function compact(p: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== ""));
}
