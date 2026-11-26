/** REVS (Phase 29): a transparent estimate revision score from the EEO trend and revision counts (inputs shown). */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "revs",
  api: "fund",
  usage: "USAGE: <SYM> REVS",
  keys: "SCORE = 50 x BREADTH + 50 x DRIFT",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
