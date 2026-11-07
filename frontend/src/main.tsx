import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startAlerts } from "./command/alerts"; // Phase 8
import { history } from "./command/history";
import { createSyncGate } from "./command/syncGate";
import { preloadSettingsCommands } from "./command/execute";
import { idlePreload } from "./functions/idlePreload";
import { FUNCTION_LIST, loadModule } from "./functions/registry";
import { afterPaint, installObservers } from "./perf/metrics";
import { connect, link } from "./net/socket";
import { pollSources } from "./net/sources";
import "./styles.css";
import "./fonts.css"; // bundled font presets (loaded only when used)
import "./gui/gui.css"; // GUI-mode-only rules, all scoped under :root[data-mode="gui"]
import "./polish/lists.css"; // panel polish: Q, WL, WEI, N
import "./polish/analysis.css"; // panel polish: GP, FA, PORT, BT
import { openHomeOnStart } from "./home/startup";
import { getSettings, initSettings, pollMs } from "./settings/runtime";
import { workspace } from "./state/workspace";
import { startSettingsSync } from "./settings/sync";

installObservers();
initSettings(); // Phase 10: theme, number format, keybinding overrides from the localStorage mirror (sync, no fetch)
// Setting `startup` = "home": a new session opens the HOME page instead of the saved workspace (see home/startup.ts).
openHomeOnStart(getSettings().startup, (w) => workspace.set(() => w));
createRoot(document.getElementById("root")!).render(<App />);

afterPaint(() => {
  performance.mark("openterm:ready");
  window.__openterm_perf!.ready = performance.now();
  connect();
  startAlerts(); // Phase 8: alert symbols are watched app-wide, not only while ALRT is open
  pollSources(pollMs("sources"));
  void startSettingsSync(); // Phase 10: reconcile with /api/settings after first paint
  // Backend down at page load: history starts empty and still works in memory; it loads once the link reports OK.
  const historyGate = createSyncGate(() => history.sync());
  void historyGate.attempt();
  link.subscribe(() => void historyGate.onLink(link.get().status));
  addEventListener("pagehide", () => history.flushOnExit());
  // Warm function modules while idle so the first command doesn't wait on a chunk download.
  const idle = window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 200));
  // A few chunks per idle slot, not all ~88 at once, so the first keystrokes and the first quote fetch are not starved.
  idlePreload(
    FUNCTION_LIST.filter((f) => f.idlePreload !== false && f.load).map((f) => f.code),
    loadModule,
    idle,
  );
  // THEME / SETTINGS parser chunk (see command/execute.ts). A failed idle prefetch is ignored on purpose: the first THEME or
  // SETTINGS command loads the chunk again and reports a failure then.
  idle(() => void preloadSettingsCommands().catch(() => {}));
});
