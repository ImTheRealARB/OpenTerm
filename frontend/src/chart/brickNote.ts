/**
 * Brick-chart helpers (Phase 21), kept OUT of chartTypes.ts: that file is loaded at startup (settings), and a module
 * loaded at startup carries every export any lazy chunk uses. Only the chart chunk (ChartView, GP, bricks.ts) needs these.
 */
import type { ChartType } from "./chartTypes";

/** The "brick" types: a new mark is made when PRICE moves, not when the clock ticks, so the time axis is not linear. */
const BRICK_TYPES: readonly ChartType[] = ["RENKO", "KAGI", "PNF", "LINEBREAK", "RANGE"];
export const isBrickType = (t: ChartType): boolean => BRICK_TYPES.includes(t);

/**
 * The box (brick size, reversal amount or range) a brick transform actually used. The transforms return it so the screen can say
 * what it drew: with no BOX= argument the size comes from ATR(14) of the source bars and the reader cannot guess it.
 */
export interface BoxUsed {
  /** Price units. 0 or NaN means no valid size could be found (flat data), so no bricks were made. */
  size: number;
  /** true = taken from ATR(period) of the source bars; false = given by the user (BOX=). */
  atr: boolean;
  period: number;
  /** Point and figure only: boxes of reversal needed to start a new column. */
  rev?: number;
}

/** 2.4137 -> "2.41", 1234.5678 -> "1234.6", 0.004213 -> "0.00421" (always plain digits, never "1.23e+3"). */
function fmtBox(x: number): string {
  if (!Number.isFinite(x)) return "n/a";
  if (x >= 100) return x.toFixed(1);
  if (x >= 1) return x.toFixed(2);
  return String(Number(x.toPrecision(3)));
}

/**
 * The line shown on screen above a brick chart, e.g.
 * `RENKO BOX 2.41 (ATR 14) · BUILT FROM 1d BARS · NON-LINEAR TIME AXIS`.
 * `interval` is the source bar length (the bars the bricks were built from), `box` what the transform reported,
 * `made` how many bricks / columns came out and `capped` whether the 100,000-mark safety limit was hit.
 */
export function brickNote(t: ChartType, interval: string, box: BoxUsed | null, made?: { count: number; capped: boolean }): string {
  const size = box ? `${fmtBox(box.size)}${box.atr ? ` (ATR ${box.period})` : ""}` : "";
  const parts: string[] = [];
  if (t === "RENKO") parts.push(`RENKO BOX ${size}`);
  else if (t === "KAGI") parts.push(`KAGI REVERSAL ${size}`);
  else if (t === "PNF") parts.push(`P&F BOX ${size}`, `${box?.rev ?? 3}-BOX REVERSAL`);
  else if (t === "LINEBREAK") parts.push("3-LINE BREAK");
  else if (t === "RANGE") parts.push(`RANGE BARS ${size}`);
  parts.push(`BUILT FROM ${interval} BARS`);
  // Range bars need the order prices were visited inside each source bar, which bars do not record: say it is assumed.
  if (t === "RANGE") parts.push("INTRABAR PATH ASSUMED: OPEN, NEARER EXTREME, FAR EXTREME, CLOSE");
  parts.push("NON-LINEAR TIME AXIS");
  if (made?.capped) parts.push("STOPPED AT 100,000 MARKS: BOX TOO SMALL");
  else if (made && made.count === 0) parts.push("NOTHING DRAWN: PRICE NEVER MOVED A FULL BOX");
  return parts.join(" · ");
}

/** The line shown above a volume-candle chart; counts the bars with no volume (they are drawn hollow at normal width). */
export function volCandleNote(volumes: ArrayLike<number>): string {
  let none = 0;
  for (let i = 0; i < volumes.length; i++) if (!(volumes[i] > 0)) none++;
  return "VOLUME CANDLES · BODY WIDTH = VOLUME / LARGEST VOLUME IN VIEW" + (none ? ` · ${none} BARS WITH NO VOLUME DRAWN HOLLOW AT NORMAL WIDTH` : "");
}
