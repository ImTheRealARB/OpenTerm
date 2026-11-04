/**
 * Routing of plain-English input (pure, lazy side; see nlResolve.ts). Order:
 *   1. compare ("apple vs microsoft 1 year" -> `AAPL GP 1Y VS MSFT`)
 *   2. screener ("tech stocks with price under 50" -> `EQS <text>`), only for plural stock words plus a recognised filter
 *   3. company + intent (natural.ts)
 * Exact function codes never get here (nlRun.needsNatural).
 */
import { interpretScreener, looksLikeEnglish } from "../functions/eqsNatural";
import { compareCommand, parseCompare } from "./compareNatural";
import { interpretNatural, type NlContext } from "./natural";

export type RouteResult =
  | { kind: "command"; command: string; why: string }
  | { kind: "choices"; choices: { command: string; label: string }[] }
  | { kind: "error"; message: string }
  | { kind: "none" };

const STOCK_WORDS = /\b(?:stocks|shares|companies|equities)\b/;

const symbolOf = (command: string): string => command.split(" ")[0];

function route(body: string, ctx: NlContext): RouteResult {
  if (parseCompare(body)) return routeCompare(body, ctx);
  if (STOCK_WORDS.test(body.toLowerCase()) && looksLikeEnglish(body) && interpretScreener(body).args.length) {
    return { kind: "command", command: `EQS ${body.trim()}`, why: "EQS" };
  }
  return interpretNatural(body, ctx);
}

function routeCompare(body: string, ctx: NlContext): RouteResult {
  const parse = parseCompare(body)!;
  const picked = new Map<string, string>();
  let ambiguous: { phrase: string; hits: { symbol: string; label: string }[] } | null = null;
  for (const phrase of [parse.a, parse.b, ...parse.more]) {
    const r = interpretNatural(phrase, ctx);
    if (r.kind === "command") picked.set(phrase, symbolOf(r.command));
    else if (r.kind === "choices") {
      picked.set(phrase, symbolOf(r.choices[0].command));
      ambiguous ??= { phrase, hits: r.choices.map((c) => ({ symbol: symbolOf(c.command), label: c.label })) };
    }
  }
  const build = (swap?: { phrase: string; symbol: string }) =>
    compareCommand(body, (p) => (swap && p === swap.phrase ? swap.symbol : (picked.get(p) ?? null)));
  const base = build();
  if (base.error) return { kind: "error", message: base.error };
  if (!ambiguous) return { kind: "command", command: base.command!, why: "GP VS" };
  const { phrase, hits } = ambiguous;
  const choices = hits.flatMap((h) => {
    const c = build({ phrase, symbol: h.symbol }).command;
    return c ? [{ command: c, label: h.label }] : [];
  });
  return choices.length ? { kind: "choices", choices } : { kind: "error", message: base.error ?? "COMPARE NEEDS TWO DIFFERENT NAMES" };
}

export { route as routeNatural };
