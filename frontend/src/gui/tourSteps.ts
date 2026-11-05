/**
 * The guided tour of GUI mode (pure data, so vitest can check it without a browser).
 *
 * Each step points at one piece of the screen by CSS selector. `selectors` are tried in order and the first one
 * that exists is highlighted; if none exists (say the user switched to terminal mode mid-tour) the caption is
 * still shown, just without an outline.
 */
export interface TourStep {
  title: string;
  text: string;
  selectors: string[];
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    title: "Menu bar",
    text: "The Sidebar button swaps the sidebar for a menu bar: the same seven headings as a row across the top. Click a heading, then a function, and it opens in the focused panel.",
    selectors: ['[data-testid="gui-menubar"] .gm-slot', '[data-testid="sidebar-toggle"]'],
  },
  {
    title: "Sidebar",
    text: "The same functions as a list, grouped by topic. Click a row to open it. To search, type a name or a command in the box at the very top.",
    selectors: ['[data-testid="gui-sidebar"]'],
  },
  {
    title: "Command line",
    text: "Type a ticker such as MSFT, a company name or a question, then press Enter (or click GO). A chart of AAPL becomes a chart of MSFT.",
    selectors: ["#cmdline"],
  },
  {
    title: "Mode switch",
    text: "TERMINAL | GUI. Terminal mode is the keyboard-first look with no menus: faster once you know the commands. You can switch back any time ({toggleMode}).",
    selectors: [".mode-toggle"],
  },
  {
    title: "Panel buttons and help",
    text: "Each panel has its own button row. The ? button explains the panel: what it shows, its keys and related functions ({helpDrawer}).",
    selectors: [".panel.focus .pt-help", ".pt-help"],
  },
];

/**
 * A step's text with the live key names filled in: `{toggleMode}` and `{helpDrawer}` become the first chord bound to that
 * action right now (so a SETTINGS KEYS rebinding shows up in the tour), or "no key bound" when the user cleared it.
 * `bindings` is `effectiveBindings()`; it is passed in so this file stays pure.
 */
export function tourText(step: TourStep, bindings: Readonly<Record<string, readonly string[]>>): string {
  return step.text.replace(/\{(\w+)\}/g, (_, action: string) => bindings[action]?.[0] ?? "no key bound");
}
