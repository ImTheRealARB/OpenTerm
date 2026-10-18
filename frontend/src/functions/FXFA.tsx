import { fxfaArgs } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "fxfa",
  api: "deriv",
  usage: "USAGE: FXFA <PAIR> [1W,1M,3M,6M,1Y] [R1=pct R2=pct]  (R1 = first currency's rate, R2 = second's; a currency with no free rate source needs it typed)",
  keys: "C FORWARD POINTS CHART",
  params: (p) => {
    const { params, bad } = fxfaArgs(p.args);
    return bad.length || !params.pair ? null : params;
  },
});
