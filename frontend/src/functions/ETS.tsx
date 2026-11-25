/** ETS: EU Emissions Trading System verified emissions of installations whose account holder opens with the company name. EMISSIONS ONLY, NO SCORE. */
import { makeResearchPanel } from "./ResearchPanel";
import { compact, parseEsgArgs } from "./filingsArgs";

export default makeResearchPanel({
  fn: "ets",
  api: "filings",
  usage: "USAGE: <SYM> ETS [YEAR=2024] [NAME=<COMPANY WORDS>] (EU INSTALLATIONS, MATCHED ON THE ACCOUNT-HOLDER NAME)",
  keys: "EMISSIONS ONLY, NO SCORE",
  params: (p) => {
    const a = parseEsgArgs(p.args, p.security?.symbol);
    return a.symbol || a.name ? compact({ symbol: a.symbol, name: a.name, year: a.year }) : null;
  },
});
