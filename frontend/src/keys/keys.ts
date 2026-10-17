import bindings from "./keybindings.json";

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

const index = new Map<string, { action: Action; n?: number }>();
for (const [action, chords] of Object.entries(KEYBINDINGS) as [Action, string[]][]) {
  for (const c of chords) {
    const range = /^(.*)\+1\.\.9$/.exec(c);
    if (range) for (let n = 1; n <= 9; n++) index.set(`${range[1]}+${n}`, { action, n });
    else index.set(c, { action });
  }
}

export function match(e: KeyboardEvent): { action: Action; n?: number } | undefined {
  return index.get(chord(e));
}
