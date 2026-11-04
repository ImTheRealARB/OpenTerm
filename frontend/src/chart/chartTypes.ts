export type ChartType = "CANDLE" | "HOLLOW" | "OHLC" | "LINE" | "AREA" | "BASELINE" | "HEIKIN";
export const CHART_TYPES: ChartType[] = ["CANDLE", "HOLLOW", "OHLC", "LINE", "AREA", "BASELINE", "HEIKIN"];

/** Names shown in the GUI dropdown. */
export const CHART_TYPE_LABELS: Record<ChartType, string> = {
  CANDLE: "Candles",
  HOLLOW: "Hollow candles",
  OHLC: "Bars",
  LINE: "Line",
  AREA: "Area",
  BASELINE: "Baseline",
  HEIKIN: "Heikin Ashi",
};

/** Types drawn from open/high/low/close (the rest draw only the close). */
export const isOhlcType = (t: ChartType): boolean => t === "CANDLE" || t === "HOLLOW" || t === "OHLC" || t === "HEIKIN";
