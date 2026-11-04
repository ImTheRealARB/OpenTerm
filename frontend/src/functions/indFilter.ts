/** Pure search over the indicator catalog for the IND panel (no React, no catalog import: rows are passed in). */
export interface IndRow {
  id: string;
  name: string;
  category: string;
  plain: string;
}

export interface ParsedQuery {
  words: string[];
  /** Trailing / embedded numbers: "rsi 21" adds RSI with length 21. */
  params: number[];
}

export function parseQuery(q: string): ParsedQuery {
  const words: string[] = [];
  const params: number[] = [];
  for (const t of q.trim().toLowerCase().split(/[\s,()]+/)) {
    if (!t) continue;
    if (/^-?\d+(\.\d+)?$/.test(t)) params.push(Number(t));
    else words.push(t);
  }
  return { words, params };
}

function score(r: IndRow, words: string[]): number {
  const id = r.id.toLowerCase();
  const name = r.name.toLowerCase();
  let total = 0;
  for (const w of words) {
    let s = 0;
    if (id === w) s = 100;
    else if (id.startsWith(w)) s = 80;
    else if (name.split(/[\s/()-]+/).some((x) => x.startsWith(w))) s = 60;
    else if (name.includes(w) || id.includes(w)) s = 40;
    else if (r.category.includes(w)) s = 20;
    else if (r.plain.toLowerCase().includes(w)) s = 10;
    if (!s) return 0; // every word must match something
    total += s;
  }
  return total;
}

/** Best matches first; with no words, catalog order. */
export function filterIndicators<T extends IndRow>(rows: T[], q: string): T[] {
  const { words } = parseQuery(q);
  if (!words.length) return rows;
  return rows
    .map((r, i) => ({ r, s: score(r, words), i }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.r);
}
