/**
 * Pure CSV serializer (RFC 4180): fields are quoted when they hold a comma, quote, CR/LF or edge
 * spaces; quotes are doubled; records end with CRLF. Kept free of DOM code so vitest can cover it.
 */
export type CsvCell = string | number | boolean | null | undefined;

/**
 * Spreadsheet formula injection guard: a text cell starting with = @ TAB CR, or with + / - not followed by
 * a number, gets a leading apostrophe. Numbers and signed figures like "-1.25" or "+3.4%" are left alone.
 */
export function neutralize(s: string): string {
  return /^[=@\t\r]/.test(s) || /^[+-](?![\d.])/.test(s) ? `'${s}` : s;
}

export function csvField(v: CsvCell): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  const s = neutralize(String(v));
  return /[",\r\n]|^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(header: string[], rows: CsvCell[][]): string {
  return [header, ...rows].map((r) => r.map(csvField).join(",")).join("\r\n") + "\r\n";
}

/** Safe download file name: letters, digits, dot, dash, underscore; at most 80 characters. */
export function csvFileName(name: string): string {
  const base = name.replace(/[^\w.-]+/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "export";
  return `${base}.csv`;
}
