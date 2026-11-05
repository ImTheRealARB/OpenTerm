/** Pure formatting for SHIP (kept out of the panel so vitest can test it without a browser). */

const BLOCKS = "▁▂▃▄▅▆▇█";

/** A tiny bar chart in text: one block per day, tallest = busiest day in the window. Missing days show a dot. */
export function spark(series: [string, number | null][], width = 28): string {
  const vals = series.slice(-width).map((s) => s[1]);
  const nums = vals.filter((v): v is number => v != null);
  if (nums.length === 0) return "";
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  return vals
    .map((v) => (v == null ? "·" : BLOCKS[hi === lo ? 3 : Math.round(((v - lo) / (hi - lo)) * (BLOCKS.length - 1))]))
    .join("");
}

/** One decimal for averages ("41.3"); blank when unknown. */
export function fmtShips(v: number | null): string {
  return v == null ? "" : v.toFixed(1);
}

/** Signed percent with one decimal ("+12.4%"); blank when there is no base to compare with. */
export function fmtPct(v: number | null): string {
  return v == null ? "" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/** Colour name for the change column: a move of 15% or more either way is coloured (up or down); colour says size of move, not good or bad. */
export function chgColor(v: number | null): "fg" | "up" | "down" | "dim" {
  if (v == null) return "dim";
  if (v <= -15) return "down";
  if (v >= 15) return "up";
  return "fg";
}
