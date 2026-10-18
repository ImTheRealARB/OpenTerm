import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "cdsw",
  api: "deriv",
  usage: "USAGE: CDSW SPREAD=150 REC=40 TENOR=5 RF=3 COUPON=100 N=10000000 [FREQ=4]",
  keys: "NOTHING IS DEFAULTED SILENTLY",
  params: (p) => {
    const { params, bad } = kvParams(p.args);
    return bad.length ? null : params;
  },
});
