import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "wirp",
  api: "deriv",
  usage: "USAGE: WIRP  (no arguments: implied fed funds path from ZQ futures across FOMC meetings)",
  params: (p) => (p.args.length ? null : {}),
});
