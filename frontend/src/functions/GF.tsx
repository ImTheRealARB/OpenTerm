/** GF (Phase 29): one fundamental metric or valuation multiple over time from SEC filings, optionally vs peers. */
import { makeResearchPanel } from "./ResearchPanel";
import { GF_METRICS, gfParams } from "./fundArgs";

export default makeResearchPanel({
  fn: "gf",
  api: "fund",
  usage: `USAGE: <SYM> GF [${GF_METRICS.join("|")}] [Q] [VS=MSFT,GOOGL] (US SEC FILERS)`,
  keys: "Q = QUARTERLY (MULTIPLES USE TTM)",
  params: (p) => (p.security ? { symbol: p.security.symbol, ...gfParams(p.args) } : null),
});
