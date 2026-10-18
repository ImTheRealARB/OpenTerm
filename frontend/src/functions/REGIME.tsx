import { regimeArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

/** CORR REGIME: the command line routes `CORR REGIME ...` here (command/execute.ts). No list: the server answers (no default basket). */
export default makeResearchPanel({
  fn: "regime",
  usage: "USAGE: CORR REGIME [WL:<NAME>|LIST:A,B,C] [WIN=60] [EDGE=0.5]",
  keys: "HISTORICAL CORRELATION STATE, NOT A FORECAST",
  params: (p) => {
    const { params, bad } = regimeArgs(p.args);
    return bad.length ? null : params;
  },
  loader: (params, ctx) => runQuant("regime", params, ctx),
});
