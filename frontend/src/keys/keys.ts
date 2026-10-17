import bindings from "./keybindings.json";
import { buildIndex, mergeBindings } from "./overrides";

export type Action = keyof typeof bindings;
export const KEYBINDINGS: Record<Action, string[]> = bindings;

export const ACTION_LABELS: Record<Action, string> = {
  focusCommand: "Focus command line",
  escape: "Blur / close overlay / back",
  focusPanel: "Focus panel N",
  nextPanel: "Next panel",
  prevPanel: "Previous panel",
  splitVertical: "Split vertical",
  splitHorizontal: "Split horizontal",
  closePanel: "Close panel",
  resizeLeft: "Move divider left",
  resizeRight: "Move divider right",
  resizeUp: "Move divider up",
  resizeDown: "Move divider down",
  maximize: "Maximize / restore panel",
  historyBack: "Panel history back",
  historyForward: "Panel history forward",
  refresh: "Refresh panel data",
  saveWorkspace: "Save layout (re-saves the current named layout)",
  openWorkspace: "Open a saved layout",
  cheatsheet: "Shortcut cheatsheet",
  perfHud: "Toggle PERF HUD",
  exportCsv: "Export the focused panel's table to CSV (also E in tables)",
};

/** Canonical chord string for an event, e.g. "Ctrl+Shift+ArrowLeft". */
export function chord(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push("Ctrl");
  if (e.altKey) parts.push("Alt");
  // Shift is implied by printable symbols like "?" so only record it for named keys and letters.
  let key = e.key;
  if (key.length === 1) key = key.toUpperCase();
  const printableSymbol = e.key.length === 1 && !/[a-z0-9]/i.test(e.key);
  if (e.shiftKey && !printableSymbol) parts.push("Shift");
  // With Ctrl+Shift, e.key may be the shifted symbol; fall back to the physical digit.
  if (/^Digit[0-9]$/.test(e.code) && (e.ctrlKey || e.altKey)) key = e.code.slice(5);
  parts.push(key);
  return parts.join("+");
}

// Phase 10: user overrides (SETTINGS) are merged on top of keybindings.json; the index is rebuilt on change.
let effective: Record<Action, string[]> = mergeBindings(KEYBINDINGS, undefined) as Record<Action, string[]>;
let index = buildIndex(effective);

/** Applies keybinding overrides from settings (an action -> chords map; {} restores the defaults). */
export function setKeyOverrides(overrides: Record<string, string[]> | undefined): void {
  effective = mergeBindings(KEYBINDINGS, overrides) as Record<Action, string[]>;
  index = buildIndex(effective);
}

/** The bindings in force (defaults + overrides), for SHORTCUTS and the SETTINGS editor. */
export const effectiveBindings = (): Record<Action, string[]> => effective;

export function match(e: KeyboardEvent): { action: Action; n?: number } | undefined {
  return index.get(chord(e)) as { action: Action; n?: number } | undefined;
}
