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
    text: "Every function is under one of these seven headings. Click a heading, then a function, and it opens in the focused panel.",
    selectors: ['[data-testid="gui-menubar"] .gm-slot'],
  },
  {
    title: "Sidebar and search",
    text: "The same functions as a list. Type in the search box (a name, a code like GP, or a command like AAPL GP) and press Enter.",
    selectors: ['[data-testid="gui-sidebar"]'],
  },
  {
    title: "Symbol box",
    text: "Type a ticker such as MSFT and press Enter to load it into the focused panel. A chart of AAPL becomes a chart of MSFT.",
    selectors: ['[data-testid="gui-symbol"]'],
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
