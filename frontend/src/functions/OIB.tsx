/** OIB (Phase 28): India F&O open-interest buildup per bar from Kite bars (long / short buildup, short covering, long unwinding). */
import { makeResearchPanel } from "./ResearchPanel";

const RANGES = new Set(["5D", "1M", "3M", "6M", "1Y"]);
const INTERVALS = new Set(["5m", "15m", "30m", "60m", "1d"]);

export default makeResearchPanel({
  fn: "oib",
  api: "deriv",
  usage: "USAGE: <F&O SYMBOL> OIB [5D|1M|3M|6M|1Y] [5m|15m|30m|60m|1d], E.G. NIFTY26NOVFUT.NFO OIB 1M 1d (NEEDS A KITE LOGIN)",
  keys: "READING = THE USUAL F&O CONVENTION",
  params: (p) => {
    if (!p.security) return null;
    const range = p.args.map((a) => a.toUpperCase()).find((a) => RANGES.has(a));
    const interval = p.args.map((a) => a.toLowerCase()).find((a) => INTERVALS.has(a));
    return { symbol: p.security.symbol, ...(range ? { range } : {}), ...(interval ? { interval } : {}) };
  },
});
