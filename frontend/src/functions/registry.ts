import type { ComponentType } from "react";
import type { SecurityRef } from "../command/markets";
import { ALIASES } from "./aliases";

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
  { code: "PERF", title: "Performance monitor", needsSecurity: false, argsSchema: "[GRID rows | CHART bars | CALC]", phase: 1, load: () => import("./Perf") },
  { code: "SHORTCUTS", title: "Keyboard shortcuts", needsSecurity: false, phase: 1, load: () => import("./Shortcuts") },
  { code: "GP", title: "Price chart", needsSecurity: true, argsSchema: "[1D..MAX] [D|W|MO|5MIN|1H] [VS SYM] [CANDLE|OHLC|LINE|AREA] [LOG] [SMA20 SMA50 EMA20 BB RSI MACD VWAP ATR STOCH ADX OBV CCI WILLR MFI KELT DONCH SUPERTREND PSAR ICHIMOKU PAT:CANDLE PAT:SMC]", phase: 3, load: () => import("./GP"), idlePreload: false },
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
  { code: "RATES", title: "Yield curve", needsSecurity: false, argsSchema: "[EUR|GBP|CAD|JPY|SPRD|AUCT|NS <ccy>]", phase: 7, load: () => import("./RATES") },
  { code: "ERN", title: "Earnings calendar", needsSecurity: false, argsSchema: "[TODAY|TOMORROW|+N|-N|YYYY-MM-DD]", phase: 7, load: () => import("./ERN") },
  { code: "HDS", title: "Holders (13F)", needsSecurity: true, phase: 6, load: () => import("./HDS") },
  { code: "OWN", title: "Ownership / insiders", needsSecurity: true, phase: 6, load: () => import("./OWN") },
  { code: "EQS", title: "Equity screener", needsSecurity: false, argsSchema: "[SECTOR=TECH MCAP>10B PCT>2 PRICE<50 VOL>1M COUNTRY=US SORT=PCT]", phase: 9, load: () => import("./EQS") },
  { code: "GIP", title: "Intraday tick chart (candles built from the live ticks seen since the session began)", needsSecurity: true, argsSchema: "[1S|5S|15S|1M]", phase: 19, load: () => import("./GIP"), idlePreload: false },
  { code: "IMAP", title: "Heat map of the equity universe (size = market cap, colour = % change)", needsSecurity: false, argsSchema: "[SECTOR|INDUSTRY|COUNTRY] [N=3000] [EQS filter: MCAP>10B ...]", phase: 19, load: () => import("./IMAP") },
  { code: "SEAS", title: "Seasonality (average return by month, weekday, day of month, ISO week)", needsSecurity: true, argsSchema: "[MONTH|WEEKDAY|DOM|WOY]", phase: 19, load: () => import("./SEAS") },
  { code: "SECF", title: "Security finder (fuzzy name or ticker search; ISIN / CUSIP / SEDOL / FIGI lookup via OpenFIGI)", needsSecurity: false, argsSchema: "<text | ISIN | CUSIP | SEDOL | FIGI:id ...>", phase: 19, load: () => import("./SECF") },
  { code: "ECST", title: "World statistics: one indicator for one country (World Bank, DBnomics IMF)", needsSecurity: false, argsSchema: "<COUNTRY> <GDP|GDPG|GDPPC|CPI|UNEMP|POP|DEBT|CA|TRADE> | DBN:<provider>/<dataset>/<series>", phase: 19, load: () => import("./ECST") },
  { code: "WECO", title: "World economies: G20 growth, inflation, unemployment, debt, current account (each cell with its data year)", needsSecurity: false, argsSchema: "", phase: 19, load: () => import("./WECO") },
  { code: "CENB", title: "Central bank calendar: policy rates and rate-decision dates (Fed, ECB, BoE, BoJ, BoC, RBA, RBI, SNB)", needsSecurity: false, argsSchema: "", phase: 19, load: () => import("./CENB") },
  { code: "PRED", title: "Prediction markets: Polymarket and Kalshi odds (MARKET-IMPLIED PROBABILITY, NOT A FORECAST; read only)", needsSecurity: false, argsSchema: "[TEXT ...] [SRC=POLY|KALSHI|ALL]", phase: 19, load: () => import("./PRED") },
  { code: "CDEP", title: "Crypto order book depth: cumulative bids / asks, spread, imbalance (Binance spot, OKX fallback)", needsSecurity: false, argsSchema: "[PAIR] [LEVELS]", phase: 19, load: () => import("./CDEP") },
  { code: "FUND", title: "Perpetual funding rates (annualised) and basis, quarterly basis; one coin's funding history", needsSecurity: false, argsSchema: "[COIN]", phase: 19, load: () => import("./FUND") },
  { code: "LIQ", title: "Crypto liquidations: latest filled liquidation orders of a USDT perpetual (OKX)", needsSecurity: false, argsSchema: "[COIN]", phase: 19, load: () => import("./LIQ") },
  { code: "STBL", title: "Stablecoin supply by coin and chain (DefiLlama)", needsSecurity: false, argsSchema: "[CHAIN]", phase: 19, load: () => import("./STBL") },
  { code: "DEFI", title: "DeFi yield pools over US$1M TVL by chain or project (DefiLlama)", needsSecurity: false, argsSchema: "[CHAIN|PROJECT]", phase: 19, load: () => import("./DEFI") },
  { code: "UNLK", title: "Token unlocks: not built, DefiLlama's emissions API is paid (HTTP 402) and there is no keyless source", needsSecurity: false, argsSchema: "", phase: 19 },
  { code: "NRG", title: "Energy board: crude, natural gas, refined products, retail fuel (FRED CSV, prices only)", needsSecurity: false, argsSchema: "[WTI|BRENT|HH|GASNY|GASGC|ULSD|HEAT|JET|PROPANE|GASRET|DIESELRET]", phase: 19, load: () => import("./NRG") },
  { code: "WETR", title: "Weather for commodities: degree-day basket, place forecast, NWS alerts (Open-Meteo)", needsSecurity: false, argsSchema: "[<place> | <lat,lon>]", phase: 19, load: () => import("./WETR") },
  { code: "CORR", title: "Correlation matrix", needsSecurity: false, argsSchema: "SYM SYM... [1M..MAX]", phase: 9, load: () => import("./CORR") },
  { code: "COMP", title: "Peer comparison", needsSecurity: true, phase: 9, load: () => import("./COMP") },
  { code: "HIST", title: "Historical price table", needsSecurity: true, argsSchema: "[1M..MAX] [D|W|MO]", phase: 9, load: () => import("./HIST") },
  { code: "LAYOUT", title: "Save / load named workspaces", needsSecurity: false, argsSchema: "[SAVE|LOAD|DEL] name", phase: 4, load: () => import("./Layout") },
  { code: "MONITOR", title: "Alias of LAYOUT", needsSecurity: false, argsSchema: "[SAVE|LOAD|DEL] name", phase: 4, load: () => import("./Layout") },
  { code: "SETTINGS", title: "Settings: theme, vim mode, shortcuts, number format, clocks", needsSecurity: false, argsSchema: "[MODE|THEME|VIM|CLOCKS|CHART|THOUSANDS|DECIMAL|POLL|KEYS|RESET ...]", phase: 10, load: () => import("./SETTINGS") },
  { code: "THEME", title: "Colour theme", needsSecurity: false, argsSchema: "[AMBER|GREEN|WHITE|LIGHT]", phase: 10, load: () => import("./SETTINGS") },
  { code: "JOBS", title: "Background jobs: progress, cancel, results", needsSecurity: false, argsSchema: "[TEST [steps] [ms]]", phase: 11, load: () => import("./JOBS"), idlePreload: false },
  { code: "BT", title: "Backtest a rule on historical bars (historical simulation, not a forecast)", needsSecurity: false, argsSchema: "<SYMS> <RULE|@NAME> [1D|1W] [RANGE] [SHORT] [FEES=bps] [SLIP=bps] [CASH=n] [BENCH=sym] [MKT=engine]", phase: 12, load: () => import("./BT"), idlePreload: false },
  { code: "IMPORT", title: "Import your own daily bars (CSV) as a data source, labelled LOCAL DATA", needsSecurity: false, argsSchema: "[SYMBOL | LIST | DEL SYMBOL]", phase: 12, load: () => import("./IMPORT"), idlePreload: false },
  { code: "EE", title: "Analyst estimates: EPS and revenue consensus by period", needsSecurity: true, phase: 13, load: () => import("./EE") },
  { code: "CN", title: "Company news from every source, keyword-scored (not a model)", needsSecurity: true, phase: 13, load: () => import("./CN") },
  { code: "EEO", title: "Estimate revisions and EPS surprises", needsSecurity: true, phase: 13, load: () => import("./EEO") },
  { code: "ANR", title: "Analyst ratings, price targets and rating changes", needsSecurity: true, phase: 13, load: () => import("./ANR") },
  { code: "MGMT", title: "Officers, governance scores and proxy statements", needsSecurity: true, phase: 13, load: () => import("./MGMT") },
  { code: "DVD", title: "Dividend history with declaration, record and pay dates", needsSecurity: true, phase: 13, load: () => import("./DVD") },
  { code: "SPLT", title: "Stock split history", needsSecurity: true, phase: 13, load: () => import("./SPLT") },
  { code: "CACS", title: "Corporate actions: dividends and splits by date", needsSecurity: true, phase: 13, load: () => import("./CACS") },
  { code: "IPO", title: "IPO calendar: upcoming, priced, filed, withdrawn", needsSecurity: false, argsSchema: "[YYYY-MM]", phase: 13, load: () => import("./IPO") },
  { code: "SI", title: "Short interest (FINRA) and daily short sale volume", needsSecurity: true, phase: 13, load: () => import("./SI") },
  { code: "EVTS", title: "Company events: SEC 8-K filings by item", needsSecurity: true, phase: 13, load: () => import("./EVTS") },
  { code: "DCF", title: "Discounted cash flow (Vibe engine): NOT RUNNABLE until every input is given", needsSecurity: true, argsSchema: "ERP=5.5 G=2.5 EXITX=14 GROWTH=5 BASIS=CURRENT|TARGET CONV=MID|END TV=PERP|EXIT OTHER=0 [KD= RF= BETA= TAX= YEARS= EW=]", phase: 13, load: () => import("./DCF") },
  { code: "WACC", title: "Weighted average cost of capital (Vibe engine)", needsSecurity: true, argsSchema: "ERP=5.5 BASIS=CURRENT|TARGET [EW= KD= RF= BETA= TAX=]", phase: 13, load: () => import("./WACC") },
  { code: "RV", title: "Relative valuation: peer multiples from SEC filings (Vibe comps engine)", needsSecurity: true, argsSchema: "[PEERS=SYM,SYM]", phase: 13, load: () => import("./RV") },
  { code: "ETF", title: "ETF profile, full N-PORT holdings and sector weights", needsSecurity: true, phase: 13, load: () => import("./ETF") },
  { code: "MEMB", title: "Index members and weights via the proxy ETF's N-PORT", needsSecurity: false, argsSchema: "SPX|NDX|DJI|RUT|MID|<ETF>", phase: 13, load: () => import("./MEMB") },
  { code: "MGR", title: "Manager 13F positions with quarter-over-quarter changes", needsSecurity: false, argsSchema: "<NAME|CIK>", phase: 13, load: () => import("./MGR") },
  { code: "OMON", title: "Option chain: IV, Greeks computed here, open interest, volume", needsSecurity: true, argsSchema: "[YYYY-MM-DD] [ITM|OTM|ALL] [Q=pct]", phase: 14, load: () => import("./OMON") },
  { code: "PCR", title: "Put/call ratio by volume and open interest, per expiry", needsSecurity: true, phase: 14, load: () => import("./PCR") },
  { code: "OV", title: "Option pricer: Black-Scholes, binomial, Heston, barrier, IV solver (NOT RUNNABLE until every input is given)", needsSecurity: true, argsSchema: "K= EXP=|T= TYPE=C|P [IV= R= Q=] [V0= KAPPA= THETA= SIGMAV= RHO=] [H= BARR=] [PRICE=]", phase: 14, load: () => import("./OV") },
  { code: "OSA", title: "Multi-leg option payoff, breakevens, scenario grid, Greeks by leg", needsSecurity: true, argsSchema: "LEGS=+1C270@5,-1C290 | STRAT=BULLCALL,270,290 EXP=|T= [IV= R= MULT= COMM=]", phase: 14, load: () => import("./OSA") },
  { code: "OVDV", title: "Implied-vol surface: expiry x moneyness heat map and fitted smiles (equity from the chain, crypto from Deribit)", needsSecurity: true, phase: 14, load: () => import("./OVDV") },
  { code: "SKEW", title: "Skew by expiry: ATM IV, 25-delta risk reversal and butterfly, slope, term structure", needsSecurity: true, phase: 14, load: () => import("./SKEW") },
  { code: "HIVG", title: "Realized vs implied vol, variance risk premium, rolling RV, local IV rank", needsSecurity: true, phase: 14, load: () => import("./HIVG") },
  { code: "CT", title: "Futures term structure: contango/backwardation, spread to front, roll yield (month spacing)", needsSecurity: false, argsSchema: "<ROOT: CL NG GC ES ZN ZQ ...>", phase: 14, load: () => import("./CT") },
  { code: "WIRP", title: "Implied fed funds path across FOMC meetings from ZQ futures (not a probability forecast)", needsSecurity: false, phase: 14, load: () => import("./WIRP") },
  { code: "COT", title: "CFTC Commitments of Traders: positions, weekly change, 3-year net history and percentile", needsSecurity: false, argsSchema: "<MARKET: ES CL GC ZN EUR ... or name>", phase: 14, load: () => import("./COT") },
  { code: "FXFA", title: "FX forward estimate by covered interest parity (not a dealer quote)", needsSecurity: false, argsSchema: "<PAIR> [1W,1M,3M,6M,1Y] [R1= R2=]", phase: 14, load: () => import("./FXFA") },
  { code: "YAS", title: "Bond yield analysis from terms: price/yield, accrued, duration, convexity, DV01, key-rate durations", needsSecurity: false, argsSchema: "CPN= MAT= PX=|YLD= [FREQ= SETTLE= DAYS= FACE=]", phase: 14, load: () => import("./YAS") },
  { code: "SWPM", title: "Vanilla swap valuation on the Treasury par curve (discount proxy, not SOFR) or a flat curve", needsSecurity: false, argsSchema: "N= FIXED= TENOR= DIR=PAY|REC [FREQ= CURVE=TSY|FLAT:4.2]", phase: 14, load: () => import("./SWPM") },
  { code: "CDSW", title: "CDS valuation, flat hazard (credit triangle), user inputs only", needsSecurity: false, argsSchema: "SPREAD= REC= TENOR= RF= COUPON= N= [FREQ=]", phase: 14, load: () => import("./CDSW") },
  { code: "RISK", title: "Portfolio risk: VaR (historical, normal, EVT), expected shortfall, contributions, stress replays, VaR backtest (historical simulation, not a forecast)", needsSecurity: false, argsSchema: "[PORTFOLIO] [RANGE=3y] [BENCH=SPY] [CONF=95] [HOR=1]", phase: 15, load: () => import("./RISK") },
  { code: "OPT", title: "Portfolio optimizer preview (PORT OPT): trades, before/after, risk contributions; A saves <NAME>.OPT, never orders", needsSecurity: false, argsSchema: "[PORTFOLIO] [METHOD=EQVOL|RP|MV|MAXDIV|HRP|TURN] [CAP=0.25] [LOOKBACK=252] [RF=0] [TC=0]", phase: 15, load: () => import("./OPT") },
  { code: "ATTR", title: "Performance attribution (PORT ATTR): Brinson-Fachler by sector, TWR, MWR, Modified Dietz from stored valuations", needsSecurity: false, argsSchema: "[PORTFOLIO] [BENCH=SPY] [RANGE=1y] | <PORTFOLIO> ADD <DATE> VALUE= [FLOW=] | <PORTFOLIO> DEL <DATE>", phase: 15, load: () => import("./ATTR") },
  { code: "FACT", title: "Factor regression (Fama-French / momentum / quality) of a symbol or portfolio; the factor data end date is shown", needsSecurity: false, argsSchema: "<SYM|PORTFOLIO> [RANGE=3y]", phase: 15, load: () => import("./FACT") },
  { code: "QL", title: "Quant calculators on bars: GARCH OU COINT HEDGE COPULA ROLL AMIHUD KYLE VPIN EVENT DSR ADF HVAR", needsSecurity: false, argsSchema: "<GARCH|OU|COINT|HEDGE|COPULA|ROLL|AMIHUD|KYLE|VPIN|EVENT|DSR|ADF|HVAR> [SYMBOLS] [KEY=VALUE]", phase: 15, load: () => import("./QL") },
  { code: "ALPHA", title: "Alpha factor zoo: IC / IR / decay of Alpha101 and Qlib158 style factors over a universe (historical, not a forecast; SYN is synthetic)", needsSecurity: false, argsSchema: "[UNIVERSE=TOP100|SYN|WL:<NAME>|LIST:A,B,C] [RANGE=2y] [FAMILY=...] [H=1,5,10,20]", phase: 15, load: () => import("./ALPHA") },
  { code: "REGIME", title: "Correlation regime (CORR REGIME): DIFFUSE vs FUSED state, edge density and episodes of a watchlist or list", needsSecurity: false, argsSchema: "[WL:<NAME>|LIST:A,B,C] [WIN=60] [EDGE=0.5]", phase: 15, load: () => import("./REGIME") },
  { code: "KITE", title: "Kite Connect (read-only data source): login state, LOGIN opens Kite in a new tab, LOGOUT clears the token; no orders", needsSecurity: false, argsSchema: "[LOGIN|STATUS|LOGOUT]", phase: 15, load: () => import("./KITE") },
  { code: "AI", title: "AI research assistant over OpenTerm data: tool calls with sources, [T1] citations, UNGROUNDED / UNSOURCED flags (model output, not data; needs OPENROUTER key)", needsSecurity: false, argsSchema: "[question... | BT <strategy idea> | AUTO <hypothesis> | CHART | DOC FILING <SYM> [FORM] | DOC OFF]", phase: 16, load: () => import("./AI"), idlePreload: false },
  { code: "SWARM", title: "Multi-agent desks (committee, risk, earnings, macro, quant): analyst roles with their own tools, then a chair; stored runs replay without a model (model output, not data; needs OPENROUTER key)", needsSecurity: false, argsSchema: "[COMMITTEE|RISK|EARNINGS|MACRO|QUANT <subject> | REPLAY <id> | LIST]", phase: 16, load: () => import("./SWARM"), idlePreload: false },
  { code: "THESIS", title: "Investment thesis notes per ticker: status, invalidation rule, linked SWARM runs (stored locally)", needsSecurity: false, argsSchema: "[SYMBOL | ADD <SYMBOL> <text> | INVALID <id> <rule>]", phase: 16, load: () => import("./THESIS"), idlePreload: false },
  { code: "AUDIT", title: "Audit ledger of AI, SWARM, AI AUTO and BT runs: hash chain verified, manifests and tool calls (hashes only)", needsSecurity: false, phase: 16, load: () => import("./AUDIT"), idlePreload: false },
  { code: "APIKEYS", title: "API keys: set, test, remove (optional, zero keys works)", needsSecurity: false, argsSchema: "[PROVIDER]", phase: 11, load: () => import("./APIKEYS"), idlePreload: false },
  { code: "SOURCES", title: "Data sources: health, latency, quota", needsSecurity: false, phase: 2, load: () => import("./Sources") },
  { code: "LOG", title: "Backend log", needsSecurity: false, phase: 2, load: () => import("./Log") },
  { code: "DLVR", title: "Alert delivery", needsSecurity: false, phase: 17, load: () => import("./DLVR") },
  { code: "BRIEF", title: "Daily brief", needsSecurity: false, phase: 17, load: () => import("./BRIEF") },
  { code: "FUNC", title: "Function directory: every function code with its purpose; type to filter, Enter opens", needsSecurity: false, phase: 20, load: () => import("./FUNC") },
];

export const FUNCTIONS = new Map(defs.map((d) => [d.code, d]));
// Aliases (functions/aliases.ts) point at the same definition, so isFunction and saved layouts accept both words.
// def.code is always the canonical code.
for (const [alias, target] of Object.entries(ALIASES)) {
  const def = FUNCTIONS.get(target);
  if (def && !FUNCTIONS.has(alias)) FUNCTIONS.set(alias, def);
}

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
