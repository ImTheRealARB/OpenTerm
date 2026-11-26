/**
 * IMPORT arguments (pure, so vitest covers it). What the panel does is decided here from the words after IMPORT:
 *   IMPORT | IMPORT LIST                 list stored imports and synthetics
 *   IMPORT DEL <SYMBOL>                  remove an import
 *   IMPORT <SYMBOL> [TZ=<zone>]          paste box; TZ names the zone of intraday times written without an offset (Phase 22)
 *   IMPORT SYNTH <NAME> = <formula>      store a synthetic symbol, e.g. IMPORT SYNTH PAIR = AAPL/MSFT (Phase 22)
 *   IMPORT SYNTH DEL <NAME>              remove one
 */
export type ImportAction =
  | { kind: "list"; del?: string }
  | { kind: "paste"; symbol: string; tz?: string }
  | { kind: "synth"; name: string; formula: string }
  | { kind: "synthDel"; name: string }
  | { kind: "error"; message: string };

const SYNTH_USAGE = "USAGE: IMPORT SYNTH <NAME> = <FORMULA>, E.G. IMPORT SYNTH PAIR = AAPL/MSFT";

export function parseImportArgs(args: string[]): ImportAction {
  const first = args[0]?.toUpperCase();
  if (!first || first === "LIST") return { kind: "list" };
  if (first === "DEL") return { kind: "list", del: args[1]?.toUpperCase() ?? "" };
  if (first === "SYNTH") {
    if (args[1]?.toUpperCase() === "DEL") return args[2] ? { kind: "synthDel", name: args[2].toUpperCase() } : { kind: "error", message: "USAGE: IMPORT SYNTH DEL <NAME>" };
    // The words are joined back so `PAIR = AAPL / MSFT` and `PAIR=AAPL/MSFT` both work. The FIRST `=` splits name from formula,
    // so a formula may still use futures and FX symbols (`SPREAD = ES=F-NQ=F`).
    const m = /^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(args.slice(1).join(" ").trim());
    return m ? { kind: "synth", name: m[1].toUpperCase(), formula: m[2].trim() } : { kind: "error", message: SYNTH_USAGE };
  }
  // A zone name keeps its case (America/New_York); the server matches it ignoring case anyway.
  const tzArg = args.slice(1).find((a) => /^TZ=/i.test(a));
  return { kind: "paste", symbol: first, ...(tzArg ? { tz: tzArg.slice(3) } : {}) };
}
