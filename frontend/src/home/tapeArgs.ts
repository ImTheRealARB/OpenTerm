/**
 * The TAPE command (pure; unit-tested):
 *   TAPE                 show the list
 *   TAPE ADD SYM [MKT]   add a symbol (a market word like NS turns RELIANCE into RELIANCE.NS, as everywhere else)
 *   TAPE DEL SYM         remove it
 *   TAPE RESET           back to the default list
 *   TAPE ON | OFF        also show the tape in the top bar on every screen
 */
import { MARKET_SUFFIX, resolveSecurity } from "../command/markets";
import { TAPE_DEFAULT, TAPE_MAX, TAPE_SYMBOL_RE, type Settings } from "../settings/schema";

export type TapeResult = { ok: true; next: Settings; message: string } | { ok: false; error: string };

const fail = (error: string): TapeResult => ({ ok: false, error });
const USAGE = "TAPE [ADD SYM | DEL SYM | RESET | ON | OFF]";

export function tapeCommand(args: string[], cur: Settings): TapeResult {
  const word = (args[0] ?? "").toUpperCase();
  const list = cur.tapeSymbols;
  switch (word) {
    case "":
      // Showing the list changes nothing: `next` is the unchanged settings.
      return { ok: true, next: cur, message: `TAPE${cur.tape ? " (TOP BAR ON)" : ""}: ${list.length ? list.join(" ") : "EMPTY, USE TAPE ADD SYM"}` };
    case "ON":
    case "OFF":
      return { ok: true, next: { ...cur, tape: word === "ON" }, message: `TICKER TAPE IN THE TOP BAR ${word}` };
    case "RESET":
      return { ok: true, next: { ...cur, tapeSymbols: [...TAPE_DEFAULT] }, message: "TAPE RESET TO THE DEFAULT SYMBOLS" };
    case "ADD": {
      if (!args[1]) return fail(`TAPE ADD SYM [MKT], E.G. TAPE ADD RELIANCE NS. ${USAGE}`);
      const market = args[2]?.toUpperCase();
      if (args.length > 3 || (market && !(market in MARKET_SUFFIX))) return fail(`TAPE ADD SYM [MKT]: ${market ?? ""} IS NOT A MARKET WORD`);
      const symbol = resolveSecurity(args[1], market).symbol;
      if (!TAPE_SYMBOL_RE.test(symbol)) return fail(`BAD TAPE SYMBOL ${args[1].toUpperCase().slice(0, 24)}`);
      if (list.includes(symbol)) return fail(`${symbol} IS ALREADY ON THE TAPE`);
      if (list.length >= TAPE_MAX) return fail(`THE TAPE HOLDS ${TAPE_MAX} SYMBOLS AT MOST: TAPE DEL ONE FIRST`);
      return { ok: true, next: { ...cur, tapeSymbols: [...list, symbol] }, message: `ADDED ${symbol} TO THE TAPE (${list.length + 1})` };
    }
    case "DEL":
    case "RM": {
      if (!args[1]) return fail(`TAPE DEL SYM. ${USAGE}`);
      const market = args[2]?.toUpperCase();
      const symbol = resolveSecurity(args[1], market && market in MARKET_SUFFIX ? market : undefined).symbol;
      if (!list.includes(symbol)) return fail(`${symbol} IS NOT ON THE TAPE (TAPE SHOWS THE LIST)`);
      return { ok: true, next: { ...cur, tapeSymbols: list.filter((s) => s !== symbol) }, message: `REMOVED ${symbol} FROM THE TAPE (${list.length - 1})` };
    }
    default:
      return fail(USAGE);
  }
}
