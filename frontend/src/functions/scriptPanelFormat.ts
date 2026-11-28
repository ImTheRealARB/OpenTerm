/**
 * SCRIPT panel: pure text helpers for the lines shown around the editor (compile errors, the inputs list, the import report).
 * No React, no request layer: vitest loads it.
 */

/** One problem the checker found. `line` and `col` count from 1. */
export interface ScriptProblem {
  msg: string;
  line: number;
  col: number;
}

/** `LINE 12:5 UNKNOWN NAME FOO`. A problem with no position says only the message. */
export function problemText(p: ScriptProblem): string {
  return p.line > 0 ? `LINE ${p.line}:${p.col > 0 ? p.col : 1} ${p.msg}` : p.msg;
}

/**
 * One setting of the script (`input.int(...)` and friends) as a line for the read-only list under the editor:
 * `Length: int, default 14, 1 to 200`. The engine's input record is read loosely (the field names are the engine's), so a
 * missing field just leaves its part out.
 */
export function describeInput(i: Record<string, unknown>): string {
  const title = String(i.title ?? i.name ?? "?");
  const kind = String(i.type ?? i.kind ?? "");
  const def = i.defval ?? i.def ?? i.default;
  const parts: string[] = [];
  if (kind) parts.push(kind);
  if (def !== undefined && def !== null) parts.push(`default ${String(def)}`);
  const min = i.min;
  const max = i.max;
  const has = (x: unknown) => typeof x === "number" && Number.isFinite(x);
  if (has(min) && has(max)) parts.push(`${min} to ${max}`);
  else if (has(min)) parts.push(`at least ${min}`);
  else if (has(max)) parts.push(`at most ${max}`);
  if (Array.isArray(i.options) && i.options.length) parts.push(`one of ${i.options.join(", ")}`);
  return parts.length ? `${title}: ${parts.join(", ")}` : title;
}

/** One line of the importer's report (spec 6). */
export interface ImportLine {
  line: number;
  text: string;
  status: "ok" | "changed" | "dropped";
  note: string;
}

export interface ImportSummary {
  /** `12 LINES KEPT, 3 CHANGED, 2 DROPPED` */
  headline: string;
  /** The changed and dropped lines (the ones worth reading), at most `max` of them, as `LINE 4 DROPPED: <note>`. */
  lines: string[];
  /** How many changed or dropped lines did not fit in `lines`. */
  more: number;
}

/** Counts and the first problems of an import report. Kept lines are counted, not listed. */
export function summarizeReport(report: readonly ImportLine[], max = 12): ImportSummary {
  const kept = report.filter((r) => r.status === "ok").length;
  const changed = report.filter((r) => r.status === "changed");
  const dropped = report.filter((r) => r.status === "dropped");
  const notable = report.filter((r) => r.status !== "ok");
  const lines = notable.slice(0, max).map((r) => `LINE ${r.line} ${r.status.toUpperCase()}${r.note ? `: ${r.note}` : ""}`);
  return {
    headline: `${kept} LINES KEPT, ${changed.length} CHANGED, ${dropped.length} DROPPED`,
    lines,
    more: Math.max(0, notable.length - lines.length),
  };
}
