import { useEffect, useRef, useState, type ComponentType } from "react";
import { saveLayout } from "./command/layouts";
import { MARKET_SUFFIX } from "./command/markets";
import { applySectorWord } from "./command/sectorKeys";
import type { Sector } from "./command/sectors";
import { info, statusMsg } from "./command/status";
import { isFunction, loadModule } from "./functions/registry";
import { IDLE, isLive, keysToRow, numberSelectKey, type NumberSelectState } from "./keys/numberSelect";
import { commandInputRef, prefillCommand, vimInsertMode } from "./components/CommandLine";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import { openWindowMenu, windowMenuKey } from "./components/windowMenuRun";
import { match } from "./keys/keys";
import { dispatchPanelKey } from "./keys/panelKeys";
import { refreshPanelOrSay } from "./functions/panelRefresh";
import { exportPanelCsv } from "./functions/tableExport";
import { LazyPiece } from "./components/LazyPiece";
import { GuiHelpDrawer, GuiOverlays, GuiSidebar, GuiTop, toggleHelp } from "./gui";
import { TabStrip } from "./gui/TabStrip";
import { useTabsOn } from "./gui/tabsState";
import { useStatusBarShown } from "./gui/statusBarState";
import { getSettings, settingsStore, toggleMode } from "./settings/runtime";
import { loadJSON, saveJSON, useStore } from "./state/store";
import {
  closePanel, currentView, cyclePanel, focusPanel, historyStep, resizeFocused, splitOrSay, toggleMaximize, workspace,
} from "./state/workspace";

/** Bindings that always win over panel-local keys. */
const ALWAYS_GLOBAL = new Set(["focusCommand", "escape", "nextPanel", "prevPanel", "cheatsheet"]);

/** Sector keys (F2 ...): action -> the sector word they put on the command line. */
const SECTOR_ACTIONS: Record<string, Sector> = {
  sectorEquity: "EQUITY", sectorIndex: "INDEX", sectorCurncy: "CURNCY",
  sectorComdty: "COMDTY", sectorGovt: "GOVT", sectorCorp: "CORP",
};

// The shortcut sheet and the PERF HUD are rare overlays: each is its own chunk, not part of the startup bundle.
// (Module-level functions, so LazyPiece sees the same `load` every render.)
const loadShortcuts = () => loadModule("SHORTCUTS") as Promise<ComponentType>;
const loadHud = () => import("./perf/PerfTable").then((m) => m.PerfTable as ComponentType);
// The ticker tape bar (setting `tape`) is its own chunk too: nothing of it loads while the setting is off.
const loadTape = () => import("./home/TapeBar").then((m) => m.TapeBar as ComponentType);

export function App() {
  const [cheatsheet, setCheatsheet] = useState(false);
  const [hud, setHud] = useState(() => loadJSON("openterm.hud", false));
  // GUI mode: the same panels and command line, wrapped in a menu bar and sidebar. Terminal mode renders none of that.
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  // GUI mode hides the status bar until the user turns it on (menu bar button); Terminal mode always shows it.
  const statusShown = useStatusBarShown();
  const tabsPref = useTabsOn();
  const tapeOn = useStore(settingsStore, (s) => s.tape);
  const tabs = gui && tabsPref; // GUI tabs layout: the tab strip sits above the command line, like a browser

  useEffect(() => saveJSON("openterm.hud", hud), [hud]);

  // Number-select: digits then Enter open that row of the focused list panel (see keys/numberSelect.ts).
  const numSel = useRef<NumberSelectState>(IDLE);

  /** The focused panel's grid element (list panels draw one), or null. */
  const focusedGrid = () => document.querySelector<HTMLElement>(`[data-panel="${workspace.get().focus}"] .grid`);

  /**
   * Feeds one key to the number-select buffer. Returns true when the key was used up
   * (digit buffered, row opened, buffer dropped by Escape); false lets the key carry on.
   */
  const numberSelectStep = (e: KeyboardEvent): boolean => {
    const out = numberSelectKey(numSel.current, e.key, performance.now(), focusedGrid() !== null);
    numSel.current = out.state;
    switch (out.kind) {
      case "digit":
        e.preventDefault();
        info(`ROW ${out.state.buf}: ENTER OPENS IT, ESC CANCELS`);
        return true;
      case "open": {
        e.preventDefault();
        const rows = Number(focusedGrid()?.dataset.rows ?? 0);
        if (out.n > rows) {
          info(`NO ROW ${out.n} (${rows} ROWS)`);
          return true;
        }
        // Same as moving the cursor to the row and pressing Enter: Home, ArrowDown x (n-1), Enter.
        const id = workspace.get().focus;
        for (const key of [...keysToRow(out.n), "Enter"]) dispatchPanelKey(id, new KeyboardEvent("keydown", { key }));
        info(`ROW ${out.n}`);
        return true;
      }
      case "flush":
        // "3:GP" targets panel 3: the digits go to the command line, the colon follows by itself.
        statusMsg.set(() => null);
        prefillCommand(out.text);
        return false;
      case "clear":
        if (out.swallow) e.preventDefault();
        statusMsg.set(() => null);
        return out.swallow;
      default:
        return false;
    }
  };

  /** F2... : write the sector word on the command line (replacing an old one). */
  const sectorKey = (sector: Sector) => {
    const input = commandInputRef.current;
    const sticky = currentView(workspace.get().panels[workspace.get().focus])?.security?.symbol;
    const r = applySectorWord(input?.value ?? "", sector, sticky, (t) => t in MARKET_SUFFIX, isFunction);
    if (!r.ok) info(r.error);
    else prefillCommand(r.text);
  };

  useEffect(() => {
    // Bubble phase on window: component handlers (command line Tab/arrows) run first and may preventDefault.
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      // An open window-frame menu takes plain keys first (arrows, digits, Enter, Esc).
      if (windowMenuKey(e)) {
        e.preventDefault();
        return;
      }
      const input = commandInputRef.current;
      const inInput = document.activeElement === input;
      const m = match(e);
      const modified = e.ctrlKey || e.altKey || e.metaKey;

      // F-keys carry no modifier but are never typed text, so they work from the command line too.
      const fnKey = /^F([1-9]|1[0-2])$/.test(e.key);

      // A number is waiting for Enter ("3" then Enter opens row 3): it sees the key before the panel does.
      if (!inInput && !modified && !cheatsheet && isLive(numSel.current, performance.now())) {
        if (numberSelectStep(e)) return;
      }

      // The focused panel gets first shot at plain keys (grid j/k, chart 1..8, ...).
      if (!inInput && !modified && !cheatsheet && !(m && ALWAYS_GLOBAL.has(m.action))) {
        if (dispatchPanelKey(workspace.get().focus, e)) {
          e.preventDefault();
          return;
        }
      }

      // Phase 10: vim mode adds Ctrl+D / Ctrl+U (page down / up) to the focused grid or list.
      if (!inInput && e.ctrlKey && !e.altKey && !e.shiftKey && (e.key === "d" || e.key === "u") && getSettings().vim) {
        e.preventDefault();
        dispatchPanelKey(workspace.get().focus, new KeyboardEvent("keydown", { key: e.key === "d" ? "PageDown" : "PageUp" }));
        return;
      }

      // A digit no panel handled, over a list panel: start a row number (BT, GP ... took theirs above).
      if (!inInput && !modified && !cheatsheet && !m && e.key.length === 1 && e.key >= "0" && e.key <= "9") {
        if (focusedGrid() && numberSelectStep(e)) return;
      }

      if (!m) {
        // Typing anywhere starts a command.
        if (!inInput && !modified && e.key.length === 1 && input) input.focus();
        return;
      }
      // Plain keys belong to the command line while it has focus.
      if (inInput && !modified && !fnKey && m.action !== "escape" && m.action !== "nextPanel" && m.action !== "prevPanel") return;

      e.preventDefault();
      if (m.action in SECTOR_ACTIONS) {
        sectorKey(SECTOR_ACTIONS[m.action]);
        return;
      }
      switch (m.action) {
        case "focusCommand":
          vimInsertMode();
          input?.focus();
          input?.select();
          break;
        case "escape":
          if (cheatsheet) setCheatsheet(false);
          else if (inInput) input?.blur();
          else dispatchPanelKey(workspace.get().focus, e); // e.g. close a panel's picker
          break;
        case "focusPanel":
          if (!focusPanel(m.n!)) info(`NO PANEL ${m.n}`);
          break;
        case "nextPanel":
          cyclePanel(1);
          break;
        case "prevPanel":
          cyclePanel(-1);
          break;
        case "splitVertical":
          splitOrSay("v", info);
          break;
        case "splitHorizontal":
          splitOrSay("h", info);
          break;
        case "closePanel":
          closePanel();
          break;
        case "resizeLeft":
          resizeFocused("left");
          break;
        case "resizeRight":
          resizeFocused("right");
          break;
        case "resizeUp":
          resizeFocused("up");
          break;
        case "resizeDown":
          resizeFocused("down");
          break;
        case "maximize":
          toggleMaximize();
          break;
        case "historyBack":
          historyStep(-1);
          break;
        case "historyForward":
          historyStep(1);
          break;
        case "refresh":
          refreshPanelOrSay(workspace.get().focus); // calls what the panel registered, whatever key `refresh` is bound to
          break;
        case "saveWorkspace": {
          // Re-save the named layout in use; otherwise ask for a name on the command line.
          const name = workspace.get().name;
          if (name) void saveLayout(name);
          else prefillCommand("LAYOUT SAVE ");
          break;
        }
        case "openWorkspace":
          prefillCommand("LAYOUT LOAD ");
          break;
        case "cheatsheet":
          setCheatsheet((v) => !v);
          break;
        case "perfHud":
          setHud((v) => !v);
          break;
        // --- Phase 9 ---
        case "exportCsv":
          exportPanelCsv(workspace.get().focus);
          break;
        case "windowMenu":
          input?.blur();
          openWindowMenu();
          break;
        case "toggleMode":
          toggleMode();
          break;
        case "helpDrawer":
          // The drawer is part of the GUI shell; in terminal mode say so instead of doing nothing silently.
          if (getSettings().mode === "gui") toggleHelp(workspace.get().focus);
          else info("HELP DRAWER IS A GUI MODE FEATURE: ALT+G SWITCHES MODE, OR USE HELP <FUNCTION>");
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  // numberSelectStep is re-created every render but reads only a ref and module stores (never stale state);
  // re-registering the global key listener on every render would be pure churn.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- numberSelectStep touches only a ref and stores
  }, [cheatsheet]);

  return (
    <div className={"app" + (tabs ? " has-tabs" : "") + (tapeOn ? " has-tape" : "")}>
      {tabs && <TabStrip />}
      <TopBar />
      {tapeOn && (
        <div className="tape-slot">
          <LazyPiece load={loadTape} />
        </div>
      )}
      {gui && <GuiTop />}
      {/* Same element tree in both modes so switching never remounts the panels. In terminal mode CSS makes .app-body
          `display: contents`, i.e. the wrapper disappears from the layout and the grid looks exactly as before. */}
      <div className="app-body">
        {gui && <GuiSidebar />}
        {gui && <GuiHelpDrawer />}
        <Workspace
          overlay={
            cheatsheet && (
              <div className="overlay">
                <LazyPiece load={loadShortcuts} />
                <div className="dim">ESC TO CLOSE</div>
              </div>
            )
          }
        />
      </div>
      {gui && <GuiOverlays />}
      {(!gui || statusShown) && <StatusBar />}
      {hud && (
        <div className="hud">
          <LazyPiece load={loadHud} />
        </div>
      )}
    </div>
  );
}
