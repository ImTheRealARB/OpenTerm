/**
 * MF: pure argument and text helpers (no DOM, no network, so vitest can run them; the panel is MF.tsx).
 *
 *   MF <words>          search Indian mutual fund scheme names (every word must match); Enter opens the highlighted fund
 *   MF <scheme code>    open one fund: latest NAV, 1D..5Y returns and the NAV chart
 *
 * A scheme code is the number AMFI gives each scheme (5 or 6 digits, e.g. 122639). The server applies the same rule (`world/mfund.py norm_query`).
 */

export const MF_USAGE = "USAGE: MF <FUND NAME WORDS> (E.G. MF PARAG PARIKH) OR MF <SCHEME CODE> (E.G. MF 122639)";

/** Longest NAV age (in days) that is still normal: AMFI publishes in the evening, so a Monday morning shows Friday's NAV (3 days) and a holiday adds one or two. */
export const NAV_NORMAL_AGE_DAYS = 4;

export interface MfArgs {
  kind: "search" | "fund";
  /** The words, or the scheme code with leading zeros dropped. */
  q: string;
  error: string | null;
}

export function parseMfArgs(args: string[]): MfArgs {
  const q = args.filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  if (/^\d+$/.test(q)) {
    if (q.length < 4 || q.length > 7) return { kind: "fund", q, error: "A SCHEME CODE HAS 5 OR 6 DIGITS. " + MF_USAGE };
    return { kind: "fund", q: String(Number(q)), error: null };
  }
  if (q.length < 3) return { kind: "search", q, error: "GIVE A FUND NAME (3+ LETTERS) OR A SCHEME CODE. " + MF_USAGE };
  return { kind: "search", q, error: null };
}

/** `+1.07%` / `-3.40%`; a missing return is a plain dash, never a number. */
export function fmtPct(p: number | null): string {
  if (p == null || !Number.isFinite(p)) return "-";
  return `${p > 0 ? "+" : ""}${p.toFixed(2)}%`;
}

/** NAV with the four decimals AMFI publishes (older schemes show more digits upstream; four is what funds quote). */
export function fmtNav(n: number | null): string {
  return n == null || !Number.isFinite(n) ? "-" : n.toFixed(4);
}

/** Whole days from an ISO date (`2026-11-03`) to `nowMs`, counted on UTC calendar days. Never negative. */
export function navAgeDays(iso: string, nowMs: number): number {
  const day = Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));
  const today = Math.floor(nowMs / 86_400_000) * 86_400_000;
  return Math.max(0, Math.round((today - day) / 86_400_000));
}

/** "TODAY" / "1 DAY OLD" / "5 DAYS OLD" for the NAV date line. */
export function navAgeText(days: number): string {
  return days === 0 ? "TODAY" : `${days} DAY${days === 1 ? "" : "S"} OLD`;
}

/** ISO date of an epoch-seconds stamp (the CSV export of the NAV series). */
export function isoOfEpoch(t: number): string {
  return new Date(t * 1000).toISOString().slice(0, 10);
}

/** "15 SCHEMES MATCH "PARAG PARIKH"", or "FIRST 200 OF 612 SCHEMES MATCH ..." when the server cut the list. */
export function searchHeadline(total: number, shown: number, query: string): string {
  const q = `"${query.toUpperCase()}"`;
  if (total === 0) return `NO SCHEME NAME HAS ALL THE WORDS ${q}`;
  if (shown < total) return `FIRST ${shown} OF ${total} SCHEMES MATCH ${q}: ADD WORDS TO NARROW IT`;
  return `${total} SCHEME${total === 1 ? "" : "S"} MATCH ${q}`;
}
