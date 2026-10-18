import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "mgr",
  usage: "USAGE: MGR <NAME|CIK>  (BERKSHIRE, BRIDGEWATER, RENAISSANCE, CITADEL, SCION, PERSHING ... or a CIK number)",
  params: (p) => (p.args.length ? { manager: p.args.join(" ") } : null),
});
