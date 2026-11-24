/** CDR (Phase 30): Exchange calendar: holidays, early closes, regular hours. Server: /api/macrod/cdr. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "cdr",
  api: "macro",
  keys: "NEXT 12 MONTHS",
  params: (p): Record<string, string> => (p.args[0] ? { year: p.args[0] } : {}),
  usage: "USAGE: CDR [YEAR]",
});
