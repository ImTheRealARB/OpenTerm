/**
 * `ALRT ... SCRIPT=NAME [COND="title"]` argument parsing (Phase 25). Pure, unit-tested directly.
 *
 *   ALRT AAPL SCRIPT=RSI-CROSS                    fire on the script's own alert(...) calls
 *   ALRT AAPL SCRIPT=RSI-CROSS COND="RSI down"    fire when the script's alertcondition titled "RSI down" is true
 *   AAPL ALRT SCRIPT=RSI-CROSS                    the typed security is used
 *   ALRT DEL SC3                                  delete script alert 3 (ids are written SC<n>)
 *
 * Returns null when the arguments are not a script-alert form, so the caller falls through to the price / news parser.
 */
import { isSymbolToken, type SecurityRef } from "./markets";

export type ScriptAlertCmd =
  | { kind: "createScript"; symbol: string; script: string; cond: string | null }
  | { kind: "deleteScript"; id: number }
  | { kind: "error"; message: string };

/** The same rule as a stored script name on the server (`idents.STORED_NAME_RE`; the name is upper-cased first). */
export const SCRIPT_NAME = /^[A-Z0-9][A-Z0-9_.-]{0,31}$/;
/** The longest condition title the server stores (`script_routes.MAX_COND`). */
export const MAX_COND = 80;

const USAGE = 'ALRT SYM SCRIPT=NAME [COND="TITLE"]';

export function parseScriptAlertCmd(args: string[], explicit?: SecurityRef): ScriptAlertCmd | null {
  if (!args.length || args[0].toUpperCase() === "NEWS") return null; // a news phrase may contain the words SCRIPT= / COND=

  // delete: ALRT DEL SC3
  const verb = args[0].toUpperCase();
  if ((verb === "DEL" || verb === "DELETE" || verb === "RM") && args.length === 2 && /^SC\d+$/i.test(args[1])) {
    return { kind: "deleteScript", id: Number(args[1].slice(2)) };
  }

  if (!args.some((t) => /^(SCRIPT|COND)=/i.test(t))) return null;
  let text = ` ${args.join(" ")} `;

  // COND first: its quoted title may hold spaces (and even the word SCRIPT=)
  let cond: string | null = null;
  const c = /\sCOND=(?:"([^"]*)"|'([^']*)'|(\S*))/i.exec(text);
  if (c) {
    const bare = c[3];
    if (bare !== undefined && /^["']/.test(bare)) return { kind: "error", message: `COND NEEDS A CLOSING QUOTE: ${USAGE}` };
    cond = (c[1] ?? c[2] ?? bare ?? "").trim();
    if (!cond) return { kind: "error", message: `COND NEEDS A CONDITION TITLE: ${USAGE}` };
    if (cond.length > MAX_COND) return { kind: "error", message: `COND TITLE: AT MOST ${MAX_COND} CHARACTERS` };
    text = text.slice(0, c.index) + " " + text.slice(c.index + c[0].length);
  }

  const s = /\sSCRIPT=(\S*)/i.exec(text);
  if (!s) return { kind: "error", message: `COND= NEEDS SCRIPT=NAME: ${USAGE}` };
  const script = s[1].toUpperCase();
  if (!script) return { kind: "error", message: `SCRIPT= NEEDS A SCRIPT NAME: ${USAGE}` };
  if (!SCRIPT_NAME.test(script)) return { kind: "error", message: "SCRIPT NAME: 1-32 OF A-Z 0-9 _ . -" };
  text = text.slice(0, s.index) + " " + text.slice(s.index + s[0].length);

  const rest = text.trim().split(/\s+/).filter(Boolean);
  if (rest.some((t) => t.toUpperCase() === "VIA")) {
    return { kind: "error", message: "SCRIPT ALERTS HAVE NO VIA: THEY RUN IN THIS BROWSER WHILE OPENTERM IS OPEN" };
  }
  if (rest.length > 1) return { kind: "error", message: `${USAGE} (QUOTE A TITLE WITH SPACES; EXTRA: ${rest.slice(1).join(" ").toUpperCase()})` };
  const symbol = (rest[0] ?? explicit?.symbol ?? "").toUpperCase();
  if (!symbol) return { kind: "error", message: `ALRT NEEDS A SECURITY: ${USAGE}` };
  if (!isSymbolToken(symbol)) return { kind: "error", message: `BAD SYMBOL: ${symbol}` };
  return { kind: "createScript", symbol, script, cond };
}
