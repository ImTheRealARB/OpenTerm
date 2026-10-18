import { keyValueArgs } from "../research/tablePayload";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "rv",
  valuation: true,
  usage: "USAGE: <SYM> RV [PEERS=MSFT,GOOGL]",
  keys: "NOTHING IS DEFAULTED",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = keyValueArgs(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
});
