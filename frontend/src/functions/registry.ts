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
  /** Warm during idle time after startup. Off for heavy modules (GP pulls in the chart library). */
  idlePreload?: boolean;
}

const defs: FunctionDef[] = [
  // P0
  { code: "HELP", title: "Function list / help for one function", needsSecurity: false, argsSchema: "[CODE]", phase: 1, load: () => import("./Help") },
  { code: "PERF", title: "Performance monitor", needsSecurity: false, argsSchema: "[GRID rows | CHART bars]", phase: 1, load: () => import("./Perf") },
  { code: "SHORTCUTS", title: "Keyboard shortcuts", needsSecurity: false, phase: 1, load: () => import("./Shortcuts") },
  { code: "GP", title: "Price chart", needsSecurity: true, argsSchema: "[1D..MAX] [D|W|MO|5MIN|1H] [VS SYM] [CANDLE|OHLC|LINE|AREA] [LOG] [SMA20 SMA50 EMA20 BB RSI MACD VWAP]", phase: 3, load: () => import("./GP"), idlePreload: false },
  { code: "DES", title: "Security description", needsSecurity: true, phase: 3, load: () => import("./DES") },
  { code: "Q", title: "Quote monitor (live)", needsSecurity: false, argsSchema: "[SYM...]", phase: 3, load: () => import("./Q") },
  { code: "QR", title: "Quote recap (live)", needsSecurity: true, phase: 3, load: () => import("./QR") },
  { code: "N", title: "News", needsSecurity: false, argsSchema: "[TOP | keywords]", phase: 5, load: () => import("./N") },
  { code: "WL", title: "Watchlists", needsSecurity: false, argsSchema: "[NAME] [ADD|RM SYM...] | DEL NAME", phase: 5, load: () => import("./WL") },
  { code: "WEI", title: "World equity indices", needsSecurity: false, phase: 5, load: () => import("./WEI") },
  // P1
  { code: "FA", title: "Financial analysis", needsSecurity: true, argsSchema: "[A|Q] [IS|BS|CF]", phase: 6, load: () => import("./FA") },
  { code: "FIL", title: "SEC filings", needsSecurity: true, argsSchema: "[FORM]", phase: 6, load: () => import("./FIL") },
  { code: "SEC", title: "SEC filings (alias of FIL)", needsSecurity: true, argsSchema: "[FORM]", phase: 6, load: () => import("./FIL") },
  { code: "PORT", title: "Portfolio (live P&L, CSV import/export)", needsSecurity: false, argsSchema: "[NAME] [ADD SYM QTY [COST] [CCY] | RM SYM... | EXPORT | IMPORT | BASE CCY] | DEL NAME", phase: 8, load: () => import("./PORT") },
  { code: "ECO", title: "Economic calendar", needsSecurity: false, argsSchema: "[1-62] [MAJOR] [YYYY-MM-DD]", phase: 7, load: () => import("./ECO") },
  { code: "MACRO", title: "FRED series browser", needsSecurity: false, argsSchema: "[query]", phase: 7, load: () => import("./MACRO") },
  { code: "FRED", title: "Plot a FRED series", needsSecurity: false, argsSchema: "SERIES_ID [1Y|2Y|5Y|10Y|20Y|MAX]", phase: 7, load: () => import("./FRED"), idlePreload: false },
  { code: "ALRT", title: "Price / percent alerts", needsSecurity: false, argsSchema: "[SYM > PRICE | SYM < PRICE | SYM +PCT% | SYM -PCT% | DEL ID | REARM ID | CLEAR]", phase: 8, load: () => import("./ALRT") },
  // P2
  { code: "MOV", title: "Top movers", needsSecurity: false, argsSchema: "[GAINERS|LOSERS|ACTIVE|DOLLAR|NDX100]", phase: 5, load: () => import("./MOV") },
  { code: "FX", title: "Currency rates", needsSecurity: false, phase: 5, load: () => import("./FX") },
  { code: "FXC", title: "Currency cross matrix", needsSecurity: false, argsSchema: "[CCY ...]", phase: 5, load: () => import("./FXC") },
  { code: "CRYP", title: "Crypto board", needsSecurity: false, argsSchema: "[USD|INR|EUR ...]", phase: 5, load: () => import("./CRYP") },
  { code: "CMDTY", title: "Commodities", needsSecurity: false, phase: 5, load: () => import("./CMDTY") },
  { code: "RATES", title: "Yield curve", needsSecurity: false, phase: 7, load: () => import("./RATES") },
  { code: "ERN", title: "Earnings calendar", needsSecurity: false, argsSchema: "[TODAY|TOMORROW|+N|-N|YYYY-MM-DD]", phase: 7, load: () => import("./ERN") },
  { code: "HDS", title: "Holders (13F)", needsSecurity: true, phase: 6, load: () => import("./HDS") },
  { code: "OWN", title: "Ownership / insiders", needsSecurity: true, phase: 6, load: () => import("./OWN") },
  { code: "EQS", title: "Equity screener", needsSecurity: false, phase: 9 },
  { code: "CORR", title: "Correlation matrix", needsSecurity: false, argsSchema: "SYM SYM...", phase: 9 },
  { code: "COMP", title: "Peer comparison", needsSecurity: true, phase: 9 },
  { code: "HIST", title: "Historical price table", needsSecurity: true, phase: 9 },
  { code: "LAYOUT", title: "Save / load named workspaces", needsSecurity: false, argsSchema: "[SAVE|LOAD|DEL] name", phase: 4, load: () => import("./Layout") },
  { code: "MONITOR", title: "Alias of LAYOUT", needsSecurity: false, argsSchema: "[SAVE|LOAD|DEL] name", phase: 4, load: () => import("./Layout") },
  { code: "SETTINGS", title: "Settings", needsSecurity: false, phase: 10 },
  { code: "SOURCES", title: "Data sources: health, latency, quota", needsSecurity: false, phase: 2, load: () => import("./Sources") },
  { code: "LOG", title: "Backend log", needsSecurity: false, phase: 2, load: () => import("./Log") },
];

export const FUNCTIONS = new Map(defs.map((d) => [d.code, d]));

const loaded = new Map<string, ComponentType<FunctionProps>>();
const loading = new Map<string, Promise<ComponentType<FunctionProps>>>();

/** Loads (once) and remembers a function module so later renders are synchronous. */
export function loadModule(code: string): Promise<ComponentType<FunctionProps>> {
  const hit = loaded.get(code);
  if (hit) return Promise.resolve(hit);
  let p = loading.get(code);
  if (!p) {
    const def = FUNCTIONS.get(code);
    if (!def?.load) return Promise.reject(new Error("not built"));
    p = def.load().then((m) => {
      loaded.set(code, m.default);
      return m.default;
    });
    p.catch(() => loading.delete(code)); // allow a retry after a failed chunk download
    loading.set(code, p);
  }
  return p;
}

export const loadedModule = (code: string) => loaded.get(code);
export const FUNCTION_LIST = defs;
export const isFunction = (code: string) => FUNCTIONS.has(code);
