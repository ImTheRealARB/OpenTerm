import { useEffect, useState } from "react";
import { saveLayout } from "./command/layouts";
import { info } from "./command/status";
import { commandInputRef, prefillCommand, vimInsertMode } from "./components/CommandLine";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import { openWindowMenu, windowMenuKey } from "./components/windowMenuRun";
import { match } from "./keys/keys";
import { dispatchPanelKey } from "./keys/panelKeys";
import { exportPanelCsv } from "./functions/tableExport";
import { PerfTable } from "./perf/PerfTable";
import { GuiHelpDrawer, GuiOverlays, GuiSidebar, GuiTop, toggleHelp } from "./gui";
import { getSettings, settingsStore, toggleMode } from "./settings/runtime";
import { loadJSON, saveJSON, useStore } from "./state/store";
import {
  closePanel, cyclePanel, focusPanel, historyStep, resizeFocused, split, toggleMaximize, workspace,
} from "./state/workspace";

/** Bindings that always win over panel-local keys. */
const ALWAYS_GLOBAL = new Set(["focusCommand", "escape", "nextPanel", "prevPanel", "cheatsheet"]);

import Shortcuts from "./functions/Shortcuts";

export function App() {
  const [cheatsheet, setCheatsheet] = useState(false);
  const [hud, setHud] = useState(() => loadJSON("openterm.hud", false));
  // GUI mode: the same panels and command line, wrapped in a menu bar and sidebar. Terminal mode renders none of that.
  const gui = useStore(settingsStore, (s) => s.mode === "gui");

  useEffect(() => saveJSON("openterm.hud", hud), [hud]);

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

      if (!m) {
        // Typing anywhere starts a command.
        if (!inInput && !modified && e.key.length === 1 && input) input.focus();
        return;
      }
      // Plain keys belong to the command line while it has focus.
      if (inInput && !modified && m.action !== "escape" && m.action !== "nextPanel" && m.action !== "prevPanel") return;

      e.preventDefault();
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
          if (split("v") === null) info("PANEL LIMIT (9) REACHED");
          break;
        case "splitHorizontal":
          if (split("h") === null) info("PANEL LIMIT (9) REACHED");
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
          if (!dispatchPanelKey(workspace.get().focus, e)) info("NOTHING TO REFRESH IN THIS PANEL");
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
  }, [cheatsheet]);

  return (
    <div className="app">
      <TopBar />
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
                <Shortcuts />
                <div className="dim">ESC TO CLOSE</div>
              </div>
            )
          }
        />
      </div>
      {gui && <GuiOverlays />}
      <StatusBar />
      {hud && (
        <div className="hud">
          <PerfTable />
        </div>
      )}
    </div>
  );
}
