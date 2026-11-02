/**
 * Pure helpers for the GUI shell (no React, no store imports, so vitest can test them).
 * The sidebar search and the symbol picker both end up running ordinary command-line text; these helpers only
 * decide WHICH text to run.
 */
import { fuzzyScore } from "../command/fuzzy";

/**
 * Lowest `fuzzyScore` that counts as a real match in the sidebar. fuzzyScore ranks exact > prefix > word-prefix >
 * substring > subsequence; subsequence ("A..A..P..L" scattered over a long title) is far too loose for a list the
 * user reads, and it would make a ticker like AAPL look like it matches random functions. Substrings score >= ~300.
 */
export const MIN_SCORE = 300;

export interface Searchable {
  code: string;
  title: string;
}

/**
 * Functions whose code or title matches `query`, best first. A code that equals or starts with the query is
 * boosted above title matches, so typing GP puts GP on top and typing "chart" lists chart functions.
 */
export function searchFunctions<T extends Searchable>(query: string, items: readonly T[], limit = 60): T[] {
  const q = query.trim();
  if (!q) return [];
  const scored: { item: T; s: number }[] = [];
  for (const item of items) {
    const byCode = fuzzyScore(q, item.code);
    // fuzzyScore: exact = 1000, prefix = 800 - length, so >= 700 means "exact or prefix" (looser matches score <= 600).
    const s = Math.max(byCode >= 700 ? byCode + 500 : -1, fuzzyScore(q, `${item.code} ${item.title}`));
    if (s >= MIN_SCORE) scored.push({ item, s });
  }
  // Equal scores keep the registry's own order, which is also how HELP lists them.
  scored.sort((a, b) => b.s - a.s);
  return scored.slice(0, limit).map((x) => x.item);
}

/**
 * What to run when Enter is pressed in the sidebar search:
 *  - several words, or a first word that IS a function code: the text as typed ("AAPL GP", "GP 5Y"), exactly like the command line;
 *  - otherwise the top match, if there is one ("chart" runs the first chart function);
 *  - otherwise the text as typed, so a ticker still loads and a typo gets the command line's own error message.
 */
export function sidebarEnter(text: string, top: Searchable | undefined, isFunction: (code: string) => boolean): string | null {
  const t = text.trim();
  if (!t) return null;
  if (/\s/.test(t) || isFunction(t.toUpperCase())) return t;
  return top ? top.code : t;
}

/**
 * What to run when Enter is pressed in the symbol picker. A bare ticker keeps the panel's current function when
 * that function works on a security (a GP chart of MSFT becomes a GP chart of AAPL), otherwise it is the plain
 * command-line form `AAPL`, which opens DES. Typed text with spaces is passed through as typed ("RELIANCE IN GP").
 */
export function symbolCommand(
  text: string,
  ctx: { currentFn?: string; isFunction: (code: string) => boolean; needsSecurity: (code: string) => boolean },
): string | null {
  const t = text.trim();
  if (!t) return null;
  if (/\s/.test(t) || ctx.isFunction(t.toUpperCase())) return t;
  return ctx.currentFn && ctx.needsSecurity(ctx.currentFn) ? `${t} ${ctx.currentFn}` : t;
}
