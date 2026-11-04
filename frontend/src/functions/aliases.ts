/**
 * Extra command words that run an existing function (pure data, no imports, so vitest and the registry can share it).
 *
 * alias -> canonical code. The canonical code is what a panel stores and what saved layouts hold, so layouts made
 * before an alias existed keep working, and `execute` rewrites a typed alias to its canonical code.
 * Rule for adding one: it must not be a real ticker people type first ("HP", "MS" ...), because a leading
 * function code wins over a ticker with the same letters.
 */
export const ALIASES: Readonly<Record<string, string>> = Object.freeze({
  WCRS: "FXC", // world currency cross rates
  MOST: "MOV", // most active / top movers
  PRTU: "PORT", // portfolio
  MENU: "FUNC", // function directory
  DIR: "FUNC", // function directory
});
