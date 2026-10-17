import { createRoot } from "react-dom/client";
import { App } from "./App";
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
  pollSources();
  // Warm function modules while idle so the first command doesn't wait on a chunk download.
  const idle = window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 200));
  idle(() => FUNCTION_LIST.forEach((f) => f.idlePreload !== false && f.load && loadModule(f.code).catch(() => {})));
});
