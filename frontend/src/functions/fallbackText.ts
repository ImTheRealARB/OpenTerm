/**
 * The warning shown beside data that came from a fallback source. A source that was skipped for a reason worth saying (the backend's
 * `fallback_notes`, e.g. "KITE LOGIN EXPIRED: run KITE LOGIN") shows that reason; any other failed source shows the generic text.
 * Pure, so it is unit-tested without a browser.
 */
export function fallbackText(names: readonly string[], notes?: Readonly<Record<string, string>>): string {
  const parts: string[] = [];
  const plain: string[] = [];
  for (const n of names) {
    const why = notes?.[n];
    if (why) parts.push(`${why.toUpperCase()}, VIA FALLBACK`);
    else plain.push(n.toUpperCase());
  }
  if (plain.length) parts.push(`${plain.join(",")} DOWN, VIA FALLBACK`);
  return parts.join(" · ");
}

/** One warning for a table of quotes (Q): the sources every row fell back from, each with its reason when the backend gave one. */
export function rowsFallbackText(rows: readonly { fallbackFrom?: readonly string[]; fallbackNotes?: Readonly<Record<string, string>> }[]): string {
  const names = new Set<string>();
  const notes: Record<string, string> = {};
  for (const r of rows) {
    for (const n of r.fallbackFrom ?? []) names.add(n);
    Object.assign(notes, r.fallbackNotes);
  }
  return fallbackText([...names], notes);
}
