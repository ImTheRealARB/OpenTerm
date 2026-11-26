/** IBQ (Phase 29): sector or industry roll-ups (median margins, growth, valuation and their dispersion) from SEC frames. */
import { makeResearchPanel } from "./ResearchPanel";
import { ibqParams } from "./fundArgs";

export default makeResearchPanel({
  fn: "ibq",
  api: "fund",
  usage: "USAGE: IBQ [YEAR] [SECTOR|INDUSTRY|SIC|DIV]",
  keys: "IQR = DISPERSION",
  params: (p) => ibqParams(p.args),
});
