/**
 * RES (Phase 32): research library. Free institutional research (BIS, Fed FEDS / FEDS Notes / IFDP, ECB, RBI, arXiv q-fin), newest
 * first, filtered by words and days. Enter opens the paper on the publisher's site; `?` offers AI questions about the SELECTED paper
 * (AI reads it with its read_url tool only when you pick one: the summary is on demand). Server: /api/macrod/res.
 */
import { makeResearchPanel } from "./ResearchPanel";
import { resParams } from "./resArgs";

export default makeResearchPanel({
  fn: "res",
  api: "macro",
  keys: "ENTER OPENS THE PAPER",
  params: (p) => resParams(p.args),
});
