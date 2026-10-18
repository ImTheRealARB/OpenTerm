import { qlArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "ql",
  usage: "USAGE: QL <GARCH|OU|COINT|HEDGE|COPULA|ROLL|AMIHUD|KYLE|VPIN|EVENT|DSR|ADF|HVAR> [SYMBOLS] [KEY=VALUE ...]",
  keys: "CALCULATORS ON BARS, NOT A FORECAST",
  params: (p) => {
    const { params, bad } = qlArgs(p.args);
    return bad.length ? null : params;
  },
  loader: (params, ctx) => runQuant("ql", params, ctx),
});
