/**
 * Matching a call's arguments to a function's parameters (positional first, then named). Used by BOTH the checker (to
 * report mistakes) and the compiler (to know which expression feeds which parameter), so the rules live in one place.
 * Pure.
 */
import type { Arg, Expr } from "./ast";

export interface ParamLike {
  name: string;
  /** Has a default (so it may be left out). */
  optional: boolean;
}

export interface Matched {
  /** One entry per parameter: the argument expression, or undefined when the caller left it out. */
  slots: (Expr | undefined)[];
  /** Extra positional arguments beyond the parameters (variadic functions only). */
  extra: Expr[];
}

/** The `FOO TAKES 2 TO 3 ARGUMENTS` text for a function. */
export function arityText(display: string, min: number, max: number): string {
  const word = (n: number) => `${n} ARGUMENT${n === 1 ? "" : "S"}`;
  if (max === Infinity) return `${display} TAKES ${min} OR MORE ARGUMENTS`;
  if (min === max) return `${display} TAKES ${word(max)}`;
  return `${display} TAKES ${min} TO ${max} ARGUMENTS`;
}

/**
 * Match `args` to `params`. Returns the match, or an error `{ msg, arg }` (the arg to point at, if any).
 * `display` is the function name as it should appear in messages (upper case).
 */
export function matchArgs(
  display: string,
  params: ParamLike[],
  variadic: boolean,
  args: Arg[],
): Matched | { msg: string; arg?: Arg } {
  const slots: (Expr | undefined)[] = new Array(params.length).fill(undefined);
  const extra: Expr[] = [];
  const min = params.filter((p) => !p.optional).length;
  const max = variadic ? Infinity : params.length;
  let pos = 0;
  for (const a of args) {
    if (a.name === undefined) {
      if (pos < params.length) slots[pos++] = a.value;
      else if (variadic) extra.push(a.value);
      else return { msg: arityText(display, min, max), arg: a };
    } else {
      const k = params.findIndex((p) => p.name === a.name);
      if (k < 0) return { msg: `UNKNOWN ARGUMENT ${a.name.toUpperCase()} FOR ${display}`, arg: a };
      if (slots[k] !== undefined) return { msg: `ARGUMENT ${a.name.toUpperCase()} GIVEN TWICE`, arg: a };
      slots[k] = a.value;
    }
  }
  for (let k = 0; k < params.length; k++) {
    if (slots[k] === undefined && !params[k].optional) return { msg: arityText(display, min, max) };
  }
  return { slots, extra };
}

/** A parameter default written as source text in names.ts ("0", "na", "false", '"line"', "-1") to a value. */
export function defaultValue(def: string): number | string {
  if (def === "na") return NaN;
  if (def === "false") return 0;
  if (def === "true") return 1;
  if (def.startsWith('"') || def.startsWith("'")) return def.slice(1, -1);
  return Number(def);
}
