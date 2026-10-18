import { ctArgs } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "ct",
  api: "deriv",
  usage: "USAGE: CT <ROOT>  (CL NG GC SI HG ES NQ ZN ZB ZQ ZC ZS ZW BZ HO RB ZT ZF RTY 6E)",
  keys: "C CURVE CHART",
  params: (p) => {
    const { params, bad } = ctArgs(p.args);
    return bad.length || !params.root ? null : params;
  },
});
