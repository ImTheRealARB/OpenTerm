import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startAlerts } from "./command/alerts"; // Phase 8
import { history } from "./command/history";
import { FUNCTION_LIST, loadModule } from "./functions/registry";
import { afterPaint, installObservers } from "./perf/metrics";
import { connect } from "./net/socket";
import { pollSources } from "./net/sources";
import "./styles.css";
import "./gui/gui.css"; // GUI-mode-only rules, all scoped under :root[data-mode="gui"]
import "./polish/lists.css"; // panel polish: Q, WL, WEI, N
import "./polish/analysis.css"; // panel polish: GP, FA, PORT, BT
import { initSettings, pollMs } from "./settings/runtime";
import { startSettingsSync } from "./settings/sync";

installObservers();
initSettings(); // Phase 10: theme, number format, keybinding overrides from the localStorage mirror (sync, no fetch)
createRoot(document.getElementById("root")!).render(<App />);

afterPaint(() => {
  performance.mark("openterm:ready");
  window.__openterm_perf!.ready = performance.now();
  connect();
  startAlerts(); // Phase 8: alert symbols are watched app-wide, not only while ALRT is open
  pollSources(pollMs("sources"));
  void startSettingsSync(); // Phase 10: reconcile with /api/settings after first paint
  void history.sync().catch(() => {}); // backend down: history starts empty and still works in memory
  addEventListener("pagehide", () => history.flushOnExit());
  // Warm function modules while idle so the first command doesn't wait on a chunk download.
  const idle = window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 200));
  idle(() => FUNCTION_LIST.forEach((f) => f.idlePreload !== false && f.load && loadModule(f.code).catch(() => {})));
});
