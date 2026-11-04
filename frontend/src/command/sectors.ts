/**
 * Market-sector words for the command grammar:  <SECURITY> [<MARKET>] [<SECTOR>] [<FUNCTION>]
 *
 *   SPX INDEX GP         -> ^GSPC
 *   EURUSD CURNCY GP     -> EURUSD=X
 *   CL1 COMDTY GP        -> CL=F
 *   AAPL US EQUITY GP    -> AAPL
 *   US10Y GOVT GP        -> ^TNX
 *
 * Pure module (no React, no network) so vitest can test it. The parser calls `parseSector` for the
 * word and `mapSector` to turn the typed name into the symbol form our data providers use (Yahoo style).
 */

export type Sector = "EQUITY" | "INDEX" | "CURNCY" | "COMDTY" | "GOVT" | "CORP" | "CRYPTO";

/**
 * Words people type, mapped to a sector. The short forms (EQ, IDX, CCY, CMD, GOV) are ours.
 * Do not add a word that is also a function code (FX, CMDTY, CRYP ...): the parser would hide the function.
 */
export const SECTOR_WORDS: Readonly<Record<string, Sector>> = Object.freeze({
  EQUITY: "EQUITY", EQ: "EQUITY",
  INDEX: "INDEX", IDX: "INDEX",
  CURNCY: "CURNCY", CCY: "CURNCY",
  COMDTY: "COMDTY", CMD: "COMDTY",
  GOVT: "GOVT", GOV: "GOVT",
  CORP: "CORP",
  CRYPTO: "CRYPTO",
});

/** The sector for a typed word (case-insensitive), or undefined when it is not a sector word. */
export function parseSector(word: string | undefined): Sector | undefined {
  return word ? SECTOR_WORDS[word.toUpperCase()] : undefined;
}

/** Popular index names -> Yahoo symbols. */
const INDEXES: Readonly<Record<string, string>> = Object.freeze({
  SPX: "^GSPC", SPY: "^GSPC", INDU: "^DJI", DJI: "^DJI", DJIA: "^DJI",
  CCMP: "^IXIC", COMP: "^IXIC", NDX: "^NDX", RTY: "^RUT", VIX: "^VIX",
  UKX: "^FTSE", FTSE: "^FTSE", DAX: "^GDAXI", CAC: "^FCHI", NKY: "^N225", N225: "^N225",
  HSI: "^HSI", SHCOMP: "000001.SS", SENSEX: "^BSESN", NIFTY: "^NSEI", NSEI: "^NSEI", BSESN: "^BSESN",
});

/** Futures roots whose code differs from Yahoo's (CO1 = Brent in the classic spelling). */
const COMMODITY_ROOTS: Readonly<Record<string, string>> = Object.freeze({
  CO: "BZ", BRENT: "BZ", WTI: "CL", XAU: "GC", GOLD: "GC", XAG: "SI", SILVER: "SI",
});

/** US Treasury yields we can show (Yahoo yield indices). Anything else gets a clear error. */
const GOVT_YIELDS: Readonly<Record<string, string>> = Object.freeze({
  US3M: "^IRX", T3M: "^IRX", USGG3M: "^IRX",
  US5Y: "^FVX", T5Y: "^FVX", USGG5YR: "^FVX",
  US10Y: "^TNX", T10Y: "^TNX", USGG10YR: "^TNX",
  US30Y: "^TYX", T30Y: "^TYX", USGG30YR: "^TYX",
});

export type SectorMapping = { ok: true; symbol: string } | { ok: false; error: string };

/**
 * Turns the typed security name into our symbol form for a sector.
 * A token that already looks like a provider symbol (has ^ = . or -) is passed through untouched.
 * For EQUITY the caller keeps its normal market-suffix logic, so this returns the token as is.
 */
export function mapSector(sector: Sector, typed: string): SectorMapping {
  const t = typed.toUpperCase();
  const explicit = /[.\-=^]/.test(t); // RELIANCE.NS, BTC-USD, ^GSPC, EURUSD=X: already a symbol
  switch (sector) {
    case "EQUITY":
    case "CRYPTO":
      return { ok: true, symbol: t };
    case "INDEX":
      return { ok: true, symbol: explicit ? t : (INDEXES[t] ?? `^${t}`) };
    case "CURNCY":
      if (explicit) return { ok: true, symbol: t };
      // USD/JPY style: 6 letters = a pair, 3 letters = the rate against USD (Yahoo writes JPY=X).
      if (/^[A-Z]{6}$/.test(t) || /^[A-Z]{3}$/.test(t)) return { ok: true, symbol: `${t}=X` };
      return { ok: false, error: `CURNCY: ${t} IS NOT A CURRENCY PAIR (E.G. EURUSD)` };
    case "COMDTY": {
      if (explicit) return { ok: true, symbol: t };
      // CL1 = front-month crude: root + "1". Yahoo writes CL=F.
      const m = /^([A-Z]{1,5})1$/.exec(t);
      const root = m ? m[1] : t;
      return { ok: true, symbol: `${COMMODITY_ROOTS[root] ?? root}=F` };
    }
    case "GOVT": {
      const y = GOVT_YIELDS[t];
      if (y) return { ok: true, symbol: y };
      if (explicit) return { ok: true, symbol: t }; // ^TNX typed out
      return { ok: false, error: `GOVT: NO FREE QUOTE FOR ${t} (US3M US5Y US10Y US30Y WORK; TRY RATES FOR CURVES)` };
    }
    case "CORP":
      return { ok: false, error: "CORP: NO FREE CORPORATE BOND DATA SOURCE (ZERO KEYS: EQUITY CREDIT IS NOT AVAILABLE)" };
  }
}
