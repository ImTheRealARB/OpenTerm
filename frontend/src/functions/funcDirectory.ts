/**
 * Pure helpers for the FUNC panel (function directory): build the rows, shorten a title to one line, filter by typing.
 * No React and no registry import (the caller passes the list), so vitest can test it.
 */
export interface DirEntry {
  code: string;
  title: string;
  needsSecurity: boolean;
  argsSchema?: string;
}

export interface DirRow {
  code: string;
  /** One line: what the function is for. */
  purpose: string;
  /** "SEC" when it needs a security ("AAPL GP"), else "". */
  takes: string;
  /** GUI menu category, or "". */
  category: string;
  /** For an alias row: the code it runs, else "". */
  aliasOf: string;
}

/** The first clause of a registry title: cut at the first " (" or ": " and drop a trailing dot. */
export function shortPurpose(title: string): string {
  const cut = title.search(/ \(|: /);
  const s = (cut > 0 ? title.slice(0, cut) : title).trim().replace(/\.$/, "");
  return s.toUpperCase();
}

/** One row per function plus one per alias, sorted by code. */
export function buildRows(
  list: readonly DirEntry[],
  aliases: Readonly<Record<string, string>>,
  categoryOf: (code: string) => string | undefined,
): DirRow[] {
  const rows: DirRow[] = list.map((f) => ({
    code: f.code,
    purpose: shortPurpose(f.title),
    takes: f.needsSecurity ? "SEC" : "",
    category: categoryOf(f.code) ?? "",
    aliasOf: "",
  }));
  const byCode = new Map(list.map((f) => [f.code, f]));
  for (const [alias, target] of Object.entries(aliases)) {
    const f = byCode.get(target);
    if (!f) continue;
    rows.push({
      code: alias,
      purpose: `SAME AS ${target}: ${shortPurpose(f.title)}`,
      takes: f.needsSecurity ? "SEC" : "",
      category: categoryOf(target) ?? "",
      aliasOf: target,
    });
  }
  return rows.sort((a, b) => (a.code < b.code ? -1 : a.code > b.code ? 1 : 0));
}

/**
 * Filter by typed letters: codes that START with the text come first, then codes or purposes that contain it.
 * Empty text keeps everything in order.
 */
export function filterRows(rows: readonly DirRow[], text: string): DirRow[] {
  const q = text.trim().toUpperCase();
  if (!q) return [...rows];
  const starts: DirRow[] = [];
  const contains: DirRow[] = [];
  for (const r of rows) {
    if (r.code.startsWith(q)) starts.push(r);
    else if (r.code.includes(q) || r.purpose.includes(q) || r.category.toUpperCase().includes(q)) contains.push(r);
  }
  return [...starts, ...contains];
}
