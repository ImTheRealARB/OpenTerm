/** CTM (Phase 30): Futures contract table: last trade and first notice per contract (rules). Server: /api/macrod/ctm. */
import { makeResearchPanel } from "./ResearchPanel";
import { macroRowKey } from "./macroRowKey";

export default makeResearchPanel({
  fn: "ctm",
  api: "macro",
  keys: "ENTER OPENS CT",
  params: (p) => ({ root: (p.args[0] ?? "CL").toUpperCase() }),
  usage: "USAGE: CTM [ROOT]",
  onKey: (e, p, _d, say, row) => macroRowKey(e, p.panelId, row, say),
});
