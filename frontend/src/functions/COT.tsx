import { wordThenKv } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "cot",
  api: "deriv",
  usage: "USAGE: COT <MARKET>  (ES NQ CL GC SI NG ZN ZB EUR JPY BTC ... or part of a CFTC market name)",
  keys: "C NET CHART",
  params: (p) => {
    const { params, bad } = wordThenKv(p.args, "market");
    return bad.length || !params.market ? null : params;
  },
});
