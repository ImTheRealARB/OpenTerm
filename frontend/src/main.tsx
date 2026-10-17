import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startAlerts } from "./command/alerts"; // Phase 8
import { history } from "./command/history";
import { FUNCTION_LIST, loadModule } from "./functions/registry";
import { afterPaint, installObservers } from "./perf/metrics";
import { connect } from "./net/socket";
import { pollSources } from "./net/sources";
import "./styles.css";

installObservers();
createRoot(document.getElementById("root")!).render(<App />);

afterPaint(() => {
  performance.mark("openterm:ready");
  window.__openterm_perf!.ready = performance.now();
  connect();
  startAlerts(); // Phase 8: alert symbols are watched app-wide, not only while ALRT is open
  pollSources();
  void history.sync().catch(() => {}); // backend down: history starts empty and still works in memory
  addEventListener("pagehide", () => history.flushOnExit());
  // Warm function modules while idle so the first command doesn't wait on a chunk download.
  const idle = window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 200));
  idle(() => FUNCTION_LIST.forEach((f) => f.idlePreload !== false && f.load && loadModule(f.code).catch(() => {})));
});
