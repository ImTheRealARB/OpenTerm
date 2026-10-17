import { Suspense, lazy, useEffect, useState } from "react";
import { statusMsg } from "./command/execute";
import { commandInputRef } from "./components/CommandLine";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { Workspace } from "./components/Workspace";
import { match } from "./keys/keys";
import { PerfTable } from "./perf/PerfTable";
import { loadJSON, saveJSON } from "./state/store";
import {
  closePanel, cyclePanel, focusPanel, historyStep, resizeFocused, split, toggleMaximize,
} from "./state/workspace";

const Shortcuts = lazy(() => import("./functions/Shortcuts"));

const info = (text: string) => statusMsg.set(() => ({ text, kind: "info" }));

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
          info("NOTHING TO REFRESH: LIVE DATA ARRIVES IN PHASE 2-3");
          break;
        case "saveWorkspace":
        case "openWorkspace":
          info("WORKSPACE AUTOSAVES. NAMED LAYOUTS ARRIVE IN PHASE 4");
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
              <Suspense fallback={null}><Shortcuts /></Suspense>
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
