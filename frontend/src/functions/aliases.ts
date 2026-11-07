/**
 * Other names for a function (pure data, no imports, so vitest, the registry and categories.ts can all share it).
 * There are exactly two kinds, kept apart on purpose:
 *
 *  1. ALIASES: extra command words with NO registry entry of their own. `execute` rewrites a typed alias to its
 *     canonical code, so panels and saved layouts only ever hold the canonical code ("WCRS" opens an FXC panel).
 *  2. TWINS: a second code that DOES have its own registry entry (its own title in HELP, FUNC and docs/FUNCTIONS.md) and
 *     keeps its own code on the panel ("SEC" shows SEC, not FIL). It shares the original's panel module, its place in
 *     the GUI menus (categories.ts) and, for MONITOR, the LAYOUT command handling in `execute`.
 *
 * Rule for adding an alias or twin: it must not be a real ticker people type first ("HP", "MS" ...), because a leading
 * function code wins over a ticker with the same letters.
 */

/** alias -> canonical code. */
export const ALIASES: Readonly<Record<string, string>> = Object.freeze({
  WCRS: "FXC", // world currency cross rates
  MOST: "MOV", // most active / top movers
  PRTU: "PORT", // portfolio
  MENU: "FUNC", // function directory
  DIR: "FUNC", // function directory
});

/** twin code -> the original function it repeats. Both codes have a registry entry (a test checks it). */
export const TWINS: Readonly<Record<string, string>> = Object.freeze({
  SEC: "FIL", // SEC filings
  MONITOR: "LAYOUT", // saved workspaces
});
