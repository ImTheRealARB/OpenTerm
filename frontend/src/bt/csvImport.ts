/**
 * IMPORT: the browser-side check of a bars CSV, for the live preview. The same rules as the backend's
 * `bt/csvimport.py` (which is the authority and checks again): columns date, open, high, low, close and an optional
 * volume in any order and case; dates `YYYY-MM-DD` (a time after it is ignored); prices finite and positive; high not
 * below low; no duplicate date. Rows are sorted by date. Pure: vitest covers it.
 */

export interface CsvBar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v?: number;
}

export interface ParsedBars {
  bars: CsvBar[];
  /** One message per problem, `ROW n:` with n counting data rows from 1. Nothing is stored while there are errors. */
  errors: string[];
  hasVolume: boolean;
}

export const REQUIRED = ["date", "open", "high", "low", "close"] as const;
const MAX_ERRORS = 20;
export const MAX_ROWS = 200_000;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?$/;

function validDate(y: number, m: number, d: number): boolean {
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

function num(raw: string): number | null {
  if (raw.trim() === "") return null;
  if (/^\s*[+-]?0[xbo]/i.test(raw)) return null; // JS reads 0x10 / 0b1 / 0o7 as numbers; the backend (Python float) does not
  const v = Number(raw);
  return Number.isFinite(v) ? v : null;
}

export function parseBarsCsv(text: string): ParsedBars {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim() !== "");
  const out: ParsedBars = { bars: [], errors: [], hasVolume: false };
  if (!lines.length) {
    out.errors.push("EMPTY FILE");
    return out;
  }
  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const missing = REQUIRED.filter((c) => !header.includes(c));
  if (missing.length) {
    out.errors.push(`NEEDS COLUMNS ${REQUIRED.join(",")}[,volume] (MISSING ${missing.join(",")}; HAS ${header.join(",")})`);
    return out;
  }
  if (lines.length - 1 > MAX_ROWS) {
    out.errors.push(`TOO MANY ROWS (${lines.length - 1}; MAX ${MAX_ROWS})`);
    return out;
  }
  const at = Object.fromEntries([...REQUIRED, "volume"].filter((c) => header.includes(c)).map((c) => [c, header.indexOf(c)]));
  out.hasVolume = "volume" in at;
  const seen = new Set<string>();
  const fail = (msg: string) => {
    if (out.errors.length < MAX_ERRORS) out.errors.push(msg);
  };
  for (let n = 1; n < lines.length; n++) {
    const cells = lines[n].split(",").map((c) => c.trim());
    if (cells.length < header.length) {
      fail(`ROW ${n}: HAS ${cells.length} COLUMNS, THE HEADER HAS ${header.length}`);
      continue;
    }
    const m = DATE_RE.exec(cells[at.date]);
    if (!m || !validDate(+m[1], +m[2], +m[3])) {
      fail(`ROW ${n}: BAD DATE '${cells[at.date]}' (USE YYYY-MM-DD)`);
      continue;
    }
    const day = `${m[1]}-${m[2]}-${m[3]}`;
    if (seen.has(day)) {
      fail(`ROW ${n}: DUPLICATE DATE ${day}`);
      continue;
    }
    seen.add(day);
    const px: Record<string, number> = {};
    let bad = false;
    for (const k of ["open", "high", "low", "close"]) {
      const v = num(cells[at[k]]);
      if (v === null) {
        fail(`ROW ${n}: BAD NUMBER IN ${k} '${cells[at[k]]}'`);
        bad = true;
        break;
      }
      px[k] = v;
    }
    if (bad) continue;
    if (Math.min(px.open, px.high, px.low, px.close) <= 0) {
      fail(`ROW ${n}: PRICES MUST BE POSITIVE`);
      continue;
    }
    if (px.high < px.low) {
      fail(`ROW ${n}: HIGH BELOW LOW`);
      continue;
    }
    const bar: CsvBar = { t: day, o: px.open, h: px.high, l: px.low, c: px.close };
    if (out.hasVolume && cells[at.volume] !== "") {
      const v = num(cells[at.volume]);
      if (v === null) {
        fail(`ROW ${n}: BAD NUMBER IN volume '${cells[at.volume]}'`);
        continue;
      }
      if (v < 0) {
        fail(`ROW ${n}: NEGATIVE VOLUME`);
        continue;
      }
      bar.v = v;
    }
    out.bars.push(bar);
  }
  out.bars.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  if (!out.errors.length && out.bars.length < 2) out.errors.push("NEEDS AT LEAST 2 ROWS");
  return out;
}
