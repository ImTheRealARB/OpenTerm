/** RE (Phase 30): US housing board: prices, starts, sales, mortgage rates (FRED). Server: /api/macrod/re. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "re",
  api: "macro",
  keys: "FRED",
  params: () => ({}),
});
