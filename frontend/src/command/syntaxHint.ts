/**
 * Excel-style syntax hint for the command line: "GP [1D..MAX] [D|W|MO] ..." with the argument being typed marked active.
 * Pure (no React, no registry import): the caller passes the function lookups, so vitest runs it in Node.
 * It reads the free-text `argsSchema` of the registry: top-level pieces are bracket groups `[...]`, angle groups `<...>`
 * or single words; each piece is one slot, and its literal capitalised words are the values offered for it.
 */
import { GP_RANGES } from "./natural";

export interface HintSlot {
  text: string;
  active: boolean;
}

export interface Hint {
  code: string;
  slots: HintSlot[];
  /** Values offered for the active slot (already filtered by what is typed and minus those already used). */
  values: string[];
  /** The partial word being typed (upper case), "" after a space. */
  token: string;
  /** True when the active slot takes a ticker (the caller fills `values` from its own lists). */
  wantsSymbol: boolean;
}

export interface HintEnv {
  isFunction(code: string): boolean;
  argsSchema(code: string): string | undefined;
  /** Tickers to offer for a SYM slot (recent symbols, or the loaded universe). */
  symbols?: readonly string[];
}

/** Splits a schema into slot strings: "[A|Q] [IS|BS|CF]" -> ["[A|Q]", "[IS|BS|CF]"]; "SERIES_ID [1Y|MAX]" -> two. */
export function splitSchema(schema: string): string[] {
  const out: string[] = [];
  let cur = "";
  let depth = 0;
  for (const ch of schema) {
    if (ch === "[" || ch === "<") depth++;
    if (ch === "]" || ch === ">") depth = Math.max(0, depth - 1);
    if (/\s/.test(ch) && depth === 0) {
      if (cur) out.push(cur);
      cur = "";
    } else cur += ch;
  }
  if (cur) out.push(cur);
  // A `|` between top-level pieces ("[NAME] | DEL NAME") keeps both sides readable as separate pieces; the bar itself is dropped.
  return out.filter((s) => s !== "|");
}

const PLACEHOLDER = /^(SYMS?|SYM\.\.\.|NAME|CCY|PRICE|PCT|ID|FORM|CODE|N|SERIES_ID|PAIR|COIN|TEXT|LEVELS|QTY|COST|PEERS|RULE|COUNTRY|CHAIN|PROJECT)$/;

/** The literal words of a slot ("[1D..MAX]" -> the ranges, "[D|W|MO]" -> D, W, MO). Placeholders (SYM, NAME) are not values. */
export function slotValues(slot: string): string[] {
  const inner = slot.replace(/^[[<]|[\]>]$/g, "");
  const range = /^(\d+[A-Z]+)\.\.(MAX)$/.exec(inner);
  if (range) {
    const from = GP_RANGES.indexOf(range[1]);
    return from >= 0 ? GP_RANGES.slice(from) : [];
  }
  const out: string[] = [];
  for (const w of inner.split(/[\s|]+/)) {
    if (/^[A-Z0-9][A-Z0-9:+\-%]*$/.test(w) && !PLACEHOLDER.test(w) && !out.includes(w)) out.push(w);
  }
  return out;
}

const takesSymbol = (slot: string): boolean => /(^|[\s[<|])SYMS?(\.\.\.)?([\s\]>|]|$)/.test(slot);

/** `text` is what is in the command line up to the cursor. Null when no function code is in it (nothing to hint). */
export function syntaxHint(text: string, env: HintEnv): Hint | null {
  const body = text.replace(/^\s*[1-9]\s*:\s*/, "").trimStart();
  if (!body) return null;
  const tokens = body.split(/\s+/);
  const endsOpen = /\s$/.test(text); // a space after the last word: the next word is a new one
  const words = endsOpen ? tokens.filter(Boolean) : tokens;
  // The function code: the first word, or the one after the security / market / sector words ("AAPL US GP").
  let at = -1;
  for (let i = 0; i < Math.min(words.length, 4); i++) {
    if (env.isFunction(words[i].toUpperCase())) {
      at = i;
      break;
    }
  }
  if (at < 0) return null;
  const code = words[at].toUpperCase();
  // The code itself is still being typed: no argument yet.
  if (!endsOpen && at === words.length - 1) {
    return { code, slots: splitSchema(env.argsSchema(code) ?? "").map((text) => ({ text, active: false })), values: [], token: "", wantsSymbol: false };
  }
  const slotsText = splitSchema(env.argsSchema(code) ?? "");
  const argWords = words.slice(at + 1);
  const token = endsOpen ? "" : (argWords.pop() ?? "").toUpperCase();
  const done = argWords.map((w) => w.toUpperCase());
  const valuesOf = slotsText.map(slotValues);
  const used = slotsText.map((s, i) => done.some((w) => valuesOf[i].includes(w)) || (takesSymbol(s) && done.some((w) => !valuesOf.some((v) => v.includes(w)))));
  // Active slot: the one whose values the partial word starts like, else the first one not used yet, else the last.
  let active = token ? slotsText.findIndex((_, i) => !used[i] && valuesOf[i].some((v) => v.startsWith(token))) : -1;
  if (active < 0) active = used.findIndex((u) => !u);
  if (active < 0) active = slotsText.length - 1;
  const wantsSymbol = active >= 0 && takesSymbol(slotsText[active]);
  let values = active >= 0 ? valuesOf[active].filter((v) => !done.includes(v) && v.startsWith(token)) : [];
  if (wantsSymbol && env.symbols) {
    const syms = env.symbols.filter((s) => s.toUpperCase().startsWith(token) && !done.includes(s.toUpperCase())).slice(0, 8);
    values = [...values, ...syms];
  }
  return { code, slots: slotsText.map((text, i) => ({ text, active: i === active })), values, token, wantsSymbol };
}
