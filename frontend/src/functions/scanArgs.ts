/** `SCAN` and `MRR` arguments (Phase 27). Pure, so vitest covers it.
 *
 *   SCAN <UNIVERSE> <RULE>                       e.g. SCAN SPX RSI14<30 AND CLOSE>SMA200 · SCAN WL:TECH CLOSE>SMA50
 *   SCAN SAVE <NAME> <UNIVERSE> <RULE> [DAILY=HH:MM]   a saved scan; DAILY= sends its matches every weekday through DELIVERY
 *   SCAN SAVED · SCAN RUN <NAME> · SCAN DEL <NAME>
 *   MRR <UNIVERSE> [1D|1W|1M|3M|YTD|1Y]          index members ranked by return and contribution
 * Universe words: SPX NDX DJI RUT MID, MEMB:<ETF>, WL:<NAME>, LIST:A,B,C, NIFTY50, NIFTY500. The rule is BT's grammar (the
 * server checks it and answers with BT's own error text).
 */
export type ScanArgs =
  | { ok: true; act: "scan"; universe: string; rule: string }
  | { ok: true; act: "save"; name: string; universe: string; rule: string; daily: string | null }
  | { ok: true; act: "saved" }
  | { ok: true; act: "run" | "del"; name: string }
  | { ok: false; error: string };

export const SCAN_USAGE = "USAGE: SCAN <UNIVERSE> <RULE> · SCAN SAVE <NAME> <UNIVERSE> <RULE> [DAILY=HH:MM] · SCAN SAVED · SCAN RUN|DEL <NAME>";
export const UNIVERSES = "SPX NDX DJI RUT MID, MEMB:<ETF>, WL:<NAME>, LIST:A,B,C, NIFTY50, NIFTY500";
export const MRR_PERIODS = ["1D", "1W", "1M", "3M", "YTD", "1Y"];
const NAME_RE = /^[A-Z0-9_-]{1,30}$/;

export function parseScanArgs(args: string[]): ScanArgs {
  const a = args.map((x) => x.toUpperCase());
  if (!a.length) return { ok: true, act: "saved" };
  if (a[0] === "SAVED") return { ok: true, act: "saved" };
  if (a[0] === "RUN" || a[0] === "DEL") {
    return a.length === 2 && NAME_RE.test(a[1]) ? { ok: true, act: a[0] === "RUN" ? "run" : "del", name: a[1] } : { ok: false, error: `USAGE: SCAN ${a[0]} <NAME>` };
  }
  if (a[0] === "SAVE") {
    if (a.length < 4 || !NAME_RE.test(a[1])) return { ok: false, error: "USAGE: SCAN SAVE <NAME> <UNIVERSE> <RULE> [DAILY=HH:MM]" };
    const daily = a.find((x) => x.startsWith("DAILY="));
    if (daily && !/^DAILY=([01]\d|2[0-3]):[0-5]\d$/.test(daily)) return { ok: false, error: "DAILY= IS HH:MM (24-HOUR, THIS COMPUTER'S TIME), E.G. DAILY=22:15" };
    const rule = a.slice(3).filter((x) => !x.startsWith("DAILY=")).join(" ");
    return { ok: true, act: "save", name: a[1], universe: a[2], rule, daily: daily ? daily.slice(6) : null };
  }
  if (a.length < 2) return { ok: false, error: `${SCAN_USAGE} · UNIVERSE: ${UNIVERSES}` };
  return { ok: true, act: "scan", universe: a[0], rule: a.slice(1).join(" ") };
}

export function parseMrrArgs(args: string[]): { ok: true; universe: string; period: string } | { ok: false; error: string } {
  const a = args.map((x) => x.toUpperCase());
  if (!a.length || a.length > 2) return { ok: false, error: `USAGE: MRR <UNIVERSE> [${MRR_PERIODS.join("|")}] · UNIVERSE: ${UNIVERSES}` };
  const period = a[1] ?? "1D";
  if (!MRR_PERIODS.includes(period)) return { ok: false, error: `PERIOD MUST BE ${MRR_PERIODS.join(" ")}` };
  return { ok: true, universe: a[0], period };
}

/** GP study words for a scan's rule terms (GP draws a fixed set: other averages and terms are simply not drawn). */
export function gpStudies(terms: string[]): string[] {
  const out = new Set<string>();
  for (const t of terms) {
    if (["SMA20", "SMA50", "SMA100", "SMA200", "EMA20", "EMA50", "EMA200"].includes(t)) out.add(t);
    else if (t.startsWith("RSI")) out.add("RSI");
    else if (t.startsWith("ATR")) out.add("ATR");
  }
  return [...out];
}
