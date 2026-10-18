import { keyValueArgs } from "../research/tablePayload";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "wacc",
  valuation: true,
  usage: "USAGE: <SYM> WACC ERP=5.5 BASIS=CURRENT|TARGET [EW=90 KD= RF= BETA= TAX=]",
  keys: "NOTHING IS DEFAULTED",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = keyValueArgs(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
});
