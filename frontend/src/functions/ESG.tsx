/** ESG (Phase 29): EMISSIONS ONLY, NO SCORE. US EPA greenhouse-gas reports of facilities whose parent text matches the company name. */
import { makeResearchPanel } from "./ResearchPanel";
import { compact, parseEsgArgs } from "./filingsArgs";

export default makeResearchPanel({
  fn: "esg",
  api: "filings",
  usage: "USAGE: <SYM> ESG [YEAR=2023] [NAME=<COMPANY WORDS>] (US FACILITIES ONLY, MATCHED ON THE NAME)",
  keys: "EMISSIONS ONLY, NO SCORE",
  params: (p) => {
    const a = parseEsgArgs(p.args, p.security?.symbol);
    return a.symbol || a.name ? compact({ symbol: a.symbol, name: a.name, year: a.year }) : null;
  },
});
