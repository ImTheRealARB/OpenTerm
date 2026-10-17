import { useEffect, useState } from "react";
import { saveLayout } from "./command/layouts";
import { info } from "./command/status";
import { commandInputRef, prefillCommand } from "./components/CommandLine";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import { match } from "./keys/keys";
import { dispatchPanelKey } from "./keys/panelKeys";
import { PerfTable } from "./perf/PerfTable";
import { loadJSON, saveJSON } from "./state/store";
import {
  closePanel, cyclePanel, focusPanel, historyStep, resizeFocused, split, toggleMaximize, workspace,
} from "./state/workspace";

/** Bindings that always win over panel-local keys. */
const ALWAYS_GLOBAL = new Set(["focusCommand", "escape", "nextPanel", "prevPanel", "cheatsheet"]);

import Shortcuts from "./functions/Shortcuts";

export function App() {
  const [cheatsheet, setCheatsheet] = useState(false);
  const [hud, setHud] = useState(() => loadJSON("openterm.hud", false));

  useEffect(() => saveJSON("openterm.hud", hud), [hud]);

  useEffect(() => {
    // Bubble phase on window: component handlers (command line Tab/arrows) run first and may preventDefault.
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
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
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cheatsheet]);

  return (
    <div className="app">
      <TopBar />
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
      <StatusBar />
      {hud && (
        <div className="hud">
          <PerfTable />
        </div>
      )}
    </div>
  );
}
