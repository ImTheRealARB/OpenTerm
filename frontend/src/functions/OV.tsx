import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "ov",
  api: "deriv",
  usage: "USAGE: <SYM> OV K=350 EXP=2026-12-18|T=0.5 TYPE=C|P [IV=27 R= Q=] [MODEL inputs: V0= KAPPA= THETA= SIGMAV= RHO= | H= BARR=UO|UI|DO|DI REBATE=] [PRICE= solves IV] [STEPS=]",
  keys: "NOTHING IS DEFAULTED",
  params: (p) => {
    if (!p.security) return null;
    const { params, bad } = kvParams(p.args);
    return bad.length ? null : { symbol: p.security.symbol, ...params };
  },
});
