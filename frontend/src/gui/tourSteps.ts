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
    text: "TERMINAL | GUI. Terminal mode is the keyboard-first look with no menus: faster once you know the commands. You can switch back any time (Alt+G).",
    selectors: [".mode-toggle"],
  },
  {
    title: "Panel buttons and help",
    text: "Each panel has its own button row. The ? button explains the panel: what it shows, its keys and related functions (Alt+H).",
    selectors: [".panel.focus .pt-help", ".pt-help"],
  },
];
