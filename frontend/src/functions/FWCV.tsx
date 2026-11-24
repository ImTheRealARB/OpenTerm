/** FWCV (Phase 30): Forward curve bootstrapped from the Treasury par curve (1y1y, 5y5y ...). Server: /api/macrod/fwcv. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "fwcv",
  api: "macro",
  keys: "C CYCLES CHART",
  params: () => ({}),
});
