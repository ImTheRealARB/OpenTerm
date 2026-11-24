/**
 * Pure helpers of the recorder panel and of `REC=<id>` on FOOT / TAS / DOM (no React, no request layer: vitest imports it).
 *
 *   REC                       list running recordings and stored sessions
 *   REC BTCUSDT ON | OFF      start / stop recording that pair (crypto only; OFF BY DEFAULT: nothing records until you type ON)
 *   FOOT BTCUSDT REC=2026-11-24-101500        show a recorded session instead of live data
 *
 * A session's id on screen is its start stamp `YYYY-MM-DD-HHMMSS` (UTC). The server names a session `SYMBOL/STAMP`; a command may
 * also spell it that way (`REC=BTCUSDT/2026-11-24-101500`). The stamp alone is the default because a `/` inside a word reads as a
 * symbol formula (Phase 22) on the command line.
 */

const STAMP = String.raw`\d{4}-\d{2}-\d{2}-\d{6}`;
const REC_TOKEN = new RegExp(String.raw`^REC=(?:([A-Z0-9]{2,20})/)?(${STAMP})$`);

export interface RecSplit {
  rest: string[];
  stamp?: string;
  recSym?: string;
  /** set when a word starts with REC= but is not a session id */
  bad?: string;
}

/** Words with the `REC=...` token taken out, plus what the token said. */
export function splitRec(words: string[]): RecSplit {
  const rest: string[] = [];
  const out: RecSplit = { rest };
  for (const w of words) {
    if (!/^REC=/i.test(w)) {
      rest.push(w);
      continue;
    }
    const m = REC_TOKEN.exec(w.toUpperCase());
    if (!m) out.bad = "REC= NEEDS A SESSION ID LIKE 2026-11-24-101500 (SEE THE REC LIST)";
    else {
      out.recSym = m[1];
      out.stamp = m[2];
    }
  }
  return out;
}

/** The server's session id for a symbol as typed: `BTC-USDT` + stamp -> `BTCUSDT/<stamp>`. */
export function sessionId(sym: string, stamp: string, recSym?: string): string {
  return `${(recSym ?? sym).replace(/[^A-Z0-9]/gi, "").toUpperCase()}/${stamp}`;
}

/** The stamp of a server session id (`BTCUSDT/2026-11-24-101500` -> `2026-11-24-101500`). */
export const stampOf = (id: string): string => id.slice(id.indexOf("/") + 1);

export type RecAction = "LIST" | "ON" | "OFF";
export interface RecArgs {
  action: RecAction;
  sym: string;
  /** set when the words were not understood */
  error?: string;
}

/** `REC` | `REC BTCUSDT ON|OFF`. A symbol without ON / OFF is an error (starting a recording must be spelled out). */
export function parseRecArgs(args: string[]): RecArgs {
  const w = args.filter(Boolean).map((x) => x.toUpperCase());
  if (!w.length) return { action: "LIST", sym: "" };
  const last = w[w.length - 1];
  if (last === "ON" || last === "OFF") {
    const sym = w.slice(0, -1).join("");
    return sym ? { action: last, sym } : { action: "LIST", sym: "", error: `REC <SYMBOL> ${last}` };
  }
  return { action: "LIST", sym: "", error: "REC <SYMBOL> ON | OFF (REC ALONE LISTS RECORDINGS)" };
}

/** Bytes as a short size: `812 B`, `3.4 KB`, `12.1 MB`. */
export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** `2026-11-24` from epoch seconds (UTC). */
export const recDate = (epochS: number): string => new Date(epochS * 1000).toISOString().slice(0, 10);

/** The label every replayed panel shows: `RECORDED BY OPENTERM 2026-11-24`. */
export const recordedLabel = (startedEpochS: number): string => `RECORDED BY OPENTERM ${recDate(startedEpochS)}`;

/** Moves a snapshot index by `dir` inside 0..count-1 (DOM `,` / `.`); never leaves the range. */
export function stepIndex(index: number, dir: -1 | 1, count: number): number {
  return Math.min(count - 1, Math.max(0, index + dir));
}
