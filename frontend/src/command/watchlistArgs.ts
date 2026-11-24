/** `WL` argument parsing. Pure (no store, no network) so it is unit-tested directly. */
import { LAYOUT_NAME_RE } from "../state/layoutState";
import { isSymbolToken, type SecurityRef } from "./markets";
import { FLAG_COLORS, type FlagColor, type MetaChange } from "../functions/wlFlags";

export type WlAction =
  | { kind: "view"; name?: string }
  | { kind: "edit"; name: string; add: string[]; remove: string[] }
  | { kind: "delete"; name: string }
  | { kind: "meta"; name: string; change: MetaChange }
  | { kind: "error"; message: string };

const NAME_ERR = "WATCHLIST NAME: 1-32 OF A-Z 0-9 _ . -";
const USAGE = "USAGE: WL [NAME] | WL NAME ADD|RM SYM... | WL NAME FLAG SYM COLOUR|OFF | WL NAME SECTION SYM [TITLE] | WL DEL NAME";
const ADD = new Set(["ADD", "+"]);
const REMOVE = new Set(["RM", "REMOVE", "DEL", "DELETE", "-"]);

/**
 * `WL` (index), `WL NAME` (open), `WL NAME ADD|RM SYM...`, `WL DEL NAME`.
 * `AAPL WL TECH ADD` adds the typed security; the panel's sticky security is never added silently.
 */
export function parseWl(args: string[], explicit?: SecurityRef): WlAction {
  if (!args.length) return { kind: "view" };
  const first = args[0].toUpperCase();
  if (first === "DEL" || first === "DELETE") {
    if (!args[1]) return { kind: "error", message: "WL DEL NEEDS A NAME" };
    const name = args[1].toUpperCase();
    return LAYOUT_NAME_RE.test(name) ? { kind: "delete", name } : { kind: "error", message: NAME_ERR };
  }
  if (!LAYOUT_NAME_RE.test(first)) return { kind: "error", message: NAME_ERR };
  if (args.length === 1) return { kind: "view", name: first };
  const verb = args[1].toUpperCase();
  // Phase 22: `WL TECH FLAG AAPL RED` (OFF removes) and `WL TECH SECTION JPM Banks and brokers` (no title removes the header).
  if (verb === "FLAG" || verb === "SECTION") {
    const sym = args[2]?.toUpperCase();
    if (!sym || !isSymbolToken(sym)) return { kind: "error", message: `WL ${first} ${verb} NEEDS A SYMBOL FROM THE LIST` };
    if (verb === "SECTION") {
      const title = args.slice(3).join(" ").trim();
      return { kind: "meta", name: first, change: { kind: "section", before: sym, ...(title ? { title } : {}) } };
    }
    const colour = args[3]?.toUpperCase();
    if (colour === "OFF" || colour === "NONE") return { kind: "meta", name: first, change: { kind: "flag", symbol: sym } };
    if (!colour || !FLAG_COLORS.includes(colour as FlagColor))
      return { kind: "error", message: `FLAG COLOURS: ${FLAG_COLORS.join(" ")} OR OFF` };
    return { kind: "meta", name: first, change: { kind: "flag", symbol: sym, color: colour as FlagColor } };
  }
  if (!ADD.has(verb) && !REMOVE.has(verb)) return { kind: "error", message: USAGE };
  const syms = [...new Set(args.slice(2).map((a) => a.toUpperCase()))];
  const bad = syms.find((s) => !isSymbolToken(s));
  if (bad) return { kind: "error", message: `BAD SYMBOL: ${bad}` };
  if (ADD.has(verb)) {
    const add = syms.length ? syms : explicit ? [explicit.symbol] : [];
    if (!add.length) return { kind: "error", message: `WL ${first} ADD NEEDS SYMBOLS, E.G. WL ${first} ADD AAPL MSFT` };
    return { kind: "edit", name: first, add, remove: [] };
  }
  if (!syms.length) return { kind: "error", message: `WL ${first} RM NEEDS SYMBOLS` };
  return { kind: "edit", name: first, add: [], remove: syms };
}
