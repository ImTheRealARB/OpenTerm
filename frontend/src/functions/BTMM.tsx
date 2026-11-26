/** BTMM (Phase 30): Country monitor: policy rate, 2Y/10Y, FX, index, CPI, GDP, next releases. Server: /api/macrod/btmm. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "btmm",
  api: "macro",
  keys: "BTMM US|IN|UK|EA|JP",
  params: (p) => ({ country: (p.args[0] ?? "US").toUpperCase() }),
  usage: "USAGE: BTMM [US|IN|UK|EA|JP]",
});
