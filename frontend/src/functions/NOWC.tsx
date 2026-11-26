/** NOWC (Phase 30): GDP nowcast: Atlanta Fed GDPNow path and past quarters vs BEA. Server: /api/macrod/nowc. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "nowc",
  api: "macro",
  keys: "MODEL ESTIMATE, NOT A FORECAST",
  params: () => ({}),
});
