/**
 * Pure helper (no `window`, no CodeMirror, so vitest can test it): splits the server's sandbox error text into the
 * offending line number and the message.
 *
 * The backend answers things like "LINE 3: IMPORT os IS NOT ALLOWED ..." (a problem on one line) or
 * "EMPTY STRATEGY" (a problem with the whole file, no line). Save failures carry the same text.
 */
export interface SandboxError {
  /** 1-based line number the server named, or null when the error is about the whole strategy. */
  line: number | null;
  /** The text without the `LINE n: ` prefix (the prefix is shown by the editor as the position of the message). */
  message: string;
}

// ^LINE <digits>: <rest>  (case-insensitive because the server upper-cases its messages, but do not depend on it)
const LINE_PREFIX = /^\s*LINE\s+(\d+)\s*:\s*([\s\S]*)$/i;

export function parseSandboxError(text: string): SandboxError {
  const m = LINE_PREFIX.exec(text);
  if (!m) return { line: null, message: text.trim() };
  const line = Number(m[1]);
  // "LINE 0" cannot be a real line; treat it as a whole-file error rather than decorating a line that does not exist.
  return { line: line >= 1 ? line : null, message: m[2].trim() };
}
