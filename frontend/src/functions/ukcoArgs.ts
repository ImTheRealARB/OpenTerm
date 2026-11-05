/** UKCO: pure argument and text helpers (no DOM, no network; vitest runs them). */

/** `UKCO tesco`, `UKCO 00445790`, `UKCO SC123456`: every word after the code is one query. */
export function ukcoQuery(args: string[]): string {
  return args.filter(Boolean).join(" ").trim();
}

/** "2026-12-31" with a flag when the register says it is overdue; "" when there is no date. */
export function dueText(date: string | null | undefined, overdue: boolean | null | undefined): string {
  if (!date) return "";
  return overdue ? `${date} OVERDUE` : date;
}

/** Yes / No / "" for a register flag that may be missing (a missing flag is not "no"). */
export function yesNo(flag: boolean | null | undefined): string {
  return flag == null ? "NOT GIVEN" : flag ? "YES" : "NO";
}

/** Colour class for a company status: only "active" is plain, anything else (dissolved, liquidation ...) is a warning. */
export function statusClass(status: string | null | undefined): "fg" | "warn" {
  return !status || status.toLowerCase() === "active" ? "fg" : "warn";
}

/** A register code made readable for a header: "england-wales" -> "ENGLAND WALES". */
export function readable(code: string | null | undefined): string {
  return (code ?? "").replace(/[-_]/g, " ").toUpperCase();
}
