/** WCRS (Phase 30): Currencies ranked by return vs USD and vs INR. Server: /api/macrod/wcrs. */
import { makeResearchPanel } from "./ResearchPanel";
import { kvParams } from "./derivArgs";

export default makeResearchPanel({
  fn: "wcrs",
  api: "macro",
  keys: "V USD / INR",
  params: (p) => { const { params, bad } = kvParams(p.args); return bad.length ? null : { sort: (params.sort ?? "1M").toUpperCase() }; },
  usage: "USAGE: WCRS [SORT=1W|1M|3M|6M|YTD|1Y]",
});
