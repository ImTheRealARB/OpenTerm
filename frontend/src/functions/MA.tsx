/** MA (Phase 29): deal filings (8-K items 1.01 / 2.01, tender offers, merger proxies, S-4, 425). A symbol = one company; none = market-wide. */
import { makeResearchPanel } from "./ResearchPanel";
import { compact, parseMaArgs } from "./filingsArgs";
import { filingsRowKey } from "./filingsKeys";

export default makeResearchPanel({
  fn: "ma",
  api: "filings",
  usage: "USAGE: [SYMBOL] MA [FROM=YYYY-MM-DD] [TO=YYYY-MM-DD] (NO SYMBOL = MARKET-WIDE, LAST 90 DAYS)",
  keys: "ENTER FIL · O FILING",
  params: (p) => {
    const a = parseMaArgs(p.args, p.security?.symbol);
    return compact({ symbol: a.symbol, start: a.start, end: a.end });
  },
  onKey: (e, p, _d, say, row) => filingsRowKey(e, p.panelId, row, say),
});
