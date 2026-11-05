/** ADDR: pure argument and text helpers (no DOM, no network; vitest runs them). */

/** `ADDR 0x... [ARB]`, `ADDR GAS [BASE]`; with no words at all the panel shows the gas price. */
export function addrQuery(args: string[]): string {
  const q = args.filter(Boolean).join(" ").trim();
  return q || "GAS";
}

/** 0x1234...abcd for a table cell; the full value is in the CSV. */
export function shortHex(h: string | null | undefined, head = 8, tail = 6): string {
  if (!h) return "";
  return h.length <= head + tail + 3 ? h : `${h.slice(0, head)}...${h.slice(-tail)}`;
}

/** A native-coin amount: up to 6 decimals for small values, 4 for medium, 2 for big; "0" stays "0". */
export function fmtCoin(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  if (v === 0) return "0";
  const a = Math.abs(v);
  const digits = a >= 1000 ? 2 : a >= 1 ? 4 : 6;
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

/** Gas prices are gwei and are often below 1 on L2s and quiet days: keep 3 significant decimals. */
export function fmtGwei(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  return v >= 10 ? v.toFixed(1) : v >= 1 ? v.toFixed(2) : v.toFixed(4);
}

/** "3H", "12D" ago from an epoch-seconds time; "" when unknown. */
export function agoText(timeSec: number | null | undefined, nowSec: number): string {
  if (timeSec == null) return "";
  const s = Math.max(0, nowSec - timeSec);
  if (s < 90) return `${Math.round(s)}S`;
  if (s < 5400) return `${Math.round(s / 60)}M`;
  if (s < 129600) return `${Math.round(s / 3600)}H`;
  return `${Math.round(s / 86400)}D`;
}

/** UTC date and time of a transaction, e.g. "2025-09-29 06:46". */
export function txTime(timeSec: number | null | undefined): string {
  return timeSec == null ? "" : new Date(timeSec * 1000).toISOString().slice(0, 16).replace("T", " ");
}
