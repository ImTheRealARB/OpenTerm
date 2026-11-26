/** FOMC (Phase 30): FOMC: calendar, statement word diff, SEP dots, links to minutes. Server: /api/macrod/fomc. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "fomc",
  api: "macro",
  keys: "ENTER OPENS THE PAGE",
  params: () => ({}),
});
