/** WPE (Phase 30): World index valuation via index ETFs: P/E, P/B, P/S, yield (PROXY). Server: /api/macrod/wpe. */
import { makeResearchPanel } from "./ResearchPanel";
import { macroRowKey } from "./macroRowKey";

export default makeResearchPanel({
  fn: "wpe",
  api: "macro",
  keys: "ENTER OPENS DES",
  params: () => ({}),
  onKey: (e, p, _d, say, row) => macroRowKey(e, p.panelId, row, say),
});
