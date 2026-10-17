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
