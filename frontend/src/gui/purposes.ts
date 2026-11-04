/**
 * One plain sentence per function for the GUI help drawer ("what is this panel for?"). Pure data, so vitest can check it.
 * A function without an entry falls back to its registry title (see `purposeOf`), so every panel still gets a sentence.
 */
const PURPOSES: Readonly<Record<string, string>> = {
  DES: "A one-page summary of a company: price, size, valuation numbers and what it does.",
  GP: "A price chart for a stock, index or currency over the time range you pick.",
  Q: "A live table of prices for several securities side by side.",
  WL: "Your saved lists of stocks, with live prices.",
  N: "Recent news headlines, top stories or about one stock.",
  WEI: "How the major stock indices around the world are doing right now.",
  FA: "A company's income statement, balance sheet and cash flow, year by year or quarter by quarter.",
  PORT: "Your positions with their current value and profit or loss.",
  ALRT: "Alerts that tell you when a price or percent move happens.",
  BT: "Tests a trading rule on past prices. A historical simulation, not a forecast.",
  FX: "Prices of the main currency pairs.",
  CMDTY: "Prices of oil, gold and other commodities.",
  EQS: "Filter all US stocks by size, valuation and other numbers.",
  COMP: "A company next to its peers on the same numbers.",
  ERN: "Earnings: what companies reported and what is expected next.",
  ECO: "The calendar of economic releases such as jobs and inflation.",
  MOV: "The biggest gainers and losers today.",
  FIL: "Official company filings from the SEC.",
  OWN: "Who owns the stock: funds and company insiders.",
  CORR: "How closely a set of stocks move together.",
  APIKEYS: "Where you add optional API keys that unlock more data.",
  SETTINGS: "Look, mode and key bindings for the app.",
  HELP: "The list of every function and how to open it.",
};

/** The one-sentence purpose of a function; `title` (the registry title) is the fallback. */
export function purposeOf(code: string, title: string): string {
  const known = PURPOSES[code];
  if (known) return known;
  const t = title.trim();
  return t.endsWith(".") ? t : `${t}.`;
}

/** The codes with a hand-written sentence (a test checks they are real functions). */
export const PURPOSE_CODES: readonly string[] = Object.keys(PURPOSES);
