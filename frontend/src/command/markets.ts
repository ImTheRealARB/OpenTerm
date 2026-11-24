/** Market tokens accepted after a security ("RELIANCE IN GP") mapped to the Yahoo-style suffix. */
export const MARKET_SUFFIX: Record<string, string> = {
  US: "",
  IN: ".NS", NS: ".NS", NSE: ".NS",
  BO: ".BO", BSE: ".BO",
  LN: ".L",
  JP: ".T", JT: ".T",
  HK: ".HK",
  GR: ".DE",
  CN: ".TO",
  AU: ".AX",
};

const SYMBOL_RE = /^[A-Z0-9^][A-Z0-9.\-=^&]*$/;

export interface SecurityRef {
  /** Canonical symbol after applying the market suffix, e.g. RELIANCE.NS */
  symbol: string;
  /** Market token as typed, e.g. IN */
  market?: string;
}

export function isSymbolToken(t: string): boolean {
  return SYMBOL_RE.test(t);
}

/**
 * Phase 22 symbol math: `AAPL/MSFT`, `2*GLD-SLV`, `(AAPL+MSFT)/2` typed as ONE word (no spaces) where a security goes.
 * Only the shape is checked here (symbol characters plus an operator); the server parses it and says exactly what is wrong.
 * A hyphen-only formula (`GLD-SLV`, `ES=F-NQ=F`) already passes `isSymbolToken`, and the server's minus rule decides it.
 * The first character must be a symbol character, `(` or `-`, so a leading `/` (the grid's command key) is never a formula.
 */
export function isFormulaToken(t: string): boolean {
  return /^[A-Z0-9^(-][A-Z0-9.\-=^&_+*/()]*$/i.test(t) && /[A-Z]/i.test(t) && /[+*/()]/.test(t);
}

/**
 * The same idea for a word AFTER a function code (`GP AAPL/MSFT`): stricter, because function arguments may hold brackets
 * (`GP SMA(20)`). It needs `+ * /`, or the `=F-` / `=X-` of a futures or FX spread (`GP ES=F-NQ=F`).
 */
export function isFormulaArg(t: string): boolean {
  return isFormulaToken(t) && (/[+*/]/.test(t) || /=[FX]-/i.test(t));
}

export function resolveSecurity(token: string, market?: string): SecurityRef {
  const t = token.toUpperCase();
  // Already explicit (RELIANCE.NS, BTC-USD, ^GSPC, EURUSD=X) or a formula (a market suffix would land on its last leg only): leave untouched.
  if (!market || /[.\-=^+*/()]/.test(t)) return { symbol: t, market };
  return { symbol: t + (MARKET_SUFFIX[market] ?? ""), market };
}
