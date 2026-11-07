/**
 * The one list of chart ranges (GP buttons, the GP command line, plain-English parsing, the SETTINGS default).
 * It lives in its own tiny file with NO imports so startup code (settings, the natural-language parser) can use it
 * without pulling in functions/gpArgs.ts, which is a separate lazy chunk.
 * The backend copy is `CHART_RANGES` in backend/openterm/settings_store.py; test_ts_mirrors.py keeps them equal.
 */
export const CHART_RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"] as const;
export type ChartRange = (typeof CHART_RANGES)[number];

/** The same list typed as plain strings, for code that checks user text against it (`includes`, `indexOf`, `Set`). */
export const GP_RANGES: readonly string[] = CHART_RANGES;
