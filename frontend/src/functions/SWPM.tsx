import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "swpm",
  api: "deriv",
  usage: "USAGE: SWPM N=10000000 FIXED=4.0 TENOR=5 DIR=PAY|REC [FREQ=2 CURVE=TSY|FLAT:4.2]",
  keys: "NOTHING IS DEFAULTED SILENTLY",
  params: (p) => {
    const { params, bad } = kvParams(p.args);
    return bad.length ? null : params;
  },
});
