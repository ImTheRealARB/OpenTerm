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

export function resolveSecurity(token: string, market?: string): SecurityRef {
  const t = token.toUpperCase();
  // Already explicit (RELIANCE.NS, BTC-USD, ^GSPC, EURUSD=X): leave untouched.
  if (!market || /[.\-=^]/.test(t)) return { symbol: t, market };
  return { symbol: t + (MARKET_SUFFIX[market] ?? ""), market };
}
