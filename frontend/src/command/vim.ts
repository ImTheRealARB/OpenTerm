/**
 * Opt-in vim editing for the command line (pure state machine; unit-tested in vim.test.ts).
 * Insert mode is the normal input. Esc enters normal mode: h l w b e 0 ^ $ move, x D dd dw de d$ d0 edit,
 * i a A I insert, cw ce cc C change, k / j walk the command history. Enter always runs the command.
 */
export type VimMode = "insert" | "normal";
export interface VimState {
  mode: VimMode;
  /** Operator waiting for a motion: "d" or "c". */
  pending: "" | "d" | "c";
}
export interface VimResult {
  state: VimState;
  text: string;
  cursor: number;
  /** The key was consumed (the caller prevents its default). */
  handled: boolean;
  action?: "historyPrev" | "historyNext";
}

export const VIM_INSERT: VimState = { mode: "insert", pending: "" };

/** 0 = blank, 1 = word character, 2 = other punctuation (vim's "word" classes). */
const cls = (ch: string | undefined): number => (ch === undefined || /\s/.test(ch) ? 0 : /\w/.test(ch) ? 1 : 2);

export function nextWordStart(t: string, i: number): number {
  const c = cls(t[i]);
  if (c) while (i < t.length && cls(t[i]) === c) i++;
  while (i < t.length && cls(t[i]) === 0) i++;
  return i;
}

export function prevWordStart(t: string, i: number): number {
  i--;
  while (i > 0 && cls(t[i]) === 0) i--;
  const c = cls(t[i]);
  while (i > 0 && cls(t[i - 1]) === c) i--;
  return Math.max(0, i);
}

/** Index of the last character of the word at or after i + 1. */
export function wordEnd(t: string, i: number): number {
  i++;
  while (i < t.length && cls(t[i]) === 0) i++;
  const c = cls(t[i]);
  while (i + 1 < t.length && cls(t[i + 1]) === c) i++;
  return Math.min(i, Math.max(0, t.length - 1));
}

const firstNonBlank = (t: string) => {
  const m = /\S/.exec(t);
  return m ? m.index : 0;
};
const clampNormal = (t: string, i: number) => Math.max(0, Math.min(i, t.length - 1));

const NORMAL: VimState = { mode: "normal", pending: "" };

/** Handles one keydown. `key` is KeyboardEvent.key; modified chords should not be passed in. */
export function vimKey(st: VimState, key: string, text: string, cursor: number): VimResult {
  const out = (state: VimState, t = text, c = cursor, action?: VimResult["action"]): VimResult => ({
    state, text: t, cursor: state.mode === "normal" ? clampNormal(t, c) : Math.max(0, Math.min(c, t.length)), handled: true, action,
  });
  const pass: VimResult = { state: st, text, cursor, handled: false };

  if (st.mode === "insert") {
    // vim puts the cursor on the last typed character when leaving insert mode.
    return key === "Escape" ? out(NORMAL, text, cursor - 1) : pass;
  }

  if (st.pending) {
    const op = st.pending;
    const ins = op === "c";
    const cut = (from: number, to: number) => {
      const t = text.slice(0, from) + text.slice(to);
      return out(ins ? VIM_INSERT : NORMAL, t, from);
    };
    switch (key) {
      case "d":
      case "c":
        if (key !== op) return out(NORMAL);
        return out(ins ? VIM_INSERT : NORMAL, "", 0); // dd / cc: the whole line
      case "w":
        // vim treats cw like ce (the trailing blank stays).
        if (ins && cls(text[cursor]) !== 0) return cut(cursor, wordEnd(text, cursor - 1) + 1);
        return cut(cursor, nextWordStart(text, cursor));
      case "e":
        return cut(cursor, wordEnd(text, cursor) + 1);
      case "b":
        return cut(prevWordStart(text, cursor), cursor);
      case "$":
      case "End":
        return cut(cursor, text.length);
      case "0":
      case "Home":
        return cut(0, cursor);
      default:
        return out(NORMAL); // unknown motion cancels the operator
    }
  }

  switch (key) {
    case "Escape":
    case "Enter":
    case "Tab":
      return pass; // Esc in normal mode blurs; Enter runs; Tab accepts a suggestion
    case "i":
      return out(VIM_INSERT);
    case "a":
      return out(VIM_INSERT, text, Math.min(text.length, cursor + 1));
    case "A":
      return out(VIM_INSERT, text, text.length);
    case "I":
      return out(VIM_INSERT, text, firstNonBlank(text));
    case "h":
    case "ArrowLeft":
    case "Backspace":
      return out(NORMAL, text, cursor - 1);
    case "l":
    case "ArrowRight":
    case " ":
      return out(NORMAL, text, cursor + 1);
    case "0":
    case "Home":
      return out(NORMAL, text, 0);
    case "^":
      return out(NORMAL, text, firstNonBlank(text));
    case "$":
    case "End":
      return out(NORMAL, text, text.length - 1);
    case "w":
      return out(NORMAL, text, nextWordStart(text, cursor));
    case "b":
      return out(NORMAL, text, prevWordStart(text, cursor));
    case "e":
      return out(NORMAL, text, wordEnd(text, cursor));
    case "x":
    case "Delete":
      return out(NORMAL, text.slice(0, cursor) + text.slice(cursor + 1), cursor);
    case "D":
      return out(NORMAL, text.slice(0, cursor), cursor);
    case "C":
      return out(VIM_INSERT, text.slice(0, cursor), cursor);
    case "d":
    case "c":
      return out({ mode: "normal", pending: key });
    case "k":
    case "ArrowUp":
      return out(NORMAL, text, cursor, "historyPrev");
    case "j":
    case "ArrowDown":
      return out(NORMAL, text, cursor, "historyNext");
    default:
      // Printable keys never type in normal mode; named keys (F5, ...) fall through.
      return key.length === 1 ? out(st) : pass;
  }
}
