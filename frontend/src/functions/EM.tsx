/** EM (Phase 29): earnings matrix, quarters x fiscal years: SEC EPS and revenue, consensus estimate and surprise. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "em",
  api: "fund",
  usage: "USAGE: <SYM> EM (US SEC FILERS)",
  keys: "SURPRISE = YAHOO ACTUAL VS YAHOO ESTIMATE",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
