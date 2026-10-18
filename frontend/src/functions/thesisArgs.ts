/** `THESIS [SYMBOL]`, `THESIS ADD <SYMBOL> <text...>`, `THESIS INVALID <id> <text...>` (pure, unit-tested). */
export type ThesisArgs =
  | { mode: "list"; symbol: string | null }
  | { mode: "add"; symbol: string; text: string }
  | { mode: "invalid"; id: number; text: string }
  | { mode: "bad"; error: string };

const SYMBOL = /^[A-Za-z0-9.^=-]{1,12}$/;

export function thesisArgs(args: string[]): ThesisArgs {
  const first = (args[0] ?? "").toUpperCase();
  if (!first) return { mode: "list", symbol: null };
  if (first === "ADD") {
    const sym = args[1] ?? "";
    const text = args.slice(2).join(" ").trim();
    return SYMBOL.test(sym) && text ? { mode: "add", symbol: sym.toUpperCase(), text } : { mode: "bad", error: "USAGE: THESIS ADD <SYMBOL> <your thesis in words>" };
  }
  if (first === "INVALID") {
    const id = Number(args[1]);
    const text = args.slice(2).join(" ").trim();
    return Number.isInteger(id) && id > 0 && text ? { mode: "invalid", id, text } : { mode: "bad", error: "USAGE: THESIS INVALID <id> <what would prove the thesis wrong>" };
  }
  return args.length === 1 && SYMBOL.test(args[0]) ? { mode: "list", symbol: first } : { mode: "bad", error: "USAGE: THESIS [SYMBOL] | ADD <SYMBOL> <text> | INVALID <id> <text>" };
}

export const STATUSES = ["open", "confirmed", "invalidated", "closed"] as const;
export function nextStatus(s: string): (typeof STATUSES)[number] {
  const i = (STATUSES as readonly string[]).indexOf(s);
  return STATUSES[(i + 1) % STATUSES.length];
}
