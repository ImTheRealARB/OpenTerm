import { MARKET_SUFFIX, isSymbolToken, resolveSecurity, type SecurityRef } from "./markets";
import { mapSector, parseSector } from "./sectors";

/**
 * Grammar:
 *   [N:] <SECURITY> [<MARKET>] [<SECTOR>] [<FUNCTION> [args...]]   (sector words: see sectors.ts, e.g. SPX INDEX GP)
 *   [N:] <FUNCTION> [args...]
 * A leading function code always wins over a ticker with the same letters.
 */
export type Parsed =
  | { ok: true; raw: string; target?: number; security?: SecurityRef; fn?: string; args: string[] }
  | { ok: false; raw: string; error: string };

export function parseCommand(input: string, isFunction: (code: string) => boolean): Parsed {
  const raw = input.trim();
  if (!raw) return { ok: false, raw, error: "EMPTY COMMAND" };

  let body = raw;
  let target: number | undefined;
  const m = /^([1-9])\s*:\s*(.*)$/.exec(raw);
  if (m) {
    target = Number(m[1]);
    body = m[2];
    if (!body) return { ok: false, raw, error: "NOTHING AFTER PANEL TARGET" };
  }

  const tokens = body.split(/\s+/);
  const first = tokens[0].toUpperCase();

  if (isFunction(first)) {
    return { ok: true, raw, target, fn: first, args: tokens.slice(1) };
  }

  if (!isSymbolToken(first)) return { ok: false, raw, error: `BAD SYMBOL: ${tokens[0]}` };

  let i = 1;
  let market: string | undefined;
  const t1 = tokens[i]?.toUpperCase();
  if (t1 && t1 in MARKET_SUFFIX && !isFunction(t1)) {
    market = t1;
    i++;
  }
  // Optional sector word (EQUITY, INDEX, CURNCY, COMDTY, GOVT, CORP ...). A function code of the same letters wins.
  const sector = tokens[i] && !isFunction(tokens[i].toUpperCase()) ? parseSector(tokens[i]) : undefined;
  if (sector) i++;

  let security = resolveSecurity(first, market);
  if (sector) {
    const mapped = mapSector(sector, first);
    if (!mapped.ok) return { ok: false, raw, error: mapped.error };
    // EQUITY keeps the market-suffix logic above; the other sectors choose the symbol themselves.
    if (sector !== "EQUITY") security = { symbol: mapped.symbol, market };
  }
  const fnTok = tokens[i]?.toUpperCase();
  if (!fnTok) return { ok: true, raw, target, security, args: [] };
  if (!isFunction(fnTok)) return { ok: false, raw, error: `UNKNOWN FUNCTION: ${fnTok}` };
  return { ok: true, raw, target, security, fn: fnTok, args: tokens.slice(i + 1) };
}
