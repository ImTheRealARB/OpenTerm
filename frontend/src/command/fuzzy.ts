/**
 * Cheap fuzzy score: exact > prefix > word-prefix > subsequence. Returns -1 for no match.
 * Runs per keystroke over a few hundred items, so it stays allocation-free.
 */
export function fuzzyScore(query: string, text: string): number {
  if (!query) return 0;
  const q = query.toUpperCase();
  const t = text.toUpperCase();
  if (t === q) return 1000;
  if (t.startsWith(q)) return 800 - t.length;
  const wi = t.indexOf(" " + q);
  if (wi >= 0) return 600 - wi;
  const ci = t.indexOf(q);
  if (ci >= 0) return 400 - ci;
  let ti = 0;
  let gaps = 0;
  for (let qi = 0; qi < q.length; qi++) {
    const found = t.indexOf(q[qi], ti);
    if (found < 0) return -1;
    gaps += found - ti;
    ti = found + 1;
  }
  return Math.max(1, 200 - gaps * 5 - t.length);
}

export function fuzzyRank<T>(query: string, items: T[], key: (item: T) => string, limit: number): T[] {
  const scored: { item: T; s: number }[] = [];
  for (const item of items) {
    const s = fuzzyScore(query, key(item));
    if (s >= 0) scored.push({ item, s });
  }
  scored.sort((a, b) => b.s - a.s);
  return scored.slice(0, limit).map((x) => x.item);
}
