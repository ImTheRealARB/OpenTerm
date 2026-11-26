/** DDIS (Phase 29): debt maturity ladder from the latest 10-K that tags it (XBRL LongTermDebtMaturitiesRepaymentsOfPrincipal...). */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "ddis",
  api: "fund",
  usage: "USAGE: <SYM> DDIS (US SEC FILERS)",
  keys: "ENTER OPENS THE FILING",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
