import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "yas",
  api: "deriv",
  usage: "USAGE: YAS CPN=4.5 MAT=2034-05-15 (PX=<clean>|YLD=<pct>) [FREQ=2 SETTLE=YYYY-MM-DD DAYS=ACT/ACT|30/360 FACE=100]",
  keys: "NOTHING IS DEFAULTED SILENTLY",
  params: (p) => {
    const { params, bad } = kvParams(p.args);
    return bad.length ? null : params;
  },
});
