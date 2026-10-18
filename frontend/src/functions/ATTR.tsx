import type { Envelope } from "../net/api";
import type { TablePayload } from "../research/tablePayload";
import { attrArgs } from "./quantArgs";
import { addValuation, deleteValuation, runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

/**
 * PORT ATTR: Brinson-Fachler by sector and TWR / MWR / Modified Dietz from the stored valuation table.
 * `ADD <date> VALUE= [FLOW=]` and `DEL <date>` edit that table (kv `port_vals:<name>`), then the attribution runs again.
 */
export default makeResearchPanel({
  fn: "attr",
  usage: "USAGE: PORT ATTR [PORTFOLIO] [BENCH=SPY] [RANGE=1y] | PORT ATTR <PORTFOLIO> ADD <YYYY-MM-DD> VALUE= [FLOW=] | PORT ATTR <PORTFOLIO> DEL <YYYY-MM-DD>",
  keys: "PORT ATTR <NAME> ADD <DATE> VALUE= FLOW=",
  params: (p) => {
    const { params, action, bad } = attrArgs(p.args);
    if (bad.length) return null;
    if (!action) return params;
    return { ...params, act: action.kind, date: action.date, ...(action.kind === "add" ? { value: action.value, ...(action.flow ? { flow: action.flow } : {}) } : {}) };
  },
  loader: async (params, ctx): Promise<Envelope<TablePayload>> => {
    const { act, date, value, flow, ...rest } = params;
    if (act === "add") {
      const n = await addValuation(rest.portfolio, { date, value: Number(value), flow: Number(flow ?? 0) });
      ctx.say(`ADDED VALUATION ${date} · ${n} STORED`);
    } else if (act === "del") {
      ctx.say((await deleteValuation(rest.portfolio, date)) ? `REMOVED VALUATION ${date}` : `NO VALUATION ON ${date}`);
    }
    return runQuant("attr", rest, ctx);
  },
});
