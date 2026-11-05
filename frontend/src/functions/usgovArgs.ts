/** USASP, FEDREG, FEC, CONGRESS: pure helpers shared by the four US government panels (no DOM, no network; vitest runs them). */
import type { CongressRow, FecItem } from "../net/api";

/** Every word after the function code is one query: `USASP lockheed martin` -> "lockheed martin". */
export function joinQuery(args: string[]): string {
  return args.filter(Boolean).join(" ").trim();
}

/**
 * US dollars as a short label: 34100007952 -> "$34.10B", 4500000 -> "$4.50M", 950 -> "$950". A missing amount is "" (never "$0"):
 * "not given" and "zero" are different things. Negative amounts (de-obligations) keep their sign.
 */
export function fmtUsd(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "";
  const a = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (a >= 1e12) return `${sign}$${(a / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`;
  return `${sign}$${a.toFixed(0)}`;
}

/** The first agency, plus how many more there are: ["A", "B", "C"] -> "A +2". */
export function agencyShort(agencies: string[]): string {
  if (agencies.length === 0) return "";
  return agencies.length === 1 ? agencies[0] : `${agencies[0]} +${agencies.length - 1}`;
}

/** "HR 9001" for a bill row: the label people type and the congress.gov site uses. */
export function billLabel(r: Pick<CongressRow, "type" | "number">): string {
  return `${r.type} ${r.number}`;
}

/** The command that opens a bill: "119 HR 9001" (the Congress number first, so an old bill is not mistaken for a current one). */
export function billCommandArgs(r: Pick<CongressRow, "congress" | "type" | "number">): string[] {
  return [String(r.congress), r.type, r.number];
}

/** What a FEC search row is, on one short label: a candidate's office or a committee's type, with the state and district when given. */
export function fecWhere(r: Pick<FecItem, "office" | "state" | "district">): string {
  const place = [r.state, r.district].filter(Boolean).join("-");
  return [r.office, place].filter(Boolean).join(" ");
}

/** A FEC "coverage to" date as the panel prints it, or "NOT GIVEN". */
export function coverage(date: string | null | undefined): string {
  return date ? date : "NOT GIVEN";
}

/** The type words FEDREG accepts as a first word (kept in step with `world/fedreg.py` TYPES by a vitest). */
export const FEDREG_TYPES = ["RULE", "PROPOSED", "NOTICE", "PRESDOC"] as const;
