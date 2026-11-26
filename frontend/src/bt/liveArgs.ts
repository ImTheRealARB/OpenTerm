/** `BT LIVE` arguments (Phase 26 paper forward tests). Pure, so vitest can cover it.
 *
 *   BT LIVE                          list the forward tests
 *   BT LIVE AAPL @mystrategy [1D|1W] [CASH=n]   start one (play money, OpenTerm's own book: no broker, no order)
 *   BT LIVE STOP <id> · BT LIVE DEL <id>        stop checking one / delete it
 */
export type LiveArgs =
  | { ok: true; act: "list" }
  | { ok: true; act: "start"; symbol: string; strategy: string; interval: "1D" | "1W"; cash?: number }
  | { ok: true; act: "stop" | "del"; id: string }
  | { ok: false; error: string };

export const LIVE_USAGE = "USAGE: BT LIVE · BT LIVE <SYMBOL> @<SAVED STRATEGY> [1D|1W] [CASH=n] · BT LIVE STOP <ID> · BT LIVE DEL <ID>";
const ID_RE = /^[0-9a-f]{8}$/i;

export function parseLiveArgs(args: string[]): LiveArgs {
  if (!args.length) return { ok: true, act: "list" };
  const head = args[0].toUpperCase();
  if (head === "STOP" || head === "DEL") {
    if (args.length !== 2 || !ID_RE.test(args[1])) return { ok: false, error: `USAGE: BT LIVE ${head} <ID> (8 CHARACTERS, FROM BT LIVE)` };
    return { ok: true, act: head === "STOP" ? "stop" : "del", id: args[1].toLowerCase() };
  }
  const m = /^@([A-Za-z0-9_-]{1,40})$/.exec(args[1] ?? "");
  if (!m) return { ok: false, error: LIVE_USAGE };
  let interval: "1D" | "1W" = "1D";
  let cash: number | undefined;
  for (const a of args.slice(2)) {
    const u = a.toUpperCase();
    if (u === "1D" || u === "1W") interval = u;
    else if (u.startsWith("CASH=") && Number(u.slice(5)) >= 1 && Number(u.slice(5)) <= 1e12) cash = Number(u.slice(5));
    else return { ok: false, error: `UNKNOWN BT LIVE OPTION ${a} · ${LIVE_USAGE}` };
  }
  return { ok: true, act: "start", symbol: head, strategy: m[1].toLowerCase(), interval, ...(cash !== undefined ? { cash } : {}) };
}
