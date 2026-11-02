/**
 * Per-function toolbar buttons for GUI mode (pure data: no React, no registry import, so vitest loads it anywhere).
 *
 * A button does NOT have its own logic. It "presses" a key the panel already understands: the toolbar builds a
 * `KeyboardEvent` for `key` and hands it to the panel's own key handler (`dispatchPanelKey`, `keys/panelKeys.ts`).
 * So the mouse and the keyboard run exactly the same code, and a key that changes in a panel is the only thing to
 * update here. `toolbars.test.ts` checks that every code exists in the registry and every key is a single key.
 *
 * Buttons that need typed text (adding a symbol to a watchlist) carry an `ask`: the toolbar shows a small inline
 * box, then runs the equivalent COMMAND (`WL <name> ADD <text>`) through the same `execute()` as the command line.
 *
 * The keys below were read from each panel's `registerPanelKeys` handler (functions/Q.tsx, GP.tsx, WL.tsx ...).
 */

export interface ToolbarButton {
  /** Text on the button (short: the toolbar wraps, but long labels waste the row). */
  label: string;
  /**
   * The panel key this button stands for, as `KeyboardEvent.key` ("a", "Enter", "ArrowLeft", "5", "+", "V").
   * For an `ask` button it is only the documentation of the equivalent key (shown in the tooltip and the help drawer).
   */
  key: string;
  /** Press the key with Shift held (BT: `V` goes to the previous view). */
  shift?: boolean;
  /** Tooltip and help-drawer text. */
  title?: string;
  /**
   * Show the button only for one shape of the view: "args" = the view has arguments (WL TECH: a named list),
   * "noargs" = it has none (WL alone: the index of saved lists). Both views of WL and PORT use different keys.
   */
  when?: "args" | "noargs";
  /**
   * Needs text first. `command` is the command line text to run once the user typed it: `{arg0}` becomes the view's
   * first argument (the list name), `{input}` the typed text.
   */
  ask?: { prompt: string; command: string };
}

/** Function code -> its buttons, in display order. Only the eight most-used panels have per-function buttons. */
export const TOOLBARS: Readonly<Record<string, readonly ToolbarButton[]>> = {
  Q: [
    { label: "Open DES", key: "Enter", title: "Open the description of the selected security (Enter)" },
    { label: "Add", key: "a", title: "Add securities: puts the command in the command line (A)" },
    { label: "Remove", key: "d", title: "Remove the selected security from this monitor (D)" },
    { label: "Sort", key: "s", title: "Cycle the sort order (S)" },
  ],
  GP: [
    // Range keys 1-8 are KEY_RANGES in gpArgs.ts: 1D 5D 1M 6M YTD 1Y 5Y MAX.
    { label: "1D", key: "1", title: "Range 1 day (1)" },
    { label: "5D", key: "2", title: "Range 5 days (2)" },
    { label: "1M", key: "3", title: "Range 1 month (3)" },
    { label: "6M", key: "4", title: "Range 6 months (4)" },
    { label: "YTD", key: "5", title: "Range year to date (5)" },
    { label: "1Y", key: "6", title: "Range 1 year (6)" },
    { label: "5Y", key: "7", title: "Range 5 years (7)" },
    { label: "MAX", key: "8", title: "Range maximum (8)" },
    { label: "Type", key: "c", title: "Cycle the chart type: candles, OHLC, line, area (C)" },
    { label: "Log", key: "l", title: "Toggle the logarithmic price scale (L)" },
    { label: "Indicators", key: "i", title: "Pick indicators (I); then press the letter shown next to each one" },
    { label: "Crosshair", key: "x", title: "Toggle the crosshair (X)" },
    { label: "Zoom +", key: "+", title: "Zoom in (+)" },
    { label: "Zoom -", key: "-", title: "Zoom out (-)" },
    { label: "<", key: "ArrowLeft", title: "Pan left, or move the crosshair when it is on (Left arrow)" },
    { label: ">", key: "ArrowRight", title: "Pan right, or move the crosshair when it is on (Right arrow)" },
  ],
  WL: [
    // A named list (WL TECH):
    { label: "Add", key: "a", when: "args", title: "Add symbols to this list (A)", ask: { prompt: "Symbols to add, e.g. AAPL MSFT", command: "WL {arg0} ADD {input}" } },
    { label: "Remove", key: "d", when: "args", title: "Remove the selected symbol (D); U undoes it" },
    { label: "Undo", key: "u", when: "args", title: "Undo the last removal (U)" },
    { label: "Sort", key: "s", when: "args", title: "Cycle the sort order (S)" },
    { label: "Open DES", key: "Enter", when: "args", title: "Open the description of the selected symbol (Enter)" },
    // The index of saved lists (WL alone):
    { label: "Open list", key: "Enter", when: "noargs", title: "Open the selected watchlist (Enter)" },
    { label: "Delete list", key: "x", when: "noargs", title: "Delete the selected watchlist: press twice to confirm (X)" },
  ],
  N: [{ label: "Open article", key: "Enter", title: "Open the selected article in the browser (Enter)" }],
  WEI: [{ label: "Open chart", key: "Enter", title: "Open the chart of the selected index (Enter)" }],
  FA: [
    { label: "Income", key: "1", title: "Income statement (1)" },
    { label: "Balance", key: "2", title: "Balance sheet (2)" },
    { label: "Cash flow", key: "3", title: "Cash flow statement (3)" },
    { label: "Annual", key: "a", title: "Annual periods (A)" },
    { label: "Quarterly", key: "q", title: "Quarterly periods (Q)" },
    { label: "Older", key: "h", title: "Scroll to older periods (H)" },
    { label: "Newer", key: "l", title: "Scroll to newer periods (L)" },
  ],
  PORT: [
    // A named portfolio (PORT MAIN):
    { label: "Add", key: "a", when: "args", title: "Add a position (A)", ask: { prompt: "Position: SYMBOL QTY [COST] [CCY], e.g. AAPL 10 150", command: "PORT {arg0} ADD {input}" } },
    { label: "Remove", key: "d", when: "args", title: "Remove the selected position: press twice to confirm (D); U undoes it" },
    { label: "Undo", key: "u", when: "args", title: "Undo the last removal (U)" },
    { label: "Sort", key: "s", when: "args", title: "Cycle the sort order (S)" },
    { label: "Open chart", key: "Enter", when: "args", title: "Open the chart of the selected position (Enter)" },
    { label: "Base ccy", key: "b", when: "args", title: "Set the base currency (B)", ask: { prompt: "Base currency, e.g. INR", command: "PORT {arg0} BASE {input}" } },
    { label: "Export", key: "e", when: "args", title: "Export this portfolio as CSV (E)" },
    { label: "Import file", key: "i", when: "args", title: "Import a CSV file (I)" },
    { label: "Paste CSV", key: "v", when: "args", title: "Import by pasting CSV text (V)" },
    // The index of saved portfolios (PORT alone):
    { label: "Open portfolio", key: "Enter", when: "noargs", title: "Open the selected portfolio (Enter)" },
    { label: "Delete portfolio", key: "x", when: "noargs", title: "Delete the selected portfolio: press twice to confirm (X)" },
  ],
  BT: [
    { label: "Run again", key: "r", title: "Run the backtest again (R)" },
    { label: "Cancel", key: "x", title: "Cancel the running backtest (X)" },
    { label: "< View", key: "V", shift: true, title: "Previous view (Shift+V)" },
    { label: "View >", key: "v", title: "Next view: chart, metrics, trades, code (V)" },
    { label: "Chart", key: "1", title: "Equity chart (1)" },
    { label: "Metrics", key: "2", title: "Metrics table (2)" },
    { label: "Trades", key: "3", title: "Trades table (3)" },
    { label: "Code", key: "4", title: "Strategy code (4)" },
    { label: "Monte Carlo", key: "m", title: "Monte Carlo robustness check (M)" },
    { label: "Walk-forward", key: "w", title: "Walk-forward validation (W)" },
    { label: "Pine", key: "p", title: "Export as a Pine script (P)" },
  ],
};

/** The buttons to show for a function and its current arguments (applies each button's `when`). */
export function buttonsFor(code: string | undefined, args: readonly string[]): ToolbarButton[] {
  if (!code) return [];
  return (TOOLBARS[code] ?? []).filter((b) => !b.when || (b.when === "args") === (args.length > 0));
}

/** The `KeyboardEvent` init for a button's key: exactly what the browser would send for that key press. */
export function keyInit(b: ToolbarButton): KeyboardEventInit {
  return { key: b.key, shiftKey: !!b.shift, bubbles: true, cancelable: true };
}

/** Command line text for an `ask` button: `{arg0}` -> the view's first argument, `{input}` -> what the user typed. */
export function expandAsk(command: string, args: readonly string[], input: string): string {
  return command.replace("{arg0}", args[0] ?? "").replace("{input}", input.trim());
}
