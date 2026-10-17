import { makeResearchPanel } from "./ResearchPanel";

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

export default makeResearchPanel({
  fn: "ipo",
  usage: "USAGE: IPO [YYYY-MM]",
  params: (p) => {
    const m = p.args[0];
    if (!m) return { month: "" };
    return MONTH.test(m) ? { month: m } : null;
  },
});
