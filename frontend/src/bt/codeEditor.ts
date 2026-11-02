/**
 * The strategy code editor: a small wrapper around CodeMirror 6 (an open-source browser code editor library; it gives us
 * line numbers, undo history, bracket matching and Python colouring, which a plain <textarea> cannot).
 *
 * IMPORTANT: this file (and so CodeMirror, ~100 KB) must only be reached through a dynamic `import("../bt/codeEditor")`
 * from BtEditor. A dynamic import makes Vite put it in its own chunk (a separate file the browser downloads on demand),
 * so the startup bundle and the BT panel do not grow. Never import it statically, and never from a file that is itself
 * loaded at startup.
 *
 * The API is "imperative" (call methods on a handle) instead of a React component, because CodeMirror owns its own DOM
 * and its own state; React only creates it once, pushes text/errors in, and gets callbacks out.
 *
 * Look: only the CSS variables from styles.css (amber on black, themes switch them), system monospace, no shadows,
 * gradients, radii, transitions or web fonts (project rules: speed over looks, colour only carries meaning).
 */
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, HighlightStyle, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { python as pythonLanguage } from "@codemirror/lang-python";
import { EditorState, Prec, StateEffect, StateField, Transaction, type Extension } from "@codemirror/state";
import { Decoration, type DecorationSet, drawSelection, EditorView, keymap, lineNumbers, WidgetType } from "@codemirror/view";
import { tags } from "@lezer/highlight";

export interface CodeEditorOptions {
  /** Starting text. */
  doc: string;
  /** true = Python (syntax colours); false = plain text (rule strategies). */
  python: boolean;
  /** Screen-reader name of the editing area (also what the e2e tests look the box up by). */
  ariaLabel: string;
  /** Called after every edit (and after `setDoc`) with the full text. */
  onChange: (text: string) => void;
  onSave: () => void;
  onRun: () => void;
  /** Esc was pressed: the editor has already given up focus. */
  onEscape: () => void;
}

export interface CodeEditor {
  /** Replaces the whole text. Not undoable (loading a file is not an edit), and it clears any error marker. */
  setDoc: (text: string) => void;
  /** Marks `line` (1-based, clamped to the text) red and shows `message` under it. `null` clears. A null line with a message shows nothing inline (the caller shows the text elsewhere). */
  setError: (line: number | null, message?: string) => void;
  focus: () => void;
  destroy: () => void;
}

// ---------------------------------------------------------------------------------------------------------------------
// Inline error: a StateField (CodeMirror's way of keeping extra state next to the document) that holds decorations.
// A "decoration" is a mark drawn on top of the text without changing it. Two of them per error:
//   1. a line decoration: adds the CSS class `cm-sbx-errline` to the offending line (red tint),
//   2. a block widget right below that line: a small <div class="cm-sbx-msg"> with the message.
// Block widgets must come from a StateField (not from a view plugin), that is why it is not a plugin.
// ---------------------------------------------------------------------------------------------------------------------

/** The message box under the line. `eq` lets CodeMirror skip redrawing when the text did not change. */
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
    el.textContent = this.message; // textContent, not innerHTML: the text comes from the server and must never be parsed as HTML
    return el;
  }
  // A click in the message must not move the cursor into it.
  ignoreEvent() {
    return true;
  }
}

/** The effect (a message you dispatch to change a StateField): `null` clears, otherwise mark that line. */
const setErrorEffect = StateEffect.define<{ line: number; message: string } | null>();

const errorField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, tr) {
    // Keep the marker attached to its text while the user types; the live check replaces it ~400 ms later anyway.
    value = value.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setErrorEffect)) continue;
      if (e.value === null) {
        value = Decoration.none;
      } else {
        // Clamp: the server may name a line past the end (e.g. "missing SignalEngine" at EOF) or the text may have shrunk.
        const doc = tr.state.doc;
        const line = doc.line(Math.min(Math.max(e.value.line, 1), doc.lines));
        value = Decoration.set([
          Decoration.line({ class: "cm-sbx-errline" }).range(line.from),
          Decoration.widget({ widget: new ErrorWidget(e.value.message), block: true, side: 1 }).range(line.to),
        ]);
      }
    }
    return value;
  },
  // Tell the view to draw these decorations.
  provide: (f) => EditorView.decorations.from(f),
});

// ---------------------------------------------------------------------------------------------------------------------
// Theme: only CSS variables, so the app's THEME command recolours the editor with no extra code.
// ---------------------------------------------------------------------------------------------------------------------

const theme = EditorView.theme({
  "&": {
    color: "var(--fg)",
    backgroundColor: "var(--bg)",
    fontFamily: "var(--font)",
    fontSize: "var(--fs)",
    height: "22em",
  },
  "&.cm-focused": { outline: "none" }, // the focus ring is not needed: the caret and selection show focus
  ".cm-scroller": { fontFamily: "var(--font)", lineHeight: "var(--row)", overflow: "auto" },
  ".cm-content": { caretColor: "var(--fg)", padding: "0" },
  ".cm-line": { padding: "0 4px" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--fg)", borderLeftWidth: "2px" },
  // drawSelection() paints the selection as separate elements; focused vs unfocused use the same token.
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": { backgroundColor: "var(--sel)" },
  ".cm-gutters": { backgroundColor: "var(--bg)", color: "var(--fg-dim)", border: "none", borderRight: "1px solid var(--line)" },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 6px 0 4px", minWidth: "3ch" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--fg)" },
  // Brackets: matched pair gets the accent colour, an unmatched one the error colour.
  "&.cm-focused .cm-matchingBracket": { backgroundColor: "transparent", color: "var(--accent)", outline: "1px solid var(--accent)" },
  "&.cm-focused .cm-nonmatchingBracket": { backgroundColor: "transparent", color: "var(--err)" },
  // The sandbox error: red text on the line's own background, plus the message under it.
  ".cm-sbx-errline": { outline: "1px solid var(--err)", outlineOffset: "-1px" },
  ".cm-sbx-msg": { color: "var(--err)", padding: "0 4px", whiteSpace: "pre-wrap", borderBottom: "1px solid var(--err)" },
});

/** Python colours. Few and meaningful: keywords = accent, strings = up (green), numbers = bright value, comments = dim. */
const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword, tags.operatorKeyword], color: "var(--accent)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--up)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--val)" },
  { tag: tags.comment, color: "var(--fg-dim)" },
  { tag: [tags.definition(tags.variableName), tags.definition(tags.propertyName), tags.className], color: "var(--warn)" },
]);

// ---------------------------------------------------------------------------------------------------------------------

export function createCodeEditor(parent: HTMLElement, opts: CodeEditorOptions): CodeEditor {
  // Pull the latest callbacks through an object so the extensions (built once) never call a stale function.
  const cb = { ...opts };

  const extensions: Extension[] = [
    lineNumbers(),
    history(),
    drawSelection({ cursorBlinkRate: 0 }), // 0 = no blinking (nothing animates in this app)
    bracketMatching(),
    indentUnit.of("    "), // Tab / auto-indent inserts four spaces, never a tab character
    EditorState.tabSize.of(4),
    syntaxHighlighting(highlight),
    theme,
    errorField,
    EditorView.contentAttributes.of({ "aria-label": opts.ariaLabel, spellcheck: "false", autocorrect: "off", autocapitalize: "off" }),
    // Our own keys first (highest precedence), so they win over the default keymap.
    Prec.highest(
      keymap.of([
        { key: "Mod-s", run: () => (cb.onSave(), true) },
        { key: "Mod-Enter", run: () => (cb.onRun(), true) },
        {
          key: "Escape",
          run: (view) => {
            view.contentDOM.blur();
            cb.onEscape();
            return true;
          },
        },
      ]),
    ),
    // Ctrl+K opens the app's command line, and the app ignores any key event that something already called preventDefault
    // on (App.tsx). CodeMirror calls preventDefault on every key it handles, and on macOS its default keymap handles Ctrl-k
    // ("delete to line end"). So that one binding is removed: the key is then unhandled here and bubbles out to the app.
    // (Windows/Linux have no Ctrl-k in the default keymap; Cmd-k is unbound everywhere.)
    keymap.of([indentWithTab, ...historyKeymap, ...defaultKeymap.filter((b) => b.key !== "Ctrl-k" && b.mac !== "Ctrl-k")]),
    EditorView.updateListener.of((u) => {
      if (u.docChanged) cb.onChange(u.state.doc.toString());
    }),
  ];
  if (opts.python) extensions.push(pythonLanguage());

  const view = new EditorView({ state: EditorState.create({ doc: opts.doc, extensions }), parent });

  // Keys typed in the editor must not reach the panel keys / global shortcuts (a plain `j` is a panel key, and Ctrl+S is
  // ALSO the app's "save workspace" shortcut, Ctrl+W closes a panel ...). Only Ctrl/Cmd+K is let through: it is the
  // command-line shortcut and the one the editor must never swallow. The listener sits on the parent element, in the
  // bubble phase, so CodeMirror has already handled the key by the time we get it.
  const guard = (e: KeyboardEvent) => {
    const isCommandLine = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k";
    if (!isCommandLine) e.stopPropagation();
  };
  parent.addEventListener("keydown", guard);

  return {
    setDoc(text) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        effects: setErrorEffect.of(null),
        annotations: Transaction.addToHistory.of(false), // loading a file is not an edit: Ctrl+Z must not blank the box
      });
    },
    setError(line, message = "") {
      view.dispatch({ effects: setErrorEffect.of(line === null ? null : { line, message }) });
    },
    focus: () => view.focus(),
    destroy() {
      parent.removeEventListener("keydown", guard);
      view.destroy();
    },
  };
}
