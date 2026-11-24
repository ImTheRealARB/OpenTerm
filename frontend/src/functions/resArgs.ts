/**
 * RES (Phase 32) arguments: `RES [SRC=<source>] [DAYS=<n>] [words...]`. Pure, so vitest can check it.
 * The source list lives only on the server (`macrod/boards.py` RES_FEEDS): SRC= is passed through and a wrong one comes back as a
 * 400 naming the valid sources, so there is no TypeScript copy to keep in step.
 */
export function resParams(args: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  const words: string[] = [];
  for (const a of args) {
    const m = /^(SRC|DAYS)=(.+)$/i.exec(a);
    if (m) out[m[1].toLowerCase()] = m[1].toUpperCase() === "SRC" ? m[2].toUpperCase() : m[2];
    else words.push(a);
  }
  if (words.length) out.q = words.join(" ");
  return out;
}
