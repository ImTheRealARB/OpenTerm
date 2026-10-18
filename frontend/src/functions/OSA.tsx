import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "osa",
  api: "deriv",
  usage: "USAGE: <SYM> OSA LEGS=+1C270@5.2,-1C290 | STRAT=BULLCALL,270,290 EXP=2026-12-18|T=0.5 [IV=25 R= MULT=100 COMM=pct]",
  keys: "C CHART · SHIFT+H J K L HEAT CURSOR",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = kvParams(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
});
