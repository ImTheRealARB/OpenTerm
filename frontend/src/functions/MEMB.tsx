import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "memb",
  usage: "USAGE: MEMB SPX|NDX|DJI|RUT|MID|<ETF TICKER>",
  params: (p) => (p.args[0] ? { index: p.args[0] } : null),
});
