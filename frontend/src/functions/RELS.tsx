/** RELS (Phase 29): other tickers of the same issuer (SEC) and the listings of this ticker (OpenFIGI). Each row names its source. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "rels",
  api: "filings",
  usage: "USAGE: <SYM> RELS (US FILERS: SHARE CLASSES FROM THE SEC, LISTINGS FROM OPENFIGI)",
  keys: "V SECTION (CLASSES / LISTINGS)",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
