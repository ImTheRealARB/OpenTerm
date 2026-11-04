/**
 * Sector keys (F2, F3 ...): put a sector word on the command line.
 *
 *   "SPX"        + F3 (INDEX)  -> "SPX INDEX "
 *   "AAPL US"    + F2 (EQUITY) -> "AAPL US EQUITY "
 *   "SPX INDEX"  + F4 (CURNCY) -> "SPX CURNCY "      (an existing sector word is replaced)
 *   "AAPL GP"    + F2          -> "AAPL EQUITY GP"   (the word goes before the function)
 *
 * Pure (no DOM) so vitest can test it. The caller passes `isMarket` and `isFunction` so this file does not
 * import the registry.
 */
import type { Sector } from "./sectors";
import { parseSector } from "./sectors";

export type SectorEdit = { ok: true; text: string } | { ok: false; error: string };

export function applySectorWord(
  line: string,
  sector: Sector,
  stickySymbol: string | undefined,
  isMarket: (t: string) => boolean,
  isFunction: (t: string) => boolean,
): SectorEdit {
  // Keep a leading "2:" panel target as typed.
  const m = /^(\s*[1-9]\s*:\s*)?(.*)$/.exec(line)!;
  const prefix = m[1] ?? "";
  let tokens = m[2].trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) {
    // Empty line: use the panel's security (so F3 on a GP panel of ^GSPC gives "^GSPC INDEX ").
    if (!stickySymbol) return { ok: false, error: `TYPE A SECURITY FIRST, THEN ${sector}` };
    tokens = [stickySymbol];
  }
  if (isFunction(tokens[0].toUpperCase())) return { ok: false, error: `${sector}: TYPE A SECURITY BEFORE THE FUNCTION` };
  let i = 1; // tokens[0] is the security
  if (tokens[i] && isMarket(tokens[i].toUpperCase()) && !isFunction(tokens[i].toUpperCase())) i++;
  const existing = tokens[i] && !isFunction(tokens[i].toUpperCase()) ? parseSector(tokens[i]) : undefined;
  tokens.splice(i, existing ? 1 : 0, sector);
  // A trailing space lets the user type the function straight away.
  return { ok: true, text: prefix + tokens.join(" ") + " " };
}
