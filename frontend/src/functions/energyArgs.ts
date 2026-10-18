/** Pure helpers for NRG and WETR (no DOM, no network): series aliases, number formats, the position bar, the place argument. */
import type { NrgRow, WxAlert } from "../net/api";

/** Alias -> FRED id (mirror of backend/openterm/world/energy.py SERIES). */
export const NRG_IDS: Record<string, string> = {
  WTI: "DCOILWTICO", BRENT: "DCOILBRENTEU", HH: "DHHNGSP", GASNY: "DGASNYH", GASGC: "DGASUSGULF", ULSD: "DDFUELNYH", HEAT: "DHOILNYH",
  JET: "DJFUELUSGULF", PROPANE: "DPROPANEMBTX", GASRET: "GASREGW", DIESELRET: "GASDESW",
};
const ID_SET = new Set(Object.values(NRG_IDS));

export interface NrgArgs {
  id: string | null;
  error: string | null;
}

/** `NRG` = the board; `NRG <alias|FRED id>` = open that series on the FRED chart. */
export function parseNrgArgs(args: string[]): NrgArgs {
  const a = args.filter(Boolean);
  if (!a.length) return { id: null, error: null };
  const k = a[0].toUpperCase();
  if (NRG_IDS[k]) return { id: NRG_IDS[k], error: null };
  if (ID_SET.has(k)) return { id: k, error: null };
  return { id: null, error: `UNKNOWN ENERGY SERIES ${k.slice(0, 24)}. USE: ${Object.keys(NRG_IDS).join(" ")}` };
}

const DECIMALS: Record<string, number> = { "$/BBL": 2, "$/MMBTU": 3, "$/GAL": 3 };

export function fmtPrice(v: number | null, unit: string): string {
  return v == null ? "" : v.toFixed(DECIMALS[unit] ?? 2);
}
export function fmtSigned(v: number | null, digits: number): string {
  return v == null ? "" : (v > 0 ? "+" : "") + v.toFixed(digits);
}
/** Where the last value sits inside its one-year range: ten cells, `#` up to the position. */
export function posBar(pos: number | null): string {
  if (pos == null) return "";
  const n = Math.max(0, Math.min(10, Math.round(pos / 10)));
  return "#".repeat(n) + ".".repeat(10 - n);
}
export function nrgChg(r: NrgRow): "up" | "down" | "dim" {
  return r.chg == null || r.chg === 0 ? "dim" : r.chg > 0 ? "up" : "down";
}

/** `WETR` args: the joined words are the place (a name or `lat,lon`); the server validates. */
export function placeArg(args: string[]): string {
  return args.filter(Boolean).join(" ").trim();
}

export function fmtTemp(c: number | null): string {
  return c == null ? "" : `${c.toFixed(1)}C`;
}
export function fmtDd(v: number | null): string {
  return v == null ? "" : v.toFixed(1);
}

const SEV: Record<string, "err" | "warn" | "fg" | "dim"> = { EXTREME: "err", SEVERE: "err", MODERATE: "warn", MINOR: "fg" };
export function alertColor(a: WxAlert): "err" | "warn" | "fg" | "dim" {
  return SEV[a.severity.toUpperCase()] ?? "dim";
}
export function alertLine(a: WxAlert): string {
  const until = a.ends ? ` UNTIL ${a.ends.slice(0, 16).replace("T", " ")}` : "";
  return `${a.severity.toUpperCase()} · ${a.event.toUpperCase()} · ${(a.area ?? "").toUpperCase().slice(0, 70)}${until}`;
}
