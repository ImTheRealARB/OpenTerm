/** CDEP / FUND / LIQ / STBL / DEFI: pure argument handling and table shaping (no DOM, no network; vitest runs it). */

export interface CdepArgs {
  pair: string;
  levels: number;
}

/** `CDEP [PAIR] [N]`: pair as the server reads it (BTCUSDT, BTC-USDT, BTC), N = ladder rows shown (5..100, default 25). */
export function parseCdepArgs(args: string[]): CdepArgs {
  const a = args.filter(Boolean);
  let levels = 25;
  const words: string[] = [];
  for (const w of a) {
    if (/^\d{1,3}$/.test(w)) levels = Math.min(100, Math.max(5, Number(w)));
    else words.push(w.toUpperCase());
  }
  return { pair: words.join("") || "BTCUSDT", levels };
}

/** `FUND [SYM]`, `LIQ [SYM]`, `STBL [CHAIN]`, `DEFI [CHAIN|PROJECT]`: the words as one argument. */
export function joinArg(args: string[]): string {
  return args.filter(Boolean).join(" ").trim();
}

export type Level = [number, number, number, number];
export interface LadderRow {
  bid: Level | null;
  ask: Level | null;
}

/** Bids and asks side by side, best price on the first row. */
export function ladder(bids: Level[], asks: Level[], n: number): LadderRow[] {
  const len = Math.min(n, Math.max(bids.length, asks.length));
  const out: LadderRow[] = [];
  for (let i = 0; i < len; i++) out.push({ bid: bids[i] ?? null, ask: asks[i] ?? null });
  return out;
}

/** A text bar for the cumulative notional of a level against the deeper side's total (width `w`). */
export function depthBar(cum: number | undefined, max: number, w = 10): string {
  if (cum == null || !(max > 0)) return "";
  return "#".repeat(Math.max(0, Math.min(w, Math.round((cum / max) * w))));
}

/** Signed percent with fixed digits; empty for null. */
export function sPct(v: number | null | undefined, digits = 2): string {
  return v == null || !Number.isFinite(v) ? "" : (v > 0 ? "+" : "") + v.toFixed(digits) + "%";
}

/** Up / down / flat color class of a signed number (color carries meaning only). */
export function signClass(v: number | null | undefined): "up" | "down" | "fg" {
  return v == null || v === 0 ? "fg" : v > 0 ? "up" : "down";
}

/** Next funding as a countdown: `3H12M`, `45M`; empty when unknown or passed. */
export function countdown(nextMs: number | null | undefined, nowMs: number): string {
  if (!nextMs || nextMs <= nowMs) return "";
  const m = Math.floor((nextMs - nowMs) / 60_000);
  return m >= 60 ? `${Math.floor(m / 60)}H${String(m % 60).padStart(2, "0")}M` : `${m}M`;
}

/** Seconds as a span: `42S`, `12M`, `3.5H`. */
export function span(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}S`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}M`;
  return `${(seconds / 3600).toFixed(1)}H`;
}

/** UTC `YYYY-MM-DD HH:MM:SS` for event times (venue times are UTC). */
export function utc(ms: number | null | undefined): string {
  return ms ? new Date(ms).toISOString().slice(0, 19).replace("T", " ") : "";
}
