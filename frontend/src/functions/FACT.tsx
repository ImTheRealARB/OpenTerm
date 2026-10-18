import { factArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "fact",
  usage: "USAGE: FACT <SYM|PORTFOLIO> [RANGE=3y]",
  keys: "FACTOR REGRESSION, NOT A FORECAST",
  params: (p) => {
    const { params, bad } = factArgs(p.args);
    if (bad.length) return null;
    if (!params.symbol && p.security) params.symbol = p.security.symbol;
    return params.symbol ? params : null;
  },
  loader: (params, ctx) => runQuant("fact", params, ctx),
});
