/** MMR (Phase 30): Money market rates: SOFR, TGCR, BGCR, EFFR, OBFR, ESTR, SONIA with history. Server: /api/macrod/mmr. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "mmr",
  api: "macro",
  keys: "OVERNIGHT REFERENCE RATES",
  params: () => ({}),
});
