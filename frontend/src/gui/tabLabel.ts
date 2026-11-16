/**
 * What one browser-style tab says, as two parts: a small bold function badge ("GP") and a title after it.
 * Pure (no registry import) so a vitest can run it in Node and the startup bundle stays small: the caller passes the facts.
 *
 *  - badge: the panel's current function code, or "" for an empty panel.
 *  - title: the ticker when the function uses one (same rule as the panel title), otherwise the function's plain title
 *    (long ones are cut by CSS), otherwise "New tab" for an empty panel.
 *  - full: the old one-string label ("AAPL GP"), kept for aria-labels so screen readers and tests read the same words as before.
 */
export interface TabParts {
  badge: string;
  title: string;
  full: string;
}

export function tabParts(fn: string | undefined, symbol: string | undefined, showsSecurity: boolean, fnTitle: string | undefined): TabParts {
  const badge = fn ?? "";
  const ticker = showsSecurity ? symbol : undefined;
  // Order of preference: ticker (what you are looking at), then the function's plain title, then nothing.
  const title = ticker ?? fnTitle ?? "";
  const full = [ticker, fn].filter(Boolean).join(" ") || "New tab";
  if (!badge && !title) return { badge: "", title: "New tab", full };
  return { badge, title, full };
}
