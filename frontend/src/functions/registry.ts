import type { ComponentType } from "react";
import type { SecurityRef } from "../command/markets";

export interface FunctionProps {
  panelId: number;
  security?: SecurityRef;
  args: string[];
}

export interface FunctionDef {
  code: string;
  title: string;
  /** Requires a security; falls back to the panel's sticky security. */
  needsSecurity: boolean;
  /** Free-form args description shown in HELP. */
  argsSchema?: string;
  /** Build phase this function ships in. Functions without `load` show a "not built yet" panel. */
  phase: number;
  /** Lazy module. Absent until implemented. */
  load?: () => Promise<{ default: ComponentType<FunctionProps> }>;
}

const defs: FunctionDef[] = [
  // P0
  { code: "HELP", title: "Function list / help for one function", needsSecurity: false, argsSchema: "[CODE]", phase: 1, load: () => import("./Help") },
  { code: "PERF", title: "Performance monitor", needsSecurity: false, phase: 1, load: () => import("./Perf") },
  { code: "SHORTCUTS", title: "Keyboard shortcuts", needsSecurity: false, phase: 1, load: () => import("./Shortcuts") },
  { code: "GP", title: "Price chart", needsSecurity: true, argsSchema: "[1D|5D|1M|6M|YTD|1Y|5Y|MAX] [interval] [vs SYM]", phase: 3 },
  { code: "DES", title: "Security description", needsSecurity: true, phase: 3 },
  { code: "Q", title: "Quote monitor", needsSecurity: false, argsSchema: "[SYM...]", phase: 3 },
  { code: "QR", title: "Quote recap", needsSecurity: true, phase: 3 },
  { code: "N", title: "News", needsSecurity: false, argsSchema: "[keyword]", phase: 5 },
  { code: "WL", title: "Watchlists", needsSecurity: false, argsSchema: "[list name]", phase: 5 },
  { code: "WEI", title: "World equity indices", needsSecurity: false, phase: 5 },
  // P1
  { code: "FA", title: "Financial analysis", needsSecurity: true, argsSchema: "[A|Q]", phase: 6 },
  { code: "FIL", title: "SEC filings", needsSecurity: true, phase: 6 },
  { code: "SEC", title: "SEC filings (alias of FIL)", needsSecurity: true, phase: 6 },
  { code: "PORT", title: "Portfolio", needsSecurity: false, phase: 8 },
  { code: "ECO", title: "Economic calendar", needsSecurity: false, phase: 7 },
  { code: "MACRO", title: "FRED series browser", needsSecurity: false, argsSchema: "[query]", phase: 7 },
  { code: "FRED", title: "Plot a FRED series", needsSecurity: false, argsSchema: "SERIES_ID", phase: 7 },
  { code: "ALRT", title: "Price / percent alerts", needsSecurity: false, phase: 8 },
  // P2
  { code: "MOV", title: "Top movers", needsSecurity: false, phase: 5 },
  { code: "FX", title: "Currency rates", needsSecurity: false, phase: 5 },
  { code: "FXC", title: "Currency cross matrix", needsSecurity: false, phase: 5 },
  { code: "CRYP", title: "Crypto board", needsSecurity: false, phase: 5 },
  { code: "CMDTY", title: "Commodities", needsSecurity: false, phase: 5 },
  { code: "RATES", title: "Yield curve", needsSecurity: false, phase: 7 },
  { code: "ERN", title: "Earnings calendar", needsSecurity: false, phase: 7 },
  { code: "HDS", title: "Holders (13F)", needsSecurity: true, phase: 6 },
  { code: "OWN", title: "Ownership / insiders", needsSecurity: true, phase: 6 },
  { code: "EQS", title: "Equity screener", needsSecurity: false, phase: 9 },
  { code: "CORR", title: "Correlation matrix", needsSecurity: false, argsSchema: "SYM SYM...", phase: 9 },
  { code: "COMP", title: "Peer comparison", needsSecurity: true, phase: 9 },
  { code: "HIST", title: "Historical price table", needsSecurity: true, phase: 9 },
  { code: "LAYOUT", title: "Save / load workspaces", needsSecurity: false, argsSchema: "SAVE|LOAD|DEL name", phase: 4 },
  { code: "MONITOR", title: "Alias of LAYOUT", needsSecurity: false, phase: 4 },
  { code: "SETTINGS", title: "Settings", needsSecurity: false, phase: 10 },
  { code: "SOURCES", title: "Data sources: health, latency, quota", needsSecurity: false, phase: 2, load: () => import("./Sources") },
  { code: "LOG", title: "Backend log", needsSecurity: false, phase: 2, load: () => import("./Log") },
];

export const FUNCTIONS = new Map(defs.map((d) => [d.code, d]));
export const FUNCTION_LIST = defs;
export const isFunction = (code: string) => FUNCTIONS.has(code);
