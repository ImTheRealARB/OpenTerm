/** Pure logic of the SYNC panel: the command words, ages and the lines that describe a sync. No React, no network. */
import type { Broker, SyncDiff, SyncRecord } from "../net/syncApi";

export const SYNC_USAGE = "USAGE: SYNC [KITE|IBKR] [PORTFOLIO] [POS] [ACCT=U1234567] [GO]   (PORT SYNC KITE|IBKR works too)";
/** A successful sync older than this is shown as STALE: the broker may hold something else by now. */
export const STALE_AFTER_S = 24 * 3600;
const NAME_RE = /^[A-Z0-9][A-Z0-9_.-]{0,31}$/;

export interface SyncArgs {
  broker: Broker | null;
  portfolio: string | null;
  positions: boolean;
  account: string | null;
  go: boolean;
}

export function parseSyncArgs(args: string[]): SyncArgs | { error: string } {
  const out: SyncArgs = { broker: null, portfolio: null, positions: false, account: null, go: false };
  for (const raw of args) {
    const w = raw.toUpperCase();
    if (w === "KITE" || w === "IBKR") {
      if (out.broker && out.broker !== w.toLowerCase()) return { error: "ONE BROKER AT A TIME: SYNC KITE OR SYNC IBKR" };
      out.broker = w.toLowerCase() as Broker;
    } else if (w === "GO") out.go = true;
    else if (w === "POS" || w === "POSITIONS") out.positions = true;
    else if (w.startsWith("ACCT=")) {
      const a = raw.slice(5);
      if (!/^[A-Za-z0-9]{3,24}$/.test(a)) return { error: "ACCT= TAKES AN IBKR ACCOUNT ID, E.G. ACCT=U1234567" };
      out.account = a;
    } else if (NAME_RE.test(w) && !out.portfolio) out.portfolio = w;
    else return { error: `${raw.slice(0, 24).toUpperCase()}: NOT A BROKER OR PORTFOLIO NAME` };
  }
  if (out.go && !out.broker) return { error: "NAME THE BROKER TO RUN: SYNC KITE GO OR SYNC IBKR GO" };
  if (out.positions && out.broker === "ibkr") return { error: "POS IS FOR KITE (DAY POSITIONS). IBKR ALWAYS SYNCS EVERY POSITION" };
  if (out.account && out.broker === "kite") return { error: "ACCT= IS FOR IBKR" };
  return out;
}

/** "5M AGO", "3H AGO", "2D AGO"; "JUST NOW" under a minute. */
export function ageText(at: number, now: number): string {
  const s = Math.max(0, Math.round(now - at));
  if (s < 60) return "JUST NOW";
  if (s < 3600) return `${Math.floor(s / 60)}M AGO`;
  if (s < 86400) return `${Math.floor(s / 3600)}H AGO`;
  return `${Math.floor(s / 86400)}D AGO`;
}

export function isStale(rec: SyncRecord | null, now: number): boolean {
  return !!rec && now - rec.at > STALE_AFTER_S;
}

export function stamp(at: number): string {
  const d = new Date(at * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}Z`;
}

export function countsLine(rec: SyncRecord): string {
  const c = rec.counts;
  if (!c) return "";
  const parts = [`${c.imported} LOTS IMPORTED`, `${c.skipped} SKIPPED`, `${c.conflicts} CONFLICTS`, `${c.manual_kept} MANUAL KEPT`];
  if (rec.broker === "kite" && rec.holdings !== undefined) parts.push(`${rec.holdings} HOLDINGS`, `${rec.positions ?? 0} POSITIONS`);
  if (rec.broker === "ibkr" && rec.accounts) parts.push(`${rec.accounts.length} ACCOUNTS`);
  return parts.join(" · ");
}

const q = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 4 });

/** One line per difference against the previous sync: `+ INFY.NS`, `- TCS.NS`, `~ AAPL 10 -> 4`. */
export function diffLines(d: SyncDiff | null, limit = 30): string[] {
  if (!d) return [];
  const lines = [
    ...d.added.map((s) => `+ ${s}`),
    ...d.removed.map((s) => `- ${s}`),
    ...d.changed.map((c) => `~ ${c.symbol} ${q(c.qty_from)} -> ${q(c.qty_to)}${c.cost_from !== c.cost_to ? ` (COST ${c.cost_from ?? "-"} -> ${c.cost_to ?? "-"})` : ""}`),
  ];
  return lines.length > limit ? [...lines.slice(0, limit), `… ${lines.length - limit} MORE`] : lines;
}

export function noDifference(d: SyncDiff | null): boolean {
  return !!d && !d.added.length && !d.removed.length && !d.changed.length;
}

/** The headline of a broker's block: last good sync with its age and source, STALE when old, or the failure. */
export function headline(broker: Broker, lastOk: SyncRecord | null, lastErr: SyncRecord | null, now: number): { text: string; cls: "up" | "warn" | "err" | "dim" } {
  const name = broker === "kite" ? "KITE" : "IBKR";
  if (!lastOk) return { text: lastErr ? `${name} NEVER SYNCED · LAST TRY FAILED ${ageText(lastErr.at, now)}` : `${name} NEVER SYNCED`, cls: lastErr ? "err" : "dim" };
  const base = `${name} → ${lastOk.portfolio} · SYNCED ${stamp(lastOk.at)} (${ageText(lastOk.at, now)})`;
  if (lastErr && lastErr.at > lastOk.at) return { text: `ERR ${base} · LATER TRY FAILED ${ageText(lastErr.at, now)}`, cls: "err" };
  return isStale(lastOk, now) ? { text: `STALE ${base}`, cls: "warn" } : { text: base, cls: "up" };
}
