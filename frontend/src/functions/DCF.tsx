import { keyValueArgs } from "../research/tablePayload";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "dcf",
  valuation: true,
  usage: "USAGE: <SYM> DCF ERP=5.5 G=2.5 EXITX=14 GROWTH=5 BASIS=CURRENT|TARGET CONV=MID|END TV=PERP|EXIT OTHER=0 [KD= RF= BETA= TAX= YEARS= EW=]",
  keys: "NOTHING IS DEFAULTED",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = keyValueArgs(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
});
