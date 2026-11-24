/** CRPR (Phase 30): Credit spreads: ICE BofA OAS (US IG / HY, euro HY, EM) from FRED. Server: /api/macrod/crpr. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "crpr",
  api: "macro",
  keys: "FRED: LAST 3 YEARS ONLY",
  params: () => ({}),
});
