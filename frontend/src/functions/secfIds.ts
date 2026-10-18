/**
 * SECF identifier helpers (pure). Mirrors backend/openterm/secf/ids.py: the panel decides locally whether a word is an
 * ISIN / CUSIP / SEDOL / FIGI; the server validates again before it spends a rate-limited OpenFIGI request.
 */

export type IdKind = "ISIN" | "CUSIP" | "SEDOL" | "FIGI";
export interface Ident {
  kind: IdKind;
  value: string;
  /** The check digit holds (FIGI: shape only). */
  valid: boolean;
}

const ISIN = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/;
const CUSIP = /^[A-Z0-9*@#]{8}[0-9]$/;
const SEDOL = /^[0-9B-DF-HJ-NP-TV-Z]{6}[0-9]$/;
const FIGI = /^[A-Z]{2}G[A-Z0-9]{8}[0-9]$/;

const alnum = (c: string) => (c >= "0" && c <= "9" ? Number(c) : c.charCodeAt(0) - 55); // A=10 .. Z=35

export function isinOk(s: string): boolean {
  if (!ISIN.test(s)) return false;
  const digits = [...s.slice(0, 11)].map((c) => String(alnum(c))).join("");
  let total = 0;
  for (let i = 0; i < digits.length; i++) {
    const d = Number(digits[digits.length - 1 - i]) * (i % 2 === 0 ? 2 : 1);
    total += Math.floor(d / 10) + (d % 10);
  }
  return (10 - (total % 10)) % 10 === Number(s[11]);
}

export function cusipCheck(base8: string): number {
  let total = 0;
  [...base8].forEach((c, i) => {
    let v = /[0-9A-Z]/.test(c) ? alnum(c) : c === "*" ? 36 : c === "@" ? 37 : 38;
    if (i % 2 === 1) v *= 2;
    total += Math.floor(v / 10) + (v % 10);
  });
  return (10 - (total % 10)) % 10;
}

export const cusipOk = (s: string) => CUSIP.test(s) && cusipCheck(s.slice(0, 8)) === Number(s[8]);

export function sedolOk(s: string): boolean {
  if (!SEDOL.test(s)) return false;
  const w = [1, 3, 1, 7, 3, 9];
  let total = 0;
  for (let i = 0; i < 6; i++) total += alnum(s[i]) * w[i];
  return (10 - (total % 10)) % 10 === Number(s[6]);
}

/** The identifier a word is, or null when it is a name or ticker. A right shape with a wrong check digit comes back with valid=false. */
export function classify(text: string): Ident | null {
  let t = text.trim().toUpperCase();
  if (t.startsWith("FIGI:")) {
    t = t.slice(5);
    return FIGI.test(t) ? { kind: "FIGI", value: t, valid: true } : null;
  }
  if (ISIN.test(t)) {
    if (isinOk(t)) return { kind: "ISIN", value: t, valid: true };
    if (t.startsWith("BBG") && FIGI.test(t)) return { kind: "FIGI", value: t, valid: true };
    return { kind: "ISIN", value: t, valid: false };
  }
  if (t.length === 9 && CUSIP.test(t)) return { kind: "CUSIP", value: t, valid: cusipOk(t) };
  if (t.length === 7 && SEDOL.test(t)) return { kind: "SEDOL", value: t, valid: sedolOk(t) };
  return null;
}

/** The identifiers of a query when EVERY word is one (a pasted list); otherwise null and the query is a name search. */
export function identsOf(query: string): Ident[] | null {
  const words = query.split(/[\s,;]+/).filter(Boolean);
  if (!words.length) return null;
  const out: Ident[] = [];
  for (const w of words) {
    const i = classify(w);
    if (!i) return null;
    if (!out.some((o) => o.kind === i.kind && o.value === i.value)) out.push(i);
  }
  return out;
}

const US_FAMILY = new Set(["US", "UN", "UW", "UQ", "UA", "UC", "UR", "UP", "UD", "UV", "UF", "UB"]);
// OpenFIGI exchange code -> Yahoo suffix. Only codes whose Yahoo suffix is certain; anything else has no mapping and says so.
const YAHOO_SUFFIX: Record<string, string> = {
  LN: ".L", GY: ".DE", FP: ".PA", JT: ".T", HK: ".HK", CT: ".TO", AU: ".AX", IN: ".NS", IB: ".BO", SW: ".SW",
  NA: ".AS", IM: ".MI", SM: ".MC", SS: ".ST", DC: ".CO", NO: ".OL", FH: ".HE",
};

/** The symbol to open for an OpenFIGI listing, or null when OpenTerm has no mapping for that exchange code. */
export function yahooSymbol(exchCode: string | null, ticker: string | null): string | null {
  if (!exchCode || !ticker) return null;
  const t = ticker.trim().toUpperCase().replace(/\s+/g, "-").replace(/\/$/, "");
  if (!t) return null;
  if (US_FAMILY.has(exchCode)) return t;
  const suffix = YAHOO_SUFFIX[exchCode];
  if (!suffix) return null;
  return exchCode === "HK" ? `${t.padStart(4, "0")}${suffix}` : `${t}${suffix}`;
}
