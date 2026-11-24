/** FLD (Phase 31): the QRY field catalog. Each field names its source, unit, update frequency and whether it needs a key.
 * `FLD valuation` searches names, labels and sources by words. */
import { researchApi } from "../net/researchApi";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "fld",
  keys: "QRY USES THESE",
  params: (p) => ({ q: p.args.join(" ") }),
  loader: (params) => researchApi.fields(String(params.q ?? "")),
});
