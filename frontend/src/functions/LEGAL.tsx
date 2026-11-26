/** LEGAL (Phase 29): SEC litigation releases and administrative proceedings by company name, plus CourtListener dockets (free key). */
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "legal",
  api: "filings",
  usage: "USAGE: <SYM> LEGAL (US FILERS; ROWS ARE MATCHED ON THE COMPANY NAME ONLY)",
  keys: "V SECTION (SEC / COURT) · ENTER OPENS THE ROW'S PAGE",
  params: (p) => (p.security ? { symbol: p.security.symbol } : null),
});
