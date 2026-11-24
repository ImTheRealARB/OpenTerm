/** AGRI (Phase 30): Crops: WASDE supply and use, NASS crop condition (free key). Server: /api/macrod/agri. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "agri",
  api: "macro",
  keys: "V NEXT TABLE",
  params: () => ({}),
});
