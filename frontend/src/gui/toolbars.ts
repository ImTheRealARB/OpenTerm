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
  /**
   * Listed in the help drawer but not drawn in the function band (keeps one-row bands one row: GP zoom, pan, crosshair).
   * The key itself still works from the keyboard.
   */
  bandHidden?: boolean;
  /** Press the key with Shift held (BT: `V` goes to the previous view). */
  shift?: boolean;
  /** Tooltip and help-drawer text. */
  title?: string;
  /** Opens this command in a NEW panel next to this one (GP: "IND" = the indicator library) instead of pressing `key`. */
  open?: string;
  /**
   * Show the button only for one shape of the view: "args" = the view has arguments (WL TECH: a named list),
   * "noargs" = it has none (WL alone: the index of saved lists). Both views of WL and PORT use different keys.
   */
  when?: "args" | "noargs";
  /** Show the button only when the view's first argument is this word (BT: "EDIT" = the strategy editor). Case-insensitive. */
  firstArg?: string;
  /**
   * Needs text first. `command` is the command line text to run once the user typed it: `{arg0}` becomes the view's
   * first argument (the list name), `{input}` the typed text.
   */
  ask?: { prompt: string; command: string; /** Typed text with commas is several entries: run the command once per entry ("AAPL 10 150, MSFT 5 300"). */ splitCommas?: boolean };
}

/** Function code -> its buttons, in display order. Only the eight most-used panels have per-function buttons. */
export const TOOLBARS: Readonly<Record<string, readonly ToolbarButton[]>> = {
  // The company overview: one extra button for a beginner. It sets a price alert for the panel's own stock.
  DES: [
    { label: "Set alert", key: "a", title: "Alert me when this stock goes above a price", ask: { prompt: "Alert me when it goes above (price), e.g. 200", command: "ALRT {symbol} > {input}" } },
  ],
  // The alert list: the same kind of box, for any stock ("AAPL > 200" or "AAPL -3%").
  ALRT: [
    { label: "Add an alert", key: "n", title: "New alert (N)", ask: { prompt: "Stock and level, e.g. AAPL > 200 or AAPL -3%", command: "ALRT {input}" } },
  ],
  Q: [
    { label: "Details", key: "Enter", title: "Open the description (DES) of the selected security (Enter)" },
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
    { label: "Log", key: "l", title: "Toggle the logarithmic price scale (L)" },
    { label: "Indicators", key: "i", title: "Pick indicators (I); then press the letter shown next to each one" },
    { label: "Indicators…", key: "i", open: "IND", bandHidden: true, title: "Indicator library: search, write a formula, Enter adds it to this chart" },
    { label: "Crosshair", key: "x", bandHidden: true, title: "Toggle the crosshair (X)" },
    { label: "Price alert", key: "A", shift: true, title: "Click the chart at the price for an alert (Shift+A; A uses the crosshair)" },
    { label: "Zoom +", key: "+", bandHidden: true, title: "Zoom in (+)" },
    { label: "Zoom -", key: "-", bandHidden: true, title: "Zoom out (-)" },
    { label: "<", key: "ArrowLeft", bandHidden: true, title: "Pan left, or move the crosshair when it is on (Left arrow)" },
    { label: ">", key: "ArrowRight", bandHidden: true, title: "Pan right, or move the crosshair when it is on (Right arrow)" },
  ],
  WL: [
    // A named list (WL TECH):
    { label: "Add", key: "a", when: "args", title: "Add symbols to this list (A)", ask: { prompt: "Symbols to add, e.g. AAPL MSFT", command: "WL {arg0} ADD {input}" } },
    { label: "Remove", key: "d", when: "args", title: "Remove the selected symbol (D); U undoes it" },
    { label: "Undo", key: "u", when: "args", title: "Undo the last removal (U)" },
    { label: "Sort", key: "s", when: "args", title: "Cycle the sort order (S)" },
    { label: "Details", key: "Enter", when: "args", title: "Open the description of the selected symbol (Enter)" },
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
    { label: "Add", key: "a", when: "args", title: "Add a position (A)", ask: { prompt: "Stock, shares, price paid: AAPL 10 150, MSFT 5 300", command: "PORT {arg0} ADD {input}", splitCommas: true } },
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
  SYNC: [
    { label: "Sync Kite", key: "k", title: "Read Zerodha Kite holdings into PORT (K)" },
    { label: "Sync IBKR", key: "i", title: "Read Interactive Brokers positions into PORT (I)" },
    { label: "Reload", key: "r", title: "Reload the last-sync status (R)" },
  ],
  JRNL: [
    { label: "Round trips", key: "1", title: "FIFO round trips (1)" },
    { label: "Stats", key: "2", title: "Statistics (2)" },
    { label: "Findings", key: "3", title: "Behaviour findings: heuristics over your own history (3)" },
    { label: "Shadow", key: "4", title: "Shadow Account: your entries with one fixed exit rule (4)" },
    { label: "Import", key: "i", title: "Import a trades file (I)" },
    { label: "Currency", key: "c", title: "Next currency (C)" },
    { label: "Run shadow", key: "s", bandHidden: true, title: "Run the Shadow Account job (S, in the Shadow view)" },
    { label: "Reload", key: "r", title: "Reload (R)" },
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
    { label: "MT5", key: "q", title: "Export as a MetaTrader 5 Expert Advisor, rule strategies (Q)" },
    { label: "PDF", key: "d", title: "Export a PDF report of this run (D)" },
    { label: "Excel", key: "b", title: "Export an Excel workbook of this run (B)" },
    // Only in the strategy editor (BT EDIT <name>). The panel handles T only while the code box is not focused,
    // and a press from this button moves focus to the panel first, so it works from the mouse too.
    { label: "Templates", key: "t", firstArg: "EDIT", title: "Replace the code with a starter template (T)" },
  ],
};

/** The buttons to show for a function and its current arguments (applies each button's `when`). */
export function buttonsFor(code: string | undefined, args: readonly string[]): ToolbarButton[] {
  if (!code) return [];
  return (TOOLBARS[code] ?? []).filter(
    (b) => (!b.when || (b.when === "args") === (args.length > 0)) && (!b.firstArg || b.firstArg.toUpperCase() === (args[0] ?? "").toUpperCase()),
  );
}

/**
 * The key letter shown before a button's label in the function band, pro-terminal style: "A) Add", "S) Sort".
 * Only plain letters are shown: digits (range and view pickers, whose labels already say what they are), arrows, "+", "-", Enter,
 * Shift chords and buttons that open another panel (`open`) get no prefix. Empty string = show nothing.
 */
export function keyHint(b: ToolbarButton): string {
  return !b.shift && !b.open && /^[a-z]$/i.test(b.key) ? b.key.toUpperCase() : "";
}

/** The `KeyboardEvent` init for a button's key: exactly what the browser would send for that key press. */
export function keyInit(b: ToolbarButton): KeyboardEventInit {
  return { key: b.key, shiftKey: !!b.shift, bubbles: true, cancelable: true };
}

/** Command line text for an `ask` button: `{arg0}` -> the view's first argument, `{input}` -> what the user typed. */
export function expandAsk(command: string, args: readonly string[], input: string, symbol = ""): string {
  return command.replace("{arg0}", args[0] ?? "").replace("{symbol}", symbol).replace("{input}", input.trim());
}

/** The command lines an `ask` button runs for the typed text (one per comma-separated entry when `splitCommas`). */
export function askCommands(ask: NonNullable<ToolbarButton["ask"]>, args: readonly string[], input: string, symbol = ""): string[] {
  const parts = ask.splitCommas ? input.split(",").map((p) => p.trim()).filter(Boolean) : [input];
  return parts.map((p) => expandAsk(ask.command, args, p, symbol));
}

/** The `ask` button with this label for a function, ignoring its `when` (a panel's empty state may open it from any view). */
export function askButton(code: string | undefined, label: string): ToolbarButton | undefined {
  return code ? (TOOLBARS[code] ?? []).find((b) => b.label === label && b.ask) : undefined;
}
