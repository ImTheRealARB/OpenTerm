/** ECFC (Phase 30): Economic forecasts: IMF WEO, OECD Outlook, Philadelphia Fed SPF, FOMC SEP. Server: /api/macrod/ecfc. */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "ecfc",
  api: "macro",
  keys: "V NEXT SOURCE",
  params: () => ({}),
});
