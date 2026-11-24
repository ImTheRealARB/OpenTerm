/**
 * Row keys shared by the Phase 30 boards whose rows point at another function (CTM -> CT, TSYS -> YAS, WPE -> DES).
 * The server puts the target on the row: `go_fn` (function code), `go_args` (its arguments) and `go_sym` (a security, optional).
 *   Enter  open that function in this panel (rows without a target fall back to the panel's default: open the row's link).
 */
import { navigate } from "../state/workspace";
import type { TableRow } from "../research/tablePayload";

/** The jump a row asks for, or null. Pure, so vitest can check it. */
export function rowTarget(row: TableRow | undefined): { fn: string; args: string[]; symbol: string | null } | null {
  if (!row || typeof row.go_fn !== "string" || !row.go_fn) return null;
  const args = Array.isArray(row.go_args) ? row.go_args.filter((a): a is string => typeof a === "string") : [];
  const symbol = typeof row.go_sym === "string" && row.go_sym ? row.go_sym : null;
  return { fn: row.go_fn, args, symbol };
}

export function macroRowKey(e: KeyboardEvent, panelId: number, row: TableRow | undefined, say: (text: string) => void): boolean {
  if (e.key !== "Enter" || e.ctrlKey || e.altKey || e.metaKey) return false;
  const t = rowTarget(row);
  if (!t) return false; // no target: ResearchPanel opens the row's link, if any
  say(`OPENING ${t.symbol ? `${t.symbol} ` : ""}${t.fn}${t.args.length ? ` ${t.args.join(" ")}` : ""}`);
  navigate(panelId, { fn: t.fn, security: t.symbol ? { symbol: t.symbol } : undefined, args: t.args });
  return true;
}
