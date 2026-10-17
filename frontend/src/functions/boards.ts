/**
 * Fixed quote boards (WEI, FX, CMDTY) and FX cross-rate math (FXC). Symbols are Yahoo-style and were
 * checked against Yahoo spark on 2026-10-17. Labels and contract units are static reference text.
 */

export interface BoardItem {
  symbol: string;
  label: string;
  /** Quote unit (commodity contracts), e.g. USD/BBL or USC/BU (US cents per bushel). */
  unit?: string;
}

export interface BoardDef {
  code: string;
  title: string;
  /** What one row is, for the header count ("31 INDICES"). */
  noun: string;
  sections: { title: string; items: BoardItem[] }[];
  /** FX: more decimals than the equity price format. */
  rates?: boolean;
}

const items = (...rows: [string, string, string?][]): BoardItem[] => rows.map(([symbol, label, unit]) => ({ symbol, label, unit }));

export const WEI: BoardDef = {
  code: "WEI",
  title: "WORLD EQUITY INDICES",
  noun: "INDICES",
  sections: [
    {
      title: "AMERICAS",
      items: items(
        ["^GSPC", "S&P 500"], ["^DJI", "DOW JONES INDU"], ["^IXIC", "NASDAQ COMPOSITE"], ["^NDX", "NASDAQ 100"],
        ["^RUT", "RUSSELL 2000"], ["^VIX", "CBOE VIX"], ["^GSPTSE", "S&P/TSX COMPOSITE"], ["^BVSP", "IBOVESPA"],
        ["^MXX", "S&P/BMV IPC"], ["^MERV", "S&P MERVAL"],
      ),
    },
    {
      title: "EMEA",
      items: items(
        ["^FTSE", "FTSE 100"], ["^GDAXI", "DAX"], ["^FCHI", "CAC 40"], ["^STOXX50E", "EURO STOXX 50"], ["^AEX", "AEX"],
        ["^IBEX", "IBEX 35"], ["^SSMI", "SMI"], ["FTSEMIB.MI", "FTSE MIB"], ["^OMX", "OMX STOCKHOLM 30"],
      ),
    },
    {
      title: "ASIA-PACIFIC",
      items: items(
        ["^N225", "NIKKEI 225"], ["^HSI", "HANG SENG"], ["000001.SS", "SSE COMPOSITE"], ["^NSEI", "NIFTY 50"],
        ["^BSESN", "BSE SENSEX"], ["^NSEBANK", "NIFTY BANK"], ["^AXJO", "S&P/ASX 200"], ["^KS11", "KOSPI"],
        ["^TWII", "TAIEX"], ["^STI", "STRAITS TIMES"], ["^JKSE", "JAKARTA COMPOSITE"], ["^NZ50", "S&P/NZX 50"],
      ),
    },
  ],
};

export const FX: BoardDef = {
  code: "FX",
  title: "CURRENCIES",
  noun: "PAIRS",
  rates: true,
  sections: [
    {
      title: "MAJORS",
      items: items(
        ["EURUSD=X", "EUR/USD"], ["GBPUSD=X", "GBP/USD"], ["USDJPY=X", "USD/JPY"], ["USDCHF=X", "USD/CHF"],
        ["AUDUSD=X", "AUD/USD"], ["USDCAD=X", "USD/CAD"], ["NZDUSD=X", "NZD/USD"], ["DX-Y.NYB", "US DOLLAR INDEX"],
      ),
    },
    { title: "ASIA", items: items(["USDCNY=X", "USD/CNY"], ["USDHKD=X", "USD/HKD"], ["USDSGD=X", "USD/SGD"]) },
    { title: "INR", items: items(["USDINR=X", "USD/INR"], ["EURINR=X", "EUR/INR"], ["GBPINR=X", "GBP/INR"], ["JPYINR=X", "JPY/INR"]) },
    { title: "CROSSES", items: items(["EURGBP=X", "EUR/GBP"], ["EURJPY=X", "EUR/JPY"]) },
  ],
};

export const CMDTY: BoardDef = {
  code: "CMDTY",
  title: "COMMODITIES",
  noun: "CONTRACTS",
  sections: [
    {
      title: "ENERGY",
      items: items(
        ["CL=F", "WTI CRUDE", "USD/BBL"], ["BZ=F", "BRENT CRUDE", "USD/BBL"], ["NG=F", "NATURAL GAS", "USD/MMBTU"],
        ["RB=F", "RBOB GASOLINE", "USD/GAL"], ["HO=F", "HEATING OIL", "USD/GAL"],
      ),
    },
    {
      title: "METALS",
      items: items(
        ["GC=F", "GOLD", "USD/OZT"], ["SI=F", "SILVER", "USD/OZT"], ["PL=F", "PLATINUM", "USD/OZT"],
        ["PA=F", "PALLADIUM", "USD/OZT"], ["HG=F", "COPPER", "USD/LB"],
      ),
    },
    {
      title: "AGRICULTURE",
      items: items(
        ["ZC=F", "CORN", "USC/BU"], ["ZW=F", "WHEAT", "USC/BU"], ["ZS=F", "SOYBEANS", "USC/BU"], ["KC=F", "COFFEE", "USC/LB"],
        ["SB=F", "SUGAR NO.11", "USC/LB"], ["CC=F", "COCOA", "USD/T"], ["CT=F", "COTTON", "USC/LB"],
      ),
    },
    { title: "LIVESTOCK", items: items(["LE=F", "LIVE CATTLE", "USC/LB"], ["HE=F", "LEAN HOGS", "USC/LB"]) },
  ],
};

export const BOARDS = { WEI, FX, CMDTY };

// --- FXC --------------------------------------------------------------------------------------
export const FXC_DEFAULT = ["USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "CNY", "HKD", "SGD", "INR"];
export const FXC_MAX = 16;

export function parseCurrencies(args: string[]): { ok: true; list: string[] } | { ok: false; error: string } {
  if (!args.length) return { ok: true, list: FXC_DEFAULT };
  const list = [...new Set(args.map((a) => a.toUpperCase()))];
  const bad = list.find((c) => !/^[A-Z]{3}$/.test(c));
  if (bad) return { ok: false, error: `NOT A CURRENCY CODE: ${bad}` };
  if (list.length > FXC_MAX) return { ok: false, error: `AT MOST ${FXC_MAX} CURRENCIES` };
  return { ok: true, list };
}

/** Yahoo's USD leg for a currency: USDxxx=X quotes units of xxx per 1 USD. */
export const usdLeg = (ccy: string): string | null => (ccy === "USD" ? null : `USD${ccy}=X`);

/** Yahoo pair to chart for "1 base in quote"; USD against itself charts the dollar index. */
export const crossPair = (base: string, quote: string): string => (base === quote && base === "USD" ? "DX-Y.NYB" : `${base}${quote}=X`);

/**
 * Price of 1 `base` in `quote`, triangulated through USD from per-USD rates. Missing or zero legs give
 * null (shown blank), never a guess.
 */
export function crossRate(perUsd: Record<string, number | null | undefined>, base: string, quote: string): number | null {
  const b = base === "USD" ? 1 : perUsd[base];
  const q = quote === "USD" ? 1 : perUsd[quote];
  if (b == null || q == null || !b || !q || !Number.isFinite(b) || !Number.isFinite(q)) return null;
  return q / b;
}
