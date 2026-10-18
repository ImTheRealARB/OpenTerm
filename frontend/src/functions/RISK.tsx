import { riskArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "risk",
  usage: "USAGE: RISK [PORTFOLIO] [RANGE=3y] [BENCH=SPY] [CONF=95] [HOR=1]",
  keys: "HISTORICAL SIMULATION, NOT A FORECAST",
  params: (p) => {
    const { params, bad } = riskArgs(p.args);
    return bad.length ? null : params;
  },
  loader: (params, ctx) => runQuant("risk", params, ctx),
});
