/**
 * Row-number gutter for the quote grids (Q, WL, WEI, FX, CMDTY): the numbers 1) 2) 3) down the left edge. Pure on purpose
 * (no DOM, no `window`), so vitest can test every rule.
 *
 * Typing a number then Enter already works in every list panel, with or without the gutter: that is the app-wide number-select
 * (`keys/numberSelect.ts`, owned by App.tsx: "3" Enter = row 3, "ROW 3" / "NO ROW 9" in the message line). The gutter only shows which
 * number is which row, and uses the SAME numbering: data rows only, a section header (a "band" such as "Americas") keeps its
 * position on screen but has no number and uses none up.
 */
import type { Mode, RowNumbers } from "../settings/schema";

/**
 * Is the gutter shown? `auto` follows the interface mode: on in Terminal, off in GUI (a beginner's GUI has no use for it).
 * `on` / `off` are the explicit overrides of the setting.
 */
export function rowNumbersEffective(setting: RowNumbers, mode: Mode): boolean {
  return setting === "on" || (setting === "auto" && mode === "terminal");
}

/**
 * The number each row shows: `nums[i]` = 1, 2, 3 ... for data rows, 0 for header rows. Built once per row change (not per paint).
 */
export function buildNumbering(count: number, isHeader: (i: number) => boolean): Int32Array {
  const nums = new Int32Array(count);
  let n = 0;
  for (let i = 0; i < count; i++) if (!isHeader(i)) nums[i] = ++n;
  return nums;
}

/** Characters the gutter needs: the largest number's digits plus the closing ")" (so "12)" is 3). 0 = no data rows, no gutter. */
export function gutterChars(nums: Int32Array): number {
  let max = 0;
  for (let i = nums.length - 1; i >= 0; i--) {
    if (nums[i] > 0) {
      max = nums[i];
      break;
    }
  }
  return max === 0 ? 0 : String(max).length + 1;
}
