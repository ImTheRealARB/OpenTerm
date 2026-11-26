/** EQS BT (Phase 29): the monthly screen backtest. EQS hands its `BT ...` form to this panel (EQS.tsx). */
import { makeResearchPanel } from "./ResearchPanel";
import { eqsBtParams } from "./fundArgs";

export default makeResearchPanel({
  fn: "eqsbt",
  api: "fund",
  usage: "USAGE: EQS BT <RULES> UNIV=LIST:AAPL,MSFT,... [FROM=2021] [VS=SPY]; RULES: MARGIN OPMARGIN ROE GROWTH DE MOM12, E.G. MARGIN>0.15 GROWTH>5%",
  keys: "SURVIVORSHIP BIAS: DELISTED COMPANIES MISSING",
  params: (p) => eqsBtParams(p.args.slice(1)),
});
