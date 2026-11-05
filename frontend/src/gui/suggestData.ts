/**
 * Data side of the company-name search (plain-English commands and DES's "did you mean"). This file is loaded with a
 * dynamic `import()` the first time it is needed, so it, and the 1 MB screener universe it fetches, cost nothing at startup.
 */
import { api, api9 } from "../net/api";
import { closestCompanies, type CompanyHit, type UniverseEntry } from "./companySearch";

/** The universe is fetched once per page load (the client cache also keeps it 5 minutes). A failure is not remembered. */
let universe: Promise<UniverseEntry[]> | null = null;

export function loadUniverse(): Promise<UniverseEntry[]> {
  universe ??= api9
    .screener()
    .then((env) => env.data.rows.map((r) => ({ symbol: r[0], name: r[1], mcap: r[6], volume: r[5] })))
    .catch(() => {
      universe = null; // try again next time
      return [];
    });
  return universe;
}

/**
 * Yahoo's name search (also finds non-US companies like "reliance"): equities, ETFs and indexes only, at most 5. Throws when the
 * request fails; each caller decides what a failure means (plain-English commands give up quietly).
 */
export async function remoteSearch(query: string): Promise<CompanyHit[]> {
  const env = await api.search(query.trim());
  return env.data
    .filter((h) => h.symbol && (h.type == null || /equity|etf|index/i.test(h.type)))
    .slice(0, 5)
    .map((h) => ({ symbol: h.symbol, name: h.name ?? h.symbol, via: "name" as const }));
}

/** Companies that look most like a symbol that returned no data ("Try AAPL"). */
export async function closest(query: string): Promise<CompanyHit[]> {
  return closestCompanies(query, await loadUniverse());
}
