/**
 * Chooses what to do with Yahoo's name-search answer for a company name nothing local knew (pure, so vitest can run it).
 * The network call itself is in nlResolve.ts; this file only judges the hits.
 *
 * Yahoo's search is fuzzy: it answers almost any text. So a hit counts only when every word the user typed is the START of a
 * word in the hit's name or ticker ("bajaj finserv" -> "Bajaj Finserv Limited"). If that leaves one hit, or exactly one hit whose name
 * starts with the typed words, it is the answer; several different names become choices (never a guess). Nothing left = null.
 */
import type { CompanyHit } from "../gui/companySearch";
import type { RouteResult } from "./nlRoute";

const norm = (s: string): string => s.toLowerCase().replace(/[’']/g, "").replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();

/**
 * @param phrase    the words the user typed for the company ("bajaj finserv")
 * @param hits      Yahoo name-search hits, best first
 * @param template  the command with `{S}` where the symbol goes ("{S} GP 5Y")
 */
export function pickRemote(phrase: string, hits: readonly CompanyHit[], template: string): Extract<RouteResult, { kind: "command" | "choices" }> | null {
  const words = norm(phrase).split(" ").filter(Boolean);
  if (!words.length) return null;
  const fits = hits.filter((h) => {
    const text = ` ${norm(h.name)} ${norm(h.symbol)} `;
    return words.every((w) => text.includes(` ${w}`));
  });
  if (!fits.length) return null;
  const make = (symbol: string): string => template.replace("{S}", symbol);
  // One fit, or exactly one hit whose name starts with the typed words: that is the company. Several: ask.
  const starts = fits.filter((h) => norm(h.name).startsWith(words.join(" ")));
  const top = fits.length === 1 ? fits[0] : starts.length === 1 ? starts[0] : null;
  if (top) return { kind: "command", command: make(top.symbol), why: `${make(top.symbol)} · Yahoo name search: ${top.name}` };
  return { kind: "choices", choices: fits.slice(0, 4).map((h) => ({ command: make(h.symbol), label: `${h.symbol}  ${h.name}` })) };
}
