/** TSYS (Phase 30): US Treasury securities: CUSIPs, coupons, maturities, auction results. Server: /api/macrod/tsys. */
import { makeResearchPanel } from "./ResearchPanel";
import { macroRowKey } from "./macroRowKey";

export default makeResearchPanel({
  fn: "tsys",
  api: "macro",
  keys: "ENTER OPENS YAS",
  params: (p): Record<string, string> => (p.args[0] ? { kind: p.args[0].toUpperCase() } : {}),
  usage: "USAGE: TSYS [BILL|NOTE|BOND|TIPS|FRN|CMB]",
  onKey: (e, p, _d, say, row) => macroRowKey(e, p.panelId, row, say),
});
