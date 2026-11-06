import { portfolioApi } from "../net/portfolioApi";
import type { PositionIn } from "../net/types";
import { optArgs } from "./quantArgs";
import { runQuant } from "./quantRun";
import { makeResearchPanel } from "./ResearchPanel";

/** Rows of the TRADES section -> the proposed portfolio: qty = now + trade, cost = price at proposal, closed names dropped.
 *  Each row carries the holding's currency (`ccy`, typed or read from its bars), kept so a rupee holding stays rupees (audit B-1). */
function proposal(rows: Record<string, unknown>[]): PositionIn[] {
  const out: PositionIn[] = [];
  for (const r of rows) {
    const qty = Number(r.qty_now ?? 0) + Number(r.shares ?? 0);
    const price = Number(r.price);
    if (typeof r.symbol !== "string" || !Number.isFinite(qty) || qty <= 0) continue;
    const currency = typeof r.ccy === "string" && r.ccy ? r.ccy : null;
    out.push({ symbol: r.symbol, qty, cost: Number.isFinite(price) ? price : null, currency });
  }
  return out;
}

/** PORT OPT: preview only. Key A saves the proposal as portfolio <NAME>.OPT; the original is never edited, nothing is ordered. */
export default makeResearchPanel({
  fn: "opt",
  usage: "USAGE: PORT OPT [PORTFOLIO] [METHOD=EQVOL|RP|MV|MAXDIV|HRP|TURN] [CAP=0.25] [LOOKBACK=252] [RF=0] [TC=0]",
  keys: "A SAVE AS <NAME>.OPT",
  params: (p) => {
    const { params, bad } = optArgs(p.args);
    return bad.length ? null : params;
  },
  loader: (params, ctx) => runQuant("opt", params, ctx),
  onKey: (e, p, d, say) => {
    if (e.key !== "a" && e.key !== "A") return false;
    if (e.shiftKey) return false;
    const name = (optArgs(p.args).params.portfolio ?? d?.symbol ?? "").toUpperCase();
    const trades = d?.sections.find((s) => s.id === "trades");
    if (!d || !trades) return false;
    if (!name) {
      say("NAME THE PORTFOLIO TO SAVE: PORT OPT <NAME>");
      return true;
    }
    const target = `${name.replace(/\.OPT$/, "")}.OPT`;
    const positions = proposal(trades.rows as Record<string, unknown>[]);
    say(`SAVING ${target}…`);
    // copy the original's base currency: without it the server would create <NAME>.OPT in USD (audit B-1)
    portfolioApi
      .portfolio(name)
      .then((src) => portfolioApi.putPortfolio(target, positions, src.base))
      .then(() => say(`SAVED ${target} · ${positions.length} POSITIONS · COST = PRICE AT PROPOSAL · ${name} NOT CHANGED`))
      .catch((err: { message?: string }) => say(`NOT SAVED: ${err.message ?? "ERROR"}`));
    return true;
  },
});
