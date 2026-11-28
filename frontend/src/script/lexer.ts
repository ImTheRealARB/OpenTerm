/**
 * OpenTerm Script lexer: turns source text into tokens (spec: docs/specs/PHASE_25.md section 1.1).
 *
 * The one unusual job is INDENTATION. Blocks are marked by indent like Python, so besides words and symbols the lexer
 * emits three layout tokens:
 *   nl      end of a statement line
 *   indent  this line is deeper than the one before (a block starts)
 *   dedent  this line is shallower (a block ends)
 * Rules (spec 1.1): blank and comment-only lines are ignored; a tab counts as 4 spaces; inside ( ) and [ ] newlines and
 * indentation are ignored; a line that ends with a binary operator or a comma continues on the next line.
 */
import { type Pos, type ScriptError, ScriptCompileError } from "./ast";

export type TokKind = "num" | "str" | "color" | "id" | "kw" | "op" | "nl" | "indent" | "dedent" | "eof";

export interface Tok extends Pos {
  k: TokKind;
  /** The text (for `str` the decoded string, for `color` the lower-case hex). */
  s: string;
  /** Number value for `num`. */
  v?: number;
}

export const KEYWORDS = new Set(["if", "else", "for", "to", "by", "while", "break", "continue", "var", "and", "or", "not", "true", "false", "na"]);

/** Longest operators first, so `==` is not read as two `=`. */
const OPS = ["=>", "==", "!=", "<=", ">=", ":=", "+=", "-=", "*=", "/=", "+", "-", "*", "/", "%", "<", ">", "=", "?", ":", ",", "(", ")", "[", "]", "."];

/** A token that, at the end of a line, means "the statement goes on". (`=>` is NOT here: it opens a function block.) */
const CONTINUES = new Set(["+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", "?", ":", "=", ":=", "+=", "-=", "*=", "/=", ","]);
const CONTINUE_KW = new Set(["and", "or", "not"]);

const isDigit = (c: string) => c >= "0" && c <= "9";
const isIdStart = (c: string) => (c >= "a" && c <= "z") || (c >= "A" && c <= "Z") || c === "_";
const isIdChar = (c: string) => isIdStart(c) || isDigit(c);
const isHex = (c: string) => isDigit(c) || (c >= "a" && c <= "f") || (c >= "A" && c <= "F");

function fail(msg: string, line: number, col: number): never {
  throw new ScriptCompileError([{ msg, line, col } satisfies ScriptError]);
}

export function lex(src: string): Tok[] {
  const toks: Tok[] = [];
  const lines = src.split("\n");
  const indents = [0];
  let depth = 0; // how many ( or [ are open
  let continuing = false; // the previous line ended with a binary operator
  let lastLine = 1;

  for (let li = 0; li < lines.length; li++) {
    const raw = lines[li].endsWith("\r") ? lines[li].slice(0, -1) : lines[li];
    const line = li + 1;
    lastLine = line;
    // 1. measure the indentation
    let p = 0;
    let ind = 0;
    while (p < raw.length && (raw[p] === " " || raw[p] === "\t")) {
      ind += raw[p] === "\t" ? 4 : 1;
      p++;
    }
    // blank or comment-only: ignored (also inside brackets)
    if (p >= raw.length || (raw[p] === "/" && raw[p + 1] === "/")) continue;

    // 2. layout tokens (not inside brackets, not on a continued line)
    if (depth === 0 && !continuing) {
      const top = indents[indents.length - 1];
      if (ind > top) {
        indents.push(ind);
        toks.push({ k: "indent", s: "", line, col: 1 });
      } else if (ind < top) {
        while (ind < indents[indents.length - 1]) {
          indents.pop();
          toks.push({ k: "dedent", s: "", line, col: 1 });
        }
        if (ind !== indents[indents.length - 1]) fail("BAD INDENT", line, 1);
      }
    }
    continuing = false;

    // 3. the tokens of the line
    let last: Tok | null = null;
    const push = (t: Tok) => {
      toks.push(t);
      last = t;
    };
    while (p < raw.length) {
      const ch = raw[p];
      const col = p + 1;
      if (ch === " " || ch === "\t") {
        p++;
        continue;
      }
      if (ch === "/" && raw[p + 1] === "/") break; // comment to the end of the line
      // numbers: 12  1.5  .5  1e-3
      if (isDigit(ch) || (ch === "." && isDigit(raw[p + 1] ?? ""))) {
        let j = p;
        while (j < raw.length && isDigit(raw[j])) j++;
        if (raw[j] === "." && isDigit(raw[j + 1] ?? "")) {
          j++;
          while (j < raw.length && isDigit(raw[j])) j++;
        }
        if ((raw[j] === "e" || raw[j] === "E") && (isDigit(raw[j + 1] ?? "") || ((raw[j + 1] === "-" || raw[j + 1] === "+") && isDigit(raw[j + 2] ?? "")))) {
          j += 2;
          while (j < raw.length && isDigit(raw[j])) j++;
        }
        if (j < raw.length && isIdChar(raw[j])) fail(`BAD NUMBER ${raw.slice(p, j + 1)}`, line, col);
        const text = raw.slice(p, j);
        const v = Number(text);
        if (!Number.isFinite(v)) fail(`BAD NUMBER ${text}`, line, col);
        push({ k: "num", s: text, v, line, col });
        p = j;
        continue;
      }
      if (isIdStart(ch)) {
        let j = p + 1;
        while (j < raw.length && isIdChar(raw[j])) j++;
        const word = raw.slice(p, j);
        push({ k: KEYWORDS.has(word) ? "kw" : "id", s: word, line, col });
        p = j;
        continue;
      }
      if (ch === '"' || ch === "'") {
        let j = p + 1;
        let out = "";
        let closed = false;
        while (j < raw.length) {
          const c = raw[j];
          if (c === "\\") {
            const e = raw[j + 1];
            if (e === "n") out += "\n";
            else if (e === "t") out += "\t";
            else if (e === '"' || e === "'" || e === "\\") out += e;
            else fail(`BAD ESCAPE \\${e ?? ""}`, line, j + 1);
            j += 2;
            continue;
          }
          if (c === ch) {
            closed = true;
            j++;
            break;
          }
          out += c;
          j++;
        }
        if (!closed) fail("UNTERMINATED STRING", line, col);
        push({ k: "str", s: out, line, col });
        p = j;
        continue;
      }
      if (ch === "#") {
        let j = p + 1;
        while (j < raw.length && isHex(raw[j])) j++;
        const n = j - p - 1;
        if ((n !== 6 && n !== 8) || (j < raw.length && isIdChar(raw[j]))) fail("BAD COLOUR (USE #RRGGBB OR #RRGGBBAA)", line, col);
        push({ k: "color", s: raw.slice(p, j).toLowerCase(), line, col });
        p = j;
        continue;
      }
      let matched = "";
      for (const op of OPS) {
        if (raw.startsWith(op, p)) {
          matched = op;
          break;
        }
      }
      if (!matched) fail(`UNEXPECTED CHARACTER ${ch}`, line, col);
      if (matched === "(" || matched === "[") depth++;
      else if (matched === ")" || matched === "]") depth = Math.max(0, depth - 1);
      push({ k: "op", s: matched, line, col });
      p += matched.length;
    }

    // 4. end of line: a new statement, or the statement goes on
    // (`last` is set inside the `push` closure, so TypeScript cannot follow it: cast to say what it holds)
    const l = last as Tok | null;
    if (depth === 0 && l) {
      if ((l.k === "op" && CONTINUES.has(l.s)) || (l.k === "kw" && CONTINUE_KW.has(l.s))) continuing = true;
      else toks.push({ k: "nl", s: "", line, col: raw.length + 1 });
    }
  }
  if (depth > 0) fail("EXPECTED )", lastLine, (lines[lastLine - 1]?.length ?? 0) + 1);
  if (continuing) fail("EXPECTED EXPRESSION", lastLine, (lines[lastLine - 1]?.length ?? 0) + 1);
  while (indents.length > 1) {
    indents.pop();
    toks.push({ k: "dedent", s: "", line: lastLine, col: 1 });
  }
  toks.push({ k: "eof", s: "", line: lastLine, col: (lines[lastLine - 1]?.length ?? 0) + 1 });
  return toks;
}
