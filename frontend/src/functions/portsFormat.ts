/** Pure helpers for PORTS (kept out of the panel so vitest can test them without a browser). Sparkline, ship counts, percent
 *  and colour come from shipFormat.ts (same PortWatch data shape); only the port-specific parts live here. */

/** The search words the user typed after PORTS (`PORTS port said` -> "port said"). Blank = the 25 busiest ports. */
export function queryArg(args: string[]): string {
  return args.join(" ").trim();
}

/** Compact tonnage for the import / export estimates: 9.68M, 412k, 950. Blank when PortWatch gave no number (never a guess). */
export function fmtTons(v: number | null): string {
  if (v == null) return "";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}k`;
  return v.toFixed(0);
}

/** "Rotterdam, The Netherlands" style label for a row; the country is left out when PortWatch has none. */
export function portLabel(name: string, country: string | null): string {
  return country ? `${name}, ${country}` : name;
}

/** The line shown above the table: what the user is looking at and how many rows it holds. */
export function headline(mode: "top" | "search", query: string, n: number): string {
  return mode === "top" ? `${n} BUSIEST PORTS, LAST 7 DAYS ON RECORD` : `${n} PORT${n === 1 ? "" : "S"} MATCHING "${query.toUpperCase()}"`;
}
