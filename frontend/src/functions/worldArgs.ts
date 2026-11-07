/** Pure helpers for ECST / WECO / CENB (no DOM, no network): argument parsing, WECO sorting and cell formatting. */
import type { WecoCell, WecoRow } from "../net/types";

/** Indicator aliases the server knows (backend/openterm/world/stats.py INDICATORS). */
export const ECST_INDICATORS = ["GDP", "GDPG", "GDPPC", "CPI", "UNEMP", "POP", "DEBT", "CA", "TRADE", "GDPGROWTH", "INFLATION", "UNEMPLOYMENT"] as const;
const IS_IND = new Set<string>(ECST_INDICATORS);
// Same shape as backend `world/stats.py` DBN_REF; the dataset part allows `@` (OECD codes such as DSD_TAXBEN_NRR@DF_NRR).
const DBN = /^DBN:[A-Za-z0-9_-]+\/[A-Za-z0-9_.:@-]+\/[A-Za-z0-9_./-]+$/i;

export interface EcstArgs {
  country: string;
  ind: string;
  error: string | null;
}

/** `ECST <country...> <indicator>` or `ECST DBN:<provider>/<dataset>/<series>`. A country may be several words. */
export function parseEcstArgs(args: string[]): EcstArgs {
  const a = args.filter(Boolean);
  const usage = "USAGE: ECST <COUNTRY> <" + ["GDP", "GDPG", "GDPPC", "CPI", "UNEMP", "POP", "DEBT", "CA", "TRADE"].join("|") + "> OR ECST DBN:<PROVIDER>/<DATASET>/<SERIES>";
  if (!a.length) return { country: "", ind: "", error: usage };
  if (a.length === 1 && DBN.test(a[0])) return { country: "", ind: a[0], error: null };
  const last = a[a.length - 1];
  if (a.length >= 2 && IS_IND.has(last.toUpperCase())) return { country: a.slice(0, -1).join(" "), ind: last.toUpperCase(), error: null };
  if (a.length >= 2 && DBN.test(last)) return { country: "", ind: last, error: null };
  if (a.length === 1 && IS_IND.has(a[0].toUpperCase())) return { country: "", ind: a[0].toUpperCase(), error: "GIVE A COUNTRY, E.G. ECST USA " + a[0].toUpperCase() };
  return { country: a.join(" "), ind: "", error: "GIVE AN INDICATOR AFTER THE COUNTRY. " + usage };
}

/** WECO column sort. `col` is an index into the columns (0-based) or "name". Rows without a value always sort last. */
export function sortWeco(rows: WecoRow[], aliases: string[], col: number | "name", desc: boolean): WecoRow[] {
  const out = [...rows];
  if (col === "name") return out.sort((x, y) => (desc ? y.name.localeCompare(x.name) : x.name.localeCompare(y.name)));
  const k = aliases[col];
  return out.sort((x, y) => {
    const a = x.cells[k]?.v;
    const b = y.cells[k]?.v;
    if (a == null && b == null) return x.name.localeCompare(y.name);
    if (a == null) return 1;
    if (b == null) return -1;
    return desc ? b - a : a - b;
  });
}

export function fmtCell(c: WecoCell | null | undefined): string {
  if (!c) return "";
  const v = Math.abs(c.v) >= 100 ? c.v.toFixed(0) : c.v.toFixed(1);
  return `${v} (${c.year})`;
}

/** Large indicator values with a unit suffix (GDP in US$, population). */
export function fmtStat(v: number | null | undefined, unit: string): string {
  if (v == null || !Number.isFinite(v)) return "";
  const a = Math.abs(v);
  if (unit === "US$" || unit === "people") {
    if (a >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
    if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
    return v.toFixed(0);
  }
  return a >= 100 ? v.toFixed(1) : v.toFixed(2);
}
