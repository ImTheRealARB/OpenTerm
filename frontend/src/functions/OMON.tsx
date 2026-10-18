import { omonArgs } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "omon",
  api: "deriv",
  usage: "USAGE: <SYM> OMON [YYYY-MM-DD] [ITM|OTM|ALL] [Q=pct]",
  keys: "IV AND GREEKS COMPUTED HERE",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = omonArgs(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
});
