/**
 * Lazy part of the command line (plain-English preview/run and the syntax hint). Loaded with `import()` the first time the
 * typed text is not a plain command or contains a space, so none of this is in the startup bundle. The command line passes
 * a small `Ui` object with its state setters; this file holds the timers and decisions.
 */
import { FUNCTIONS, isFunction } from "../functions/registry";
import { history } from "./history";
import { needsNatural, resolveNatural } from "./nlRun";
import { info } from "./status";
import type { ReactNode } from "react";
import { syntaxHint, type Hint } from "./syntaxHint";

export { needsNatural };

export interface Suggestion {
  value: string;
  label: string;
  kind: "FUNC" | "RECENT" | "SEC" | "LAYOUT" | "LIST" | "ARG" | "NL" | "MEAN";
}

export interface Ui {
  value(): string;
  setItems(items: Suggestion[]): void;
  setSel(n: number): void;
  setHint(h: ReactNode): void;
  /** The plain-English reading of the text, listed first. */
  nl: { current: Suggestion[] };
}

const NL_DEBOUNCE_MS = 150;
let timer = 0;
let seq = 0;

const meaning = (r: Awaited<ReturnType<typeof resolveNatural>>): Suggestion[] =>
  r.kind === "command"
    ? [{ value: r.command, label: "PRESS ENTER", kind: "NL" }]
    : r.kind === "choices"
      ? r.choices.map((c) => ({ value: c.command, label: c.label, kind: "MEAN" }))
      : [];

/** Plain-English preview while typing: the first suggestion shows what Enter will run. */
export function previewNl(v: string, ui: Ui): void {
  if (ui.value() !== v) return; // queued while this chunk was loading and the text has changed since
  clearTimeout(timer);
  const mine = ++seq;
  ui.nl.current = [];
  const t = v.trim();
  if (!needsNatural(v) || (!/\s/.test(t) && t.length < 4)) return;
  timer = window.setTimeout(() => {
    resolveNatural(v)
      .then((r) => {
        if (mine !== seq || ui.value() !== v) return;
        ui.nl.current = meaning(r);
        if (!ui.nl.current.length) return;
        ui.setItems(ui.nl.current);
        ui.setSel(-1);
      })
      .catch(() => {});
  }, NL_DEBOUNCE_MS);
}

/** Enter on text that may be plain English. `run` executes a command; `again` runs the text as typed (normal error path). */
export async function viaNatural(text: string, ui: Ui, run: (command: string) => void, again: () => void): Promise<void> {
  const r = await resolveNatural(text).catch(() => ({ kind: "asis" }) as const);
  if (ui.value() !== text) return; // the user kept typing
  if (r.kind === "command") run(r.command);
  else if (r.kind === "choices") {
    ui.setItems(meaning(r));
    ui.setSel(0);
    info("DID YOU MEAN: UP/DOWN + ENTER");
  } else again();
}

function hintLine(h: Hint): ReactNode {
  return (
    <div className="ac hint" role="note" data-testid="syntax-hint" aria-label="Command syntax" onMouseDown={(e) => e.preventDefault()}>
      <span>{h.code}</span>
      {h.slots.map((sl, i) => (sl.active ? <b key={i}> {sl.text}</b> : <span key={i}> {sl.text}</span>))}
      {h.slots.length === 0 && <span className="dim"> (no arguments)</span>}
      {h.values.length > 0 && <span className="dim hv" data-testid="syntax-values"> : {h.values.slice(0, 12).join(" ")}</span>}
    </div>
  );
}

/** Syntax hint line: the function's argument slots with the one being typed in bold. */
export function updateHint(v: string, ui: Ui): void {
  if (ui.value() !== v) return;
  const h = syntaxHint(v, { isFunction, argsSchema: (c) => FUNCTIONS.get(c)?.argsSchema, symbols: history.recentSecurities() });
  ui.setHint(h && hintLine(h));
  // Typing a value of the active slot ("AAPL GP 5"): list the matches so Tab completes them.
  if (h && h.token && h.values.length && !ui.nl.current.length) {
    ui.setItems(h.values.slice(0, 8).map((value) => ({ value, label: h.wantsSymbol ? "" : "ARGUMENT", kind: "ARG" as const })));
    ui.setSel(-1);
  }
}
