/**
 * OpenTerm Script engine: the public entry (spec section 2).
 *
 *   const r = compile(source);
 *   if (!r.ok) show(r.errors);                       // [{ msg, line, col }]
 *   else {
 *     r.program.meta                                 // title, overlay, inputs, requests, conditions, usesLib
 *     const run = r.program.run(bars, { inputs });   // bars = { o, h, l, c, v, t }
 *     run.result()                                   // plain data: plots, drawings, alerts, conditions, error, stats
 *     run.updateLast(bar); run.append(bar);          // live ticks
 *   }
 *
 * Pure code (no DOM, no network, no eval): it runs in the indicator Web Worker, on the main thread (the editor's live
 * check) and in vitest.
 */
import { ScriptCompileError, type ScriptError } from "./ast";
import { check } from "./checker";
import { Program } from "./runtime";
import { parse } from "./parser";
import { LIMITS } from "./names";

export type { ScriptError } from "./ast";
export type { InputDef, InputKind, ProgramMeta } from "./checker";
export type { Bar, BarCols, DrawingsOut, PlotOut, RunOpts, ScriptResult, ScriptTick } from "./runtime";
export { Program, RunState } from "./runtime";

export type CompileResult = { ok: true; program: Program } | { ok: false; errors: ScriptError[] };

/** Check a script and prepare it to run. Never throws: mistakes come back as a list of errors. */
export function compile(src: string): CompileResult {
  if (src.length > LIMITS.sourceChars) {
    return { ok: false, errors: [{ msg: `SOURCE TOO LONG (MAX ${LIMITS.sourceChars} CHARACTERS)`, line: 1, col: 1 }] };
  }
  try {
    const ast = parse(src);
    const checked = check(ast);
    if (checked.errors.length > 0) {
      // in source order, one entry per place and message
      const seen = new Set<string>();
      const errors = checked.errors
        .slice()
        .sort((a, b) => a.line - b.line || a.col - b.col)
        .filter((e) => {
          const k = `${e.line}:${e.col}:${e.msg}`;
          if (seen.has(k)) return false;
          seen.add(k);
          return true;
        });
      return { ok: false, errors };
    }
    return { ok: true, program: new Program(checked.meta, ast, checked) };
  } catch (e) {
    if (e instanceof ScriptCompileError) return { ok: false, errors: e.errors };
    // a very deeply nested script overflows the parser's call stack
    if (e instanceof RangeError) return { ok: false, errors: [{ msg: "SCRIPT TOO DEEPLY NESTED", line: 1, col: 1 }] };
    throw e;
  }
}
