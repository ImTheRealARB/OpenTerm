import { alphaArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "alpha",
  usage: "USAGE: ALPHA [UNIVERSE=TOP100|SYN|WL:<NAME>|LIST:A,B,C] [RANGE=2y] [FAMILY=...] [H=1,5,10,20]",
  keys: "HISTORICAL IC, NOT A FORECAST",
  params: (p) => {
    const { params, bad } = alphaArgs(p.args);
    return bad.length ? null : params;
  },
  loader: (params, ctx) => runQuant("alpha", params, ctx),
});
