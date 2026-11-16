/**
 * Canvas drawing for the small in-cell graphics on the boards (WEI, FX, CMDTY): the %CHG bar, the 2DAY sparkline and the
 * one-letter data-status flag. The numbers come from the pure rules in `components/microGraphics.ts` (tested there); this file only
 * reads the live row and issues canvas calls. Each function is a `Column.draw` / `text` / `color` hook: no allocation per paint
 * (the bounds object is one shared scratch), only fillRect and one stroked path, default line width.
 */
import type { CellColor, Column } from "../components/Grid";
import { barSpan, sparkBounds, sparkX, sparkY, statusFlag, type Bounds } from "../components/microGraphics";
import { dirColor, pct, price, rowId, rowLive, type QRow } from "./quoteRows";

/** A board row: a quote row plus the closes of the last two sessions (undefined = none arrived, so the cell stays blank). */
export interface SparkRow extends QRow {
  spark?: number[];
}

type Draw = NonNullable<Column<SparkRow>["draw"]>;

/** Pixels kept free above and below the sparkline and at its ends. */
const SPARK_PAD = 3;
const scratch: Bounds = { min: 0, max: 0, n: 0 };

/** Direction colour for the line and bar: up / down by the day's %CHG; a flat or unknown day uses the quiet colour. */
const lineColor = (r: QRow): CellColor => {
  const c = dirColor(pct(r));
  return c === "val" ? "dim" : c;
};

/** %CHG bar: from the cell centre, right (green) for a rise, left (red) for a fall; length by |%CHG| (clamped, see `BAR_FULL_PCT`). */
export const drawChangeBar: Draw = (ctx, row, x, y, w, h, colors) => {
  const span = barSpan(pct(row), w);
  if (!span) return;
  const bh = Math.max(4, Math.round(h * 0.5));
  ctx.fillStyle = colors[span.up ? "up" : "down"];
  ctx.fillRect(x + span.x, y + Math.floor((h - 1 - bh) / 2), span.w, bh);
};

/**
 * 2DAY sparkline: the closes of the last two sessions, scaled to the cell. The final point follows the live price while the stream
 * is up (the same number the LAST column shows); every other point is the snapshot. No points (or fewer than two) = nothing drawn.
 */
export const drawSpark: Draw = (ctx, row, x, y, w, h, colors) => {
  const pts = row.spark;
  if (!pts || pts.length < 2) return;
  const last = price(row);
  const b = sparkBounds(pts, last, scratch);
  if (b.n < 2) return;
  const n = pts.length;
  ctx.strokeStyle = colors[lineColor(row)];
  ctx.beginPath();
  let pen = false; // false = the next finite point starts a new sub-path (a skipped point breaks the line, it is never bridged)
  for (let i = 0; i < n; i++) {
    const v = i === n - 1 && last != null && Number.isFinite(last) ? last : pts[i];
    if (!Number.isFinite(v)) {
      pen = false;
      continue;
    }
    const px = x + sparkX(i, n, w, SPARK_PAD);
    const py = y + sparkY(v, b.min, b.max, h - 1, SPARK_PAD);
    if (pen) ctx.lineTo(px, py);
    else ctx.moveTo(px, py);
    pen = true;
  }
  ctx.stroke();
};

/** The data-status letter shown after LAST: "d" delayed, "c" close, blank otherwise (table in `microGraphics.ts`). */
export function flagText(r: QRow): string {
  return statusFlag({
    missing: !!r.error || !r.q,
    live: rowLive(r, rowId(r)),
    stale: !!r.stale,
    tradeTime: r.q?.market_time ?? null,
    now: Date.now() / 1000,
  });
}

export const flagColor = (r: QRow): CellColor => (flagText(r) === "d" ? "warn" : "dim");
