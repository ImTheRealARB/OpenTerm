/** BIO (Phase 29): one reporting owner's Form 3 / 4 / 5 filings across companies (SEC full-text search by CIK or name). */
import { makeResearchPanel } from "./ResearchPanel";
import { BIO_USAGE, compact, parseBioArgs } from "./filingsArgs";
import { filingsRowKey } from "./filingsKeys";

export default makeResearchPanel({
  fn: "bio",
  api: "filings",
  usage: BIO_USAGE,
  keys: "ENTER FIL (ISSUER) · O FILING",
  params: (p) => {
    const a = parseBioArgs(p.args);
    return a.q ? compact({ q: a.q, start: a.start, end: a.end }) : null;
  },
  onKey: (e, p, _d, say, row) => filingsRowKey(e, p.panelId, row, say),
});
