/** PGRK (Phase 28): Greeks of the OCC option positions in a saved portfolio, beta-weighted delta to an index. */
import { kvParams } from "./derivArgs";
import { makeResearchPanel } from "./ResearchPanel";

export default makeResearchPanel({
  fn: "pgrk",
  api: "deriv",
  usage: "USAGE: PGRK <PORTFOLIO> [VS=SPY] (POSITIONS AS OCC SYMBOLS, E.G. AAPL260116C00200000)",
  keys: "BLACK-SCHOLES AT ATM IV",
  params: (p) => {
    const name = p.args.find((a) => !a.includes("="));
    if (!name) return null;
    const { params, bad } = kvParams(p.args.filter((a) => a.includes("=")));
    return bad.length ? null : { name, ...params };
  },
});
