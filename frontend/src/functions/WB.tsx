/** WB (Phase 30): World government bond yields (10Y, 2Y where free; daily or monthly per row). Server: /api/macrod/wb. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "wb",
  api: "macro",
  keys: "FREQ SHOWN PER ROW",
  params: () => ({}),
});
