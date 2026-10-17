/** Number/time formatting shared by grids and panels. Pure, allocation-light, monospace-friendly. */

const DASH = "—";

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  const d = a >= 1000 ? 2 : a >= 1 ? 2 : a >= 0.01 ? 4 : 6;
  return loc(v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
}

/** FX rates and crosses: more decimals for smaller numbers (1.0852, 150.51, 0.011364). */
export function fmtRate(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  const d = a >= 100 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : a >= 0.1 ? 5 : a >= 0.001 ? 6 : 8;
  return loc(v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
}

export function fmtChg(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return (v > 0 ? "+" : "") + fmtPrice(v);
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return loc((v > 0 ? "+" : "") + v.toFixed(2) + "%");
}

export function fmtBig(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e12) return loc((v / 1e12).toFixed(2) + "T");
  if (a >= 1e9) return loc((v / 1e9).toFixed(2) + "B");
  if (a >= 1e6) return loc((v / 1e6).toFixed(2) + "M");
  if (a >= 1e3) return loc((v / 1e3).toFixed(1) + "K");
  return loc(v.toFixed(0));
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return loc(v.toFixed(digits));
}

const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short" });

/** Today's times as HH:MM:SS, older ones as DD MMM (local display zone). */
export function fmtTime(epochMs: number | null | undefined): string {
  if (!epochMs) return DASH;
  const d = new Date(epochMs);
  return Date.now() - epochMs < 18 * 3600_000 ? timeFmt.format(d) : dateFmt.format(d);
}

export function fmtAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}S`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}M`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}H`;
  return `${Math.round(seconds / 86400)}D`;
}

export const sign = (v: number | null | undefined): -1 | 0 | 1 => (v == null || v === 0 ? 0 : v > 0 ? 1 : -1);

// --- Phase 10: number format (SETTINGS) ---
// Formatters build en-US strings ("1,234.56"); `loc` swaps the separators only when the user chose others,
// so the default path costs one comparison.
let THOUSANDS_SEP = ",";
let DECIMAL_MARK = ".";

export function setNumberFormat(thousands: string, decimal: string): void {
  THOUSANDS_SEP = thousands;
  DECIMAL_MARK = decimal;
}

function loc(s: string): string {
  if (THOUSANDS_SEP === "," && DECIMAL_MARK === ".") return s;
  return s.replace(/[,.]/g, (c) => (c === "," ? THOUSANDS_SEP : DECIMAL_MARK));
}
