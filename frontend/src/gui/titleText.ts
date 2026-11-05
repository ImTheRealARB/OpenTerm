/**
 * Plain-words label for a panel's title bar in GUI mode (pure, so vitest can run it).
 *
 * Registry titles are written for the function list and often carry a long explanation after the first clause:
 * "Quote monitor (live)", "Intraday tick chart (candles built from ...)", "Security finder: fuzzy name ...".
 * The title bar only needs the first clause, so a beginner always sees WHAT the panel is next to its code.
 */
export function shortTitle(title: string): string {
  // Cut at the first " (", ":" or ";" (whichever comes first), then trim; a title that is only a clause is returned as is.
  const cut = title.search(/ \(|:|;/);
  const clause = (cut > 0 ? title.slice(0, cut) : title).trim();
  return clause.length > 40 ? clause.slice(0, 39).trimEnd() + "…" : clause;
}
