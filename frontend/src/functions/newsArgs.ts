import type { SecurityRef } from "../command/markets";

export type NewsQuery = { kind: "top" } | { kind: "symbol"; symbol: string } | { kind: "keyword"; q: string };

/**
 * `N` (market top stories), `AAPL N` (that security; also the panel's sticky security), `N words...`
 * (keyword search), `N TOP` (top stories even when the panel has a security).
 */
export function newsQuery(args: string[], security?: SecurityRef): NewsQuery {
  const words = args.map((a) => a.trim()).filter(Boolean);
  if (words.length === 1 && words[0].toUpperCase() === "TOP") return { kind: "top" };
  if (words.length) return { kind: "keyword", q: words.join(" ").toUpperCase() };
  if (security) return { kind: "symbol", symbol: security.symbol };
  return { kind: "top" };
}

/**
 * What to try when a query came back with no headlines (shown under "NO HEADLINES").
 * Pure on purpose, so it is unit-tested without a browser.
 */
export function newsEmptyHint(q: NewsQuery): string {
  switch (q.kind) {
    case "symbol":
      return `No headlines for ${q.symbol}. Try N <words> for a keyword search, N TOP for market stories, or F5 to retry.`;
    case "keyword":
      return `Nothing matched ${q.q}. Try fewer or broader words, N TOP for market stories, or F5 to retry.`;
    default:
      return "No stories came back. Press F5 to retry; sources that are not answering are named in the header.";
  }
}
