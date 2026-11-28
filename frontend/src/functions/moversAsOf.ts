/**
 * The "as of" text in the MOV header: the most honest time we have, and what kind of time it is.
 *
 * Sources know different things:
 *   - Nasdaq answers its own "data as of ..." sentence per table (`table_as_of` / `as_of_text`): show that as written.
 *   - Yahoo's screens give each quote's trade time; the backend keeps the newest as `market_time` (epoch seconds):
 *     show it as "QUOTES HH:MM:SS".
 *   - TradingView (and the FMP backup) give no time at all. All OpenTerm knows is when it fetched the answer, which is
 *     the envelope's `as_of`: show it as "FETCHED HH:MM:SS". It is never passed off as a market time.
 *
 * Pure (no net or settings imports) so vitest can test it.
 */
import { fmtTime } from "../format";

export interface MoversTimes {
  table_as_of: Record<string, string | null>;
  as_of_text: string | null;
  market_time: number | null;
}

export function moversAsOf(data: MoversTimes, tab: string, fetchedAtS: number | null | undefined): string | null {
  const text = data.table_as_of[tab] ?? data.as_of_text;
  if (text) return text.toUpperCase();
  if (data.market_time) return `QUOTES ${fmtTime(data.market_time * 1000)}`;
  if (fetchedAtS) return `FETCHED ${fmtTime(fetchedAtS * 1000)}`;
  return null;
}
