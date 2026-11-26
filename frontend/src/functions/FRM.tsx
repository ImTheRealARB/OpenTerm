/** FRM (Phase 29): one XBRL concept for every SEC filer in one period (frames API), point in time with ASOF=. */
import { makeResearchPanel } from "./ResearchPanel";
import { frmParams } from "./fundArgs";

export default makeResearchPanel({
  fn: "frm",
  api: "fund",
  usage: "USAGE: FRM <US-GAAP TAG> [CY2024|CY2024Q4|CY2024Q4I] [UNIT=USD] [ASOF=YYYY-MM-DD], E.G. FRM NetIncomeLoss CY2024",
  keys: "ASOF = ONLY VALUES PUBLIC BY THAT DATE",
  params: (p) => frmParams(p.args),
});
