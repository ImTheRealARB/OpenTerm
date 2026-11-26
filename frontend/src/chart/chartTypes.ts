/**
 * The GP chart types. This file is tiny on purpose: startup code (settings, GP args, the GUI dropdown) imports it,
 * so it must not pull in the chart library or the brick maths (`bricks.ts`, `customSeries.ts`).
 * The same list is mirrored in backend/openterm/settings_store.py (test_ts_mirrors.py keeps the two equal).
 */
export type ChartType =
  | "CANDLE" | "HOLLOW" | "OHLC" | "LINE" | "AREA" | "BASELINE" | "HEIKIN"
  | "RENKO" | "KAGI" | "PNF" | "LINEBREAK" | "RANGE"
  | "COLUMNS" | "HIGHLOW" | "STEP" | "VOLCANDLE";
export const CHART_TYPES: ChartType[] = [
  "CANDLE", "HOLLOW", "OHLC", "LINE", "AREA", "BASELINE", "HEIKIN",
  "RENKO", "KAGI", "PNF", "LINEBREAK", "RANGE",
  "COLUMNS", "HIGHLOW", "STEP", "VOLCANDLE",
];

/** Names shown in the GUI dropdown. */
export const CHART_TYPE_LABELS: Record<ChartType, string> = {
  CANDLE: "Candles",
  HOLLOW: "Hollow candles",
  OHLC: "Bars",
  LINE: "Line",
  AREA: "Area",
  BASELINE: "Baseline",
  HEIKIN: "Heikin Ashi",
  RENKO: "Renko",
  KAGI: "Kagi",
  PNF: "Point and figure",
  LINEBREAK: "Three line break",
  RANGE: "Range bars",
  COLUMNS: "Columns",
  // The chart library always draws a close tick on a bar, so this type is honest about showing it: high, low AND close.
  HIGHLOW: "High-low-close bars",
  STEP: "Step line",
  VOLCANDLE: "Volume candles",
};

/**
 * Types drawn from open/high/low/close with the library's own bar series (the rest draw only the close, or are custom).
 * HIGHLOW is in here because its series still needs the real open (the open tick is just hidden).
 */
export const isOhlcType = (t: ChartType): boolean => t === "CANDLE" || t === "HOLLOW" || t === "OHLC" || t === "HEIKIN" || t === "HIGHLOW";
