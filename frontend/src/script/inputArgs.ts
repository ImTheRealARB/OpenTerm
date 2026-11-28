/**
 * Per-chart script inputs (pure). `GP AAPL SCRIPT=RSI_BANDS(14,70)` stores the values as RAW TEXT in the order of the script's
 * `input.*` calls (`functions/gpArgs.ts`); this file turns them into the typed values the engine takes (by input TITLE) and back.
 * Only types are imported from the engine, so it is safe in the worker, the GP panel and vitest.
 */
import type { InputDef } from "./checker";

export interface InputsFromRaw {
  /** Typed overrides by input title (only the inputs the user changed). */
  values: Record<string, unknown>;
  /** Plain-English problems ("RSI LENGTH NEEDS A NUMBER"); empty when every value was usable. */
  errors: string[];
}

const TRUE = new Set(["true", "1", "on", "yes"]);
const FALSE = new Set(["false", "0", "off", "no"]);

/** Raw positional text -> typed overrides. An empty slot keeps the script's default. A bad value is reported, never guessed. */
export function inputsFromRaw(defs: readonly InputDef[], raw: readonly string[]): InputsFromRaw {
  const values: Record<string, unknown> = {};
  const errors: string[] = [];
  if (raw.length > defs.length) errors.push(`TOO MANY INPUTS: THE SCRIPT HAS ${defs.length}, YOU GAVE ${raw.length}`);
  defs.forEach((d, i) => {
    const text = raw[i];
    if (text === undefined || text === "") return;
    if (d.kind === "int" || d.kind === "float") {
      const n = Number(text);
      if (!Number.isFinite(n)) errors.push(`${d.title.toUpperCase()} NEEDS A NUMBER`);
      else values[d.title] = n;
    } else if (d.kind === "bool") {
      const t = text.toLowerCase();
      if (TRUE.has(t)) values[d.title] = true;
      else if (FALSE.has(t)) values[d.title] = false;
      else errors.push(`${d.title.toUpperCase()} NEEDS TRUE OR FALSE`);
    } else {
      values[d.title] = text;
    }
  });
  return { values, errors };
}

/** The text of one value as a user would type it. */
function show(v: unknown): string {
  return typeof v === "boolean" ? (v ? "true" : "false") : String(v);
}

/**
 * The form's text boxes (one per input, in order) -> the raw positional list `gpArgs` stores. A box equal to the script's
 * default becomes "" and trailing defaults are dropped, so an untouched form leaves the args as they were (`SCRIPT=NAME`).
 */
export function rawFromTexts(defs: readonly InputDef[], texts: readonly string[]): string[] {
  const out = defs.map((d, i) => {
    const t = (texts[i] ?? "").trim();
    return t === "" || t === show(d.defval) ? "" : t;
  });
  while (out.length && out[out.length - 1] === "") out.pop();
  return out;
}

/** The value shown in the form for an input: the override when there is one, else the default (as text). */
export function formText(def: InputDef, raw: readonly string[], index: number): string {
  const t = raw[index];
  return t !== undefined && t !== "" ? t : show(def.defval);
}
