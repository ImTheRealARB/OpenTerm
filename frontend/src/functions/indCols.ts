/**
 * WL / Q indicator columns (Phase 27): `Q AAPL MSFT COLS=RSI14,PCT_SMA200,REL_VOL<0.5`, `WL TECH COLS=RSI14<30`.
 * Pure (argument split, cell text and colour, grid column defs) so vitest covers it; the values come from the server's
 * `scan.cols` job (`backend/openterm/scanner/cols.py` parses the columns and is the one place that refuses a bad one).
 */
import type { CellColor, Column } from "../components/Grid";
import type { ColsResult } from "../net/types";

type ColSpec = ColsResult["cols"][number];

/** Splits `COLS=...` off a panel's args: [AAPL, MSFT, COLS=RSI14] -> args [AAPL, MSFT], cols "RSI14" (the last COLS= wins). */
export function splitCols(args: string[]): { args: string[]; cols: string | null } {
  let cols: string | null = null;
  const rest: string[] = [];
  for (const a of args) {
    if (/^COLS=/i.test(a)) cols = a.slice(5).toUpperCase() || null;
    else rest.push(a);
  }
  return { args: rest, cols };
}

/** The columns as typed, before the server answers: same labels it will use (a bare REL_VOL means REL_VOL20). */
export function typedCols(cols: string): ColSpec[] {
  return cols.split(",").map((p) => p.trim()).filter(Boolean).map((p) => {
    const m = /^([A-Z_]+\d*)(<=|>=|<|>)?(-?\d+(?:\.\d+)?)?$/.exec(p);
    const label = (m?.[1] ?? p).replace(/^REL_VOL$/, "REL_VOL20");
    return { label, op: (m?.[2] as ColSpec["op"]) ?? null, num: m?.[3] != null ? Number(m[3]) : null };
  });
}

/** True when the column's comparison holds for v (no comparison or no value: false). */
export function holds(c: ColSpec, v: number | null | undefined): boolean {
  if (v == null || c.op == null || c.num == null) return false;
  if (c.op === "<") return v < c.num;
  if (c.op === ">") return v > c.num;
  if (c.op === "<=") return v <= c.num;
  return v >= c.num;
}

/** PCT_ columns are percent already; RET is a fraction (as in BT rules) shown as percent; REL_VOL is a multiple. */
export function cellText(label: string, v: number | null | undefined): string {
  if (v == null) return "—";
  const signed = (x: number) => `${x >= 0 ? "+" : ""}${x.toFixed(1)}%`;
  if (label.startsWith("PCT_")) return signed(v);
  if (label.startsWith("RET")) return signed(v * 100);
  if (label.startsWith("REL_VOL")) return `${v.toFixed(2)}x`;
  return Math.abs(v) >= 10_000 ? v.toFixed(0) : v.toFixed(2);
}

/** Grid columns for the result (or "…" placeholders while it loads). A met comparison colours the cell like a SCAN match. */
export function indColumns<R extends { symbol: string }>(res: ColsResult | null, cols: string | null): Column<R>[] {
  if (!cols) return [];
  const spec = res?.cols ?? typedCols(cols);
  return spec.map((c) => {
    const title = c.op ? `${c.label}${c.op}${c.num}` : c.label;
    const value = (r: R) => res?.rows[r.symbol]?.values[c.label];
    return {
      title,
      width: Math.max(9, title.length + 1),
      align: "right",
      text: (r: R) => (res ? cellText(c.label, value(r)) : "…"),
      color: (r: R): CellColor => {
        const v = value(r);
        return v == null ? "dim" : holds(c, v) ? "up" : "fg";
      },
    };
  });
}

/** The header note: progress, the error, or where the numbers came from (fixture data always said). */
export function colsNote(cols: string | null, state: { error: string | null; done: number; total: number; res: ColsResult | null }): string {
  if (!cols) return "";
  if (state.error) return `COLS ERR: ${state.error}`;
  if (!state.res) return `COLS LOADING ${state.done}/${state.total || "…"}`;
  const dates = Object.values(state.res.rows).map((r) => r.date).filter((d): d is string => !!d).sort();
  const fx = state.res.labels.fixtures ? ` · ${state.res.labels.fixtures}` : "";
  return `COLS: NEWEST DAILY BAR${dates.length ? ` (TO ${dates[dates.length - 1]})` : ""}${fx}`;
}
