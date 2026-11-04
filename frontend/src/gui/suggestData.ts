/**
 * Data side of the company-name search. This file is loaded with a dynamic `import()` the first time a search box is
 * used (focus or typing), so it, and the 1 MB screener universe it fetches, cost nothing at startup.
 */
import { api, api9 } from "../net/api";
import { closestCompanies, matchCompanies, mergeHits, type CompanyHit, type UniverseEntry } from "./companySearch";

/** The universe is fetched once per page load (the client cache also keeps it 5 minutes). A failure is not remembered. */
let universe: Promise<UniverseEntry[]> | null = null;

export function loadUniverse(): Promise<UniverseEntry[]> {
  universe ??= api9
    .screener()
    .then((env) => env.data.rows.map((r) => ({ symbol: r[0], name: r[1], mcap: r[6] })))
    .catch(() => {
      universe = null; // try again next time
      return [];
    });
  return universe;
}

/**
 * Suggestions for `query`. `onUpdate` is called with the local (screener) matches first, then once more with Yahoo's
 * name search merged in when the local list is short (that search also finds non-US companies like "reliance").
 */
export async function suggest(query: string, onUpdate: (hits: CompanyHit[]) => void, isCurrent: () => boolean): Promise<void> {
  const uni = await loadUniverse();
  if (!isCurrent()) return;
  const local = matchCompanies(query, uni);
  onUpdate(local);
  if (local.length >= 3 || query.trim().length < 3) return;
  try {
    const env = await api.search(query.trim());
    if (!isCurrent()) return;
    const remote: CompanyHit[] = env.data
      .filter((h) => h.symbol && (h.type == null || /equity|etf|index/i.test(h.type)))
      .slice(0, 5)
      .map((h) => ({ symbol: h.symbol, name: h.name ?? h.symbol, via: "name" as const }));
    onUpdate(mergeHits(local, remote).slice(0, 6));
  } catch {
    // The local list stays; a failed name search is not worth an error box.
  }
}

/** Companies that look most like a symbol that returned no data ("Try AAPL"). */
export async function closest(query: string): Promise<CompanyHit[]> {
  return closestCompanies(query, await loadUniverse());
}
