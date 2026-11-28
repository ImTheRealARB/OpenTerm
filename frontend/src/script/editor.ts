/**
 * The OpenTerm Script editor: a CodeMirror 6 box (an open-source browser code editor library) with colours for the language,
 * auto-complete from the built-in list (`names.ts`) and live error marks. It follows `bt/codeEditor.ts`, the strategy editor.
 *
 * IMPORTANT: this file (CodeMirror, ~100 KB) must only be reached through a dynamic `import("../script/editor")` from the SCRIPT
 * panel, so it becomes its own chunk (a separate file the browser downloads on demand) and the startup bundle does not grow.
 * It loads the script engine the same way, with `import("./index")`, the first time a check runs.
 *
 * The API is "imperative" (call methods on a handle) instead of a React component, because CodeMirror owns its own DOM and
 * state: React creates it once, pushes text in, and gets callbacks out.
 *
 * Keys: Ctrl+S saves, Ctrl+Enter saves, checks and adds the script to a chart, Esc leaves the box. Only Ctrl/Cmd+K is allowed to
 * bubble out (it opens the app's command line); every other key stays in the box so panel keys and global shortcuts never fire
 * while typing (Ctrl+S would otherwise also save the whole workspace).
 *
 * Look: only the CSS variables from styles.css (amber on black, themes switch them), system monospace, no shadows, gradients,
 * radii or transitions (project rules).
 */
import { autocompletion, closeCompletion, completionStatus, type Completion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, HighlightStyle, indentUnit, StreamLanguage, syntaxHighlighting, type StringStream } from "@codemirror/language";
import { EditorState, Prec, StateEffect, StateField, Transaction, type Extension } from "@codemirror/state";
import { Decoration, type DecorationSet, drawSelection, EditorView, keymap, lineNumbers, WidgetType } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { BUILTINS, type Builtin } from "./names";

/** One problem to draw: `line` and `col` count from 1. */
export interface EditorProblem {
  msg: string;
  line: number;
  col: number;
}

/**
 * What a check found. `ok` carries what the SCRIPT panel shows (title, settings); `errors` is the compile error list;
 * `failed` means the engine itself could not be loaded or crashed (shown as such, never hidden).
 */
export type CheckOutcome =
  | { kind: "ok"; title: string; overlay: boolean; inputs: Record<string, unknown>[]; usesLib: boolean }
  | { kind: "errors"; errors: EditorProblem[] }
  | { kind: "failed"; message: string };

export interface ScriptEditorOptions {
  doc: string;
  /** Screen-reader name of the editing area (also what e2e looks the box up by). */
  ariaLabel: string;
  onChange: (text: string) => void;
  onSave: () => void;
  /** Ctrl+Enter: save, check and add to a chart. */
  onRun: () => void;
  /** Esc was pressed: the editor has already given up focus. */
  onEscape: () => void;
  /** A check finished (300 ms after the last edit, or after `check()`). Never called for an out-of-date text. */
  onChecked: (outcome: CheckOutcome) => void;
}

export interface ScriptEditor {
  /** Replaces the whole text. Not undoable (loading a file is not an edit). */
  setDoc: (text: string) => void;
  /** The current text. */
  getDoc: () => string;
  /** Checks the current text now and returns the outcome (also marks the errors and calls `onChecked`). */
  check: () => Promise<CheckOutcome>;
  focus: () => void;
  destroy: () => void;
}

/** How long to wait after the last keystroke before checking. */
export const CHECK_DELAY_MS = 300;

// ---------------------------------------------------------------------------------------------------------------------
// Colours for the language: a "stream parser" reads one line at a time and names each piece (keyword, number ...). That is
// much smaller than a full grammar and is all colouring needs. The names are CodeMirror's legacy token names.
// ---------------------------------------------------------------------------------------------------------------------

const KEYWORDS = new Set(["if", "else", "for", "to", "by", "while", "break", "continue", "var", "and", "or", "not"]);
const ATOMS = new Set(["true", "false", "na"]);
const BUILTIN_NAMES = new Set(BUILTINS.map((b) => b.name));
/** `a.b.c`: names joined by dots (ta.sma, color.red, lib.SUPERTREND). A method call like `window.push` is read the same way. */
const WORD = /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*/;
const NUMBER = /^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/;
const COLOR = /^#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})\b/;

function token(stream: StringStream): string | null {
  if (stream.eatSpace()) return null;
  if (stream.match("//")) {
    stream.skipToEnd();
    return "comment";
  }
  const ch = stream.peek();
  if (ch === '"' || ch === "'") {
    stream.next();
    // Read to the closing quote; a backslash escapes the next character. A string cannot span lines: it stops at the line end.
    while (!stream.eol()) {
      const c = stream.next();
      if (c === "\\") stream.next();
      else if (c === ch) break;
    }
    return "string";
  }
  if (stream.match(COLOR)) return "atom";
  if (stream.match(NUMBER)) return "number";
  const word = stream.match(WORD);
  if (word) {
    const w = (word as RegExpMatchArray)[0];
    if (KEYWORDS.has(w)) return "keyword";
    if (ATOMS.has(w)) return "atom";
    if (BUILTIN_NAMES.has(w) || w.startsWith("lib.")) return "builtin";
    return "variable";
  }
  stream.next(); // an operator or bracket: no colour
  return null;
}

const scriptLanguage = StreamLanguage.define({
  name: "openterm-script",
  token,
  languageData: { commentTokens: { line: "//" } },
});

/** Colours: few and meaningful (same palette rules as the strategy editor). */
const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--accent)" },
  { tag: tags.string, color: "var(--up)" },
  { tag: [tags.number, tags.atom], color: "var(--val)" },
  { tag: tags.comment, color: "var(--fg-dim)" },
  { tag: tags.standard(tags.variableName), color: "var(--warn)" },
]);

// ---------------------------------------------------------------------------------------------------------------------
// Auto-complete: every built-in name, with its parameters and one-sentence help. It opens while you type a word and with
// Ctrl+Space. `names.ts` is the one list, so a new built-in shows up here with no change to this file.
// ---------------------------------------------------------------------------------------------------------------------

/** `ta.sma(src, length)`: the call shape shown next to the name. */
function signature(b: Builtin): string {
  if (b.kind === "var") return "";
  const parts = (b.params ?? []).map((p) => (p.def !== undefined ? `${p.name}=${p.def}` : p.name));
  if (b.variadic) parts.push("...");
  return `(${parts.join(", ")})`;
}

const COMPLETIONS: Completion[] = [
  ...BUILTINS.filter((b, i) => BUILTINS.findIndex((x) => x.name === b.name) === i).map(
    (b): Completion => ({
      label: b.name,
      type: b.kind === "fn" ? "function" : "variable",
      detail: signature(b),
      info: b.doc,
    }),
  ),
  ...[...KEYWORDS].map((k): Completion => ({ label: k, type: "keyword" })),
];

function complete(context: CompletionContext): CompletionResult | null {
  const word = context.matchBefore(/[A-Za-z_][\w.]*/);
  // Nothing typed yet: only open on Ctrl+Space (otherwise a popup on every space would be noise).
  if (!word && !context.explicit) return null;
  return { from: word ? word.from : context.pos, options: COMPLETIONS, validFor: /^[\w.]*$/ };
}

// ---------------------------------------------------------------------------------------------------------------------
// Inline errors: a StateField (CodeMirror's way of keeping extra state next to the text) holding "decorations" (marks drawn on
// top of the text without changing it). Per error: a tint on the line plus a small message block right under it.
// ---------------------------------------------------------------------------------------------------------------------

class ErrorWidget extends WidgetType {
  constructor(readonly message: string) {
    super();
  }
  eq(other: ErrorWidget) {
    return other.message === this.message;
  }
  toDOM() {
    const el = document.createElement("div");
    el.className = "cm-sbx-msg";
    el.textContent = this.message; // textContent, never innerHTML: messages must not be parsed as HTML
    return el;
  }
  ignoreEvent() {
    return true;
  }
}

/** At most this many errors are drawn in the text (the panel lists them all under the box). */
const MAX_MARKED = 8;

const setErrorsEffect = StateEffect.define<EditorProblem[]>();

const errorField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    value = value.map(tr.changes); // keep marks attached to their text while the user types; the next check replaces them
    for (const e of tr.effects) {
      if (!e.is(setErrorsEffect)) continue;
      const doc = tr.state.doc;
      const seen = new Set<number>();
      const marks = [];
      for (const p of e.value.slice(0, MAX_MARKED)) {
        const line = doc.line(Math.min(Math.max(p.line, 1), doc.lines)); // clamp: the text may have shrunk since the check
        if (seen.has(line.number)) continue; // one mark per line
        seen.add(line.number);
        marks.push(Decoration.line({ class: "cm-sbx-errline" }).range(line.from));
        marks.push(Decoration.widget({ widget: new ErrorWidget(`${p.col > 0 ? `COL ${p.col}: ` : ""}${p.msg}`), block: true, side: 1 }).range(line.to));
      }
      value = Decoration.set(marks, true);
    }
    return value;
  },
  provide: (f) => EditorView.decorations.from(f),
});

// ---------------------------------------------------------------------------------------------------------------------
// Theme: only CSS variables, so the app's THEME command recolours the editor with no extra code.
// ---------------------------------------------------------------------------------------------------------------------

const theme = EditorView.theme({
  "&": { color: "var(--fg)", backgroundColor: "var(--bg)", fontFamily: "var(--font)", fontSize: "var(--fs)", height: "24em" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "var(--font)", lineHeight: "var(--row)", overflow: "auto" },
  ".cm-content": { caretColor: "var(--fg)", padding: "0" },
  ".cm-line": { padding: "0 4px" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--fg)", borderLeftWidth: "2px" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": { backgroundColor: "var(--sel)" },
  ".cm-gutters": { backgroundColor: "var(--bg)", color: "var(--fg-dim)", border: "none", borderRight: "1px solid var(--line)" },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 6px 0 4px", minWidth: "3ch" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--fg)" },
  "&.cm-focused .cm-matchingBracket": { backgroundColor: "transparent", color: "var(--accent)", outline: "1px solid var(--accent)" },
  "&.cm-focused .cm-nonmatchingBracket": { backgroundColor: "transparent", color: "var(--err)" },
  ".cm-sbx-errline": { outline: "1px solid var(--err)", outlineOffset: "-1px" },
  ".cm-sbx-msg": { color: "var(--err)", padding: "0 4px", whiteSpace: "pre-wrap", borderBottom: "1px solid var(--err)" },
  // The auto-complete popup: flat, with the app's colours (no shadows or radii).
  ".cm-tooltip": { backgroundColor: "var(--bg)", color: "var(--fg)", border: "1px solid var(--line)", borderRadius: "0" },
  ".cm-tooltip.cm-tooltip-autocomplete > ul": { fontFamily: "var(--font)", maxHeight: "14em" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "var(--sel)", color: "var(--fg)" },
  ".cm-completionDetail": { color: "var(--fg-dim)", marginLeft: "0.5em", fontStyle: "normal" },
  ".cm-completionInfo": { color: "var(--fg)", padding: "2px 6px" },
});

// ---------------------------------------------------------------------------------------------------------------------

/** The engine's compile result, read through the fields the spec names (docs/specs/PHASE_25.md section 2). */
function toOutcome(r: unknown): CheckOutcome {
  const res = r as {
    ok: boolean;
    errors?: EditorProblem[];
    program?: { meta: { title: string; overlay: boolean; inputs: Record<string, unknown>[]; usesLib: boolean } };
  };
  if (!res.ok) return { kind: "errors", errors: (res.errors ?? []).map((e) => ({ msg: e.msg, line: e.line, col: e.col })) };
  const m = res.program!.meta;
  return { kind: "ok", title: m.title, overlay: m.overlay, inputs: m.inputs, usesLib: m.usesLib };
}

export function createScriptEditor(parent: HTMLElement, opts: ScriptEditorOptions): ScriptEditor {
  // Callbacks go through an object so the extensions (built once) never call a stale function.
  const cb = { ...opts };
  let timer: ReturnType<typeof setTimeout> | undefined;
  let seq = 0; // bumped on every edit: an answer for an older text is dropped
  let view: EditorView;

  /** Compiles the current text (the engine is a lazy chunk: it downloads the first time this runs). */
  const runCheck = async (): Promise<CheckOutcome> => {
    const mine = ++seq;
    const text = view.state.doc.toString();
    let outcome: CheckOutcome;
    try {
      const { compile } = await import("./index");
      outcome = toOutcome(compile(text));
    } catch (e) {
      // The engine did not load or crashed: say so on screen (the panel shows it), never pretend the script is fine.
      outcome = { kind: "failed", message: `THE CHECKER FAILED: ${e instanceof Error ? e.message : String(e)}` };
    }
    if (mine === seq) {
      view.dispatch({ effects: setErrorsEffect.of(outcome.kind === "errors" ? outcome.errors : []) });
      cb.onChecked(outcome);
    }
    return outcome;
  };

  const extensions: Extension[] = [
    lineNumbers(),
    history(),
    drawSelection({ cursorBlinkRate: 0 }), // 0 = no blinking (nothing animates in this app)
    bracketMatching(),
    indentUnit.of("    "), // blocks are by indent: Tab inserts four spaces, never a tab character
    EditorState.tabSize.of(4),
    scriptLanguage,
    syntaxHighlighting(highlight),
    autocompletion({ override: [complete], icons: false, activateOnTyping: true }),
    theme,
    errorField,
    EditorView.contentAttributes.of({ "aria-label": opts.ariaLabel, spellcheck: "false", autocorrect: "off", autocapitalize: "off" }),
    Prec.highest(
      keymap.of([
        { key: "Mod-s", run: () => (cb.onSave(), true) },
        { key: "Mod-Enter", run: () => (cb.onRun(), true) },
        {
          key: "Escape",
          run: (v) => {
            // First Esc only closes an open suggestion list; the next one leaves the box.
            if (completionStatus(v.state)) {
              closeCompletion(v);
              return true;
            }
            v.contentDOM.blur();
            cb.onEscape();
            return true;
          },
        },
      ]),
    ),
    // Ctrl+K opens the app's command line, and the app ignores key events that something already called preventDefault on.
    // CodeMirror's default keymap binds Ctrl-k on macOS ("delete to line end"), so that one binding is removed: the key is then
    // unhandled here and bubbles out (same as bt/codeEditor.ts).
    keymap.of([indentWithTab, ...historyKeymap, ...defaultKeymap.filter((b) => b.key !== "Ctrl-k" && b.mac !== "Ctrl-k")]),
    EditorView.updateListener.of((u) => {
      if (!u.docChanged) return;
      cb.onChange(u.state.doc.toString());
      seq++; // any answer still on its way is for the old text
      clearTimeout(timer);
      timer = setTimeout(() => void runCheck(), CHECK_DELAY_MS);
    }),
  ];

  view = new EditorView({ state: EditorState.create({ doc: opts.doc, extensions }), parent });

  // Keys typed in the editor must not reach panel keys or global shortcuts (a plain `e` is a panel key, Ctrl+S is also the app's
  // "save workspace", Ctrl+W closes a panel ...). Only Ctrl/Cmd+K gets out. The listener sits on the parent in the bubble phase,
  // so CodeMirror has handled the key already.
  const guard = (e: KeyboardEvent) => {
    const isCommandLine = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k";
    if (!isCommandLine) e.stopPropagation();
  };
  parent.addEventListener("keydown", guard);

  // The first check, so errors and settings show as soon as the box opens.
  timer = setTimeout(() => void runCheck(), 0);

  return {
    setDoc(text) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        effects: setErrorsEffect.of([]),
        annotations: Transaction.addToHistory.of(false), // loading a file is not an edit: Ctrl+Z must not blank the box
      });
    },
    getDoc: () => view.state.doc.toString(),
    check: () => {
      clearTimeout(timer);
      return runCheck();
    },
    focus: () => view.focus(),
    destroy() {
      clearTimeout(timer);
      seq++; // a check still in flight must not touch the destroyed view
      parent.removeEventListener("keydown", guard);
      view.destroy();
    },
  };
}
