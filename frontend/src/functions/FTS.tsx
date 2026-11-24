/** FTS (Phase 29): SEC EDGAR full-text search. Words in quotes, optional FORM= / FROM= / TO= and a company ticker. */
import { makeResearchPanel } from "./ResearchPanel";
import { compact, FTS_USAGE, parseFtsArgs } from "./filingsArgs";
import { filingsRowKey } from "./filingsKeys";

export default makeResearchPanel({
  fn: "fts",
  api: "filings",
  usage: FTS_USAGE,
  keys: "ENTER FIL · O FILING",
  params: (p) => {
    const a = parseFtsArgs(p.args);
    return a.q || a.forms || a.symbol ? compact({ q: a.q, forms: a.forms, start: a.start, end: a.end, symbol: a.symbol }) : null;
  },
  onKey: (e, p, _d, say, row) => filingsRowKey(e, p.panelId, row, say),
});
