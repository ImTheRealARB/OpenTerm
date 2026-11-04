import type { Action } from "./keys";

/**
 * Human names of the keyboard actions. Only the SHORTCUTS and SETTINGS panels show them, so they live in their own
 * file (and chunk) instead of keys.ts, which every key press needs at startup.
 * scripts/gen_functions_doc.py reads this file to write docs/FUNCTIONS.md.
 */
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
  historyBack: "Panel history back (Alt+Backspace: the back key)",
  historyForward: "Panel history forward",
  refresh: "Refresh panel data",
  saveWorkspace: "Save layout (re-saves the current named layout)",
  openWorkspace: "Open a saved layout",
  cheatsheet: "Shortcut cheatsheet",
  perfHud: "Toggle PERF HUD",
  exportCsv: "Export the focused panel's table to CSV (also E in tables)",
  windowMenu: "Window menu: RECENT / RELATED / OPTIONS (arrows, 1-9, Enter)",
  toggleMode: "Switch between TERMINAL and GUI mode",
  helpDrawer: "Help drawer for the focused panel (GUI mode)",
  sectorEquity: "Sector key: EQUITY on the command line",
  sectorIndex: "Sector key: INDEX on the command line",
  sectorCurncy: "Sector key: CURNCY on the command line",
  sectorComdty: "Sector key: COMDTY on the command line",
  sectorGovt: "Sector key: GOVT on the command line",
  sectorCorp: "Sector key: CORP on the command line (no free data yet, shows why)",
};
