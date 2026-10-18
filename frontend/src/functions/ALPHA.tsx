import { alphaArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "alpha",
  usage: "USAGE: ALPHA [UNIVERSE=TOP100|SYN|WL:<NAME>|LIST:A,B,C] [RANGE=2y] [FAMILY=...] [H=1,5,10,20]",
  keys: "ENTER FORMULA · HISTORICAL IC, NOT A FORECAST",
  params: (p) => {
    const { params, bad } = alphaArgs(p.args);
    return bad.length ? null : params;
  },
  onKey: (e, _p, _d, say, row) => {
    if (e.key !== "Enter" || !row || typeof row.info !== "string") return false;
    say(`${row.id}: ${row.info}`);
    return true;
  },
  loader: (params, ctx) => runQuant("alpha", params, ctx),
});
