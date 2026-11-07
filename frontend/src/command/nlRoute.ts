/**
 * Routing of plain-English input (pure, lazy side; see nlResolve.ts). Order:
 *   1. compare ("apple vs microsoft 1 year" -> `AAPL GP 1Y VS MSFT`)
 *   2. screener ("tech stocks with price under 50" -> `EQS <text>`), only for plural stock words plus a recognised filter
 *   3. company + intent (natural.ts)
 * Exact function codes never get here (nlRun.needsNatural).
 */
import { interpretScreener, looksLikeEnglish } from "../functions/eqsNatural";
import { NEWS_SECTIONS } from "../functions/newsArgs";
import { compareCommand, parseCompare, type CompareParse } from "./compareNatural";
import { fxPair } from "./nlAliases";
import { extractRange } from "./nlRange";
import { interpretNatural, type NlContext } from "./natural";

export type RouteResult =
  | { kind: "command"; command: string; why: string }
  | { kind: "choices"; choices: { command: string; label: string }[] }
  | { kind: "error"; message: string }
  /** `lookup`: see natural.ts NlResult; nlResolve.ts may answer it with Yahoo's name search. */
  | { kind: "none"; lookup?: { phrase: string; template: string } };

const STOCK_WORDS = /\b(?:stocks|shares|companies|equities)\b/;

const symbolOf = (command: string): string => command.split(" ")[0];

/**
 * "news tech" -> `N TECH`: the word "news" plus exactly one section word is a news-section request, not a company name.
 * Why a rule here and not a blanket alias "news" -> N in functions/aliases.ts: an alias would also turn "news apple" into
 * `N APPLE` (a keyword search), but "news apple" must stay "AAPL N" (Apple's headlines), which the company + intent
 * path below already does. So we only step in when the second word is a real section.
 * The list is imported from newsArgs.ts (its single home), never copied, so a new section works here automatically.
 */
function newsSection(body: string): string | null {
  const words = body.trim().toUpperCase().split(/\s+/);
  return words.length === 2 && words[0] === "NEWS" && NEWS_SECTIONS.includes(words[1]) ? words[1] : null;
}

function route(body: string, ctx: NlContext): RouteResult {
  const section = newsSection(body);
  if (section) return { kind: "command", command: `N ${section}`, why: "N SECTION" };
  const cmp = parseCompare(body);
  if (cmp && !isCurrencyPair(cmp)) return routeCompare(body, ctx);
  if (STOCK_WORDS.test(body.toLowerCase()) && looksLikeEnglish(body) && interpretScreener(body).args.length) {
    return { kind: "command", command: `EQS ${body.trim()}`, why: "EQS" };
  }
  return interpretNatural(body, ctx);
}

/** "dollar vs rupee", "usd vs inr": two currencies are one exchange rate, not a comparison of two securities. */
const isCurrencyPair = (c: CompareParse): boolean => c.more.length === 0 && fxPair(`${c.a} ${c.b}`) !== null;

function routeCompare(original: string, ctx: NlContext): RouteResult {
  // The range is read by the shared reader (nlRange: word numbers, "18 months", "since 2021" -> the closest GP range) and cut out
  // of the sentence first; compareNatural then only has to split the names. If cutting it leaves no two names ("apple vs 3m"),
  // the original sentence is used and compareNatural's own range reading applies.
  const st = { s: original.toLowerCase() };
  const found = extractRange(st, ctx.now ?? new Date());
  const cut = found && parseCompare(st.s) ? st.s : null;
  const body = cut ?? original;
  const range = cut ? found!.range : undefined;
  const note = cut ? found!.note : undefined;
  /** Puts the range into `AAPL GP VS MSFT` -> `AAPL GP 5Y VS MSFT`. */
  const withRange = (command: string): string => (range ? command.replace(/^(\S+) GP/, `$1 GP ${range}`) : command);
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
  if (!ambiguous) return { kind: "command", command: withRange(base.command!), why: ["GP VS", note].filter(Boolean).join(" · ") };
  const { phrase, hits } = ambiguous;
  const choices = hits.flatMap((h) => {
    const c = build({ phrase, symbol: h.symbol }).command;
    return c ? [{ command: withRange(c), label: h.label }] : [];
  });
  return choices.length ? { kind: "choices", choices } : { kind: "error", message: base.error ?? "COMPARE NEEDS TWO DIFFERENT NAMES" };
}

export { route as routeNatural };
