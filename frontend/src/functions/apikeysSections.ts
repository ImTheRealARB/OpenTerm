/**
 * APIKEYS sections (pure data + one helper, so vitest can run it). The panel used to be one flat list of ~33 providers;
 * this groups them under header rows. The names are the backend's provider names (`KeySpec` in backend/openterm/keys.py);
 * `apikeysSections.test.ts` reads that file and fails when a provider has no section, so a new provider cannot be forgotten.
 * Order inside a section is the backend's own order (stable); the order of the sections is the order below.
 */
export const SECTIONS: readonly { title: string; names: readonly string[] }[] = [
  { title: "AI models", names: ["openrouter", "openai", "anthropic", "opencodego", "deepseek", "groq", "mistral", "xai", "together", "fireworks", "gemini"] },
  { title: "Market data", names: ["finnhub", "alpaca", "fmp", "twelvedata", "alphavantage", "polygon", "tradier", "openfigi", "marketaux"] },
  { title: "Economic and official data", names: ["fred", "eia", "bls", "bea", "census", "comtrade", "companies_house", "openfec", "congressgov"] },
  { title: "India", names: ["kite"] },
  { title: "Crypto and on-chain", names: ["etherscan"] },
  { title: "Shipping and flights", names: ["aisstream", "opensky"] },
  { title: "Alerts and delivery", names: ["telegram", "smtp", "webhook"] },
  { title: "Trading accounts (ORD)", names: ["alpaca_paper", "alpaca_live"] },
  { title: "AI web search (opt-in)", names: ["brave", "tavily", "searxng"] },
];

/** The section title for a provider name, or "Other" for one nobody has placed yet (it then shows last, never disappears). */
export function sectionOf(name: string): string {
  return SECTIONS.find((s) => s.names.includes(name))?.title ?? "Other";
}

/** A section header row in the grid. */
export interface HeaderRow {
  header: string;
}
export const isHeaderRow = (r: unknown): r is HeaderRow => typeof r === "object" && r !== null && "header" in r;

/**
 * Rows in display order: a header row, then that section's providers in their original order. Empty sections are left out.
 * Unplaced providers (not in SECTIONS) go under a final "Other" header.
 */
export function groupRows<T extends { name: string }>(rows: readonly T[]): (T | HeaderRow)[] {
  const titles = [...SECTIONS.map((s) => s.title), "Other"];
  const out: (T | HeaderRow)[] = [];
  for (const t of titles) {
    const mine = rows.filter((r) => sectionOf(r.name) === t);
    if (mine.length) out.push({ header: t }, ...mine);
  }
  return out;
}
