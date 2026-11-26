/** EMOV (Phase 28): the options' implied move vs the stock's actual moves on its last 12 earnings reports (8-K item 2.02 dates). */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "emov",
  api: "deriv",
  usage: "USAGE: <SYM> EMOV (US FILERS: REPORT DATES COME FROM SEC 8-K ITEM 2.02)",
  keys: "IMPLIED = ATM STRADDLE OF THE NEAREST EXPIRY",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
