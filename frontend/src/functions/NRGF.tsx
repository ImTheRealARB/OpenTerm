/** NRGF (Phase 30): Energy fundamentals: EIA weekly petroleum status and gas storage (free key). Server: /api/macrod/nrgf. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "nrgf",
  api: "macro",
  keys: "EIA WEEKLY",
  params: () => ({}),
});
